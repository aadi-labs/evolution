"""Tests for evolution.manager — heartbeat, runtime, and Manager orchestration."""

from __future__ import annotations

import subprocess
import textwrap
import threading
import time
from pathlib import Path

import pytest

from evolution.manager.config import (
    AgentConfig,
    EvolutionConfig,
    HeartbeatConfig,
    MilestoneConfig,
    RoleConfig,
    SessionConfig,
    StopConfig,
    TaskConfig,
)
from evolution.manager.heartbeat import HeartbeatTracker, parse_duration
from evolution.manager.manager import Manager
from evolution.manager.runtime import AgentRuntime
from evolution.manager.server import send_request


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def git_repo(tmp_path):
    """Create a bare-bones git repo for integration tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=repo,
        capture_output=True,
    )
    # Initial commit
    (repo / "README.md").write_text("# Test repo")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


@pytest.fixture
def grader_script(tmp_path):
    """A trivial grading script that prints a fixed score."""
    script = tmp_path / "grade.py"
    script.write_text(
        textwrap.dedent("""\
            import sys
            print("1.0")
            print("Looks good", file=sys.stderr)
        """)
    )
    return str(script)


@pytest.fixture
def seed_dir(tmp_path):
    """A seed directory with a single file."""
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "solution.py").write_text("# placeholder\n")
    return seed


@pytest.fixture
def evo_config(grader_script, seed_dir):
    """Build a minimal EvolutionConfig for testing."""
    return EvolutionConfig(
        session=SessionConfig(name="test-session"),
        task=TaskConfig(
            name="test-task",
            description="A test task",
            path=".",
            seed=str(seed_dir),
            grader={"script": grader_script},
            metric={"direction": "higher_is_better"},
            milestones=MilestoneConfig(baseline=0.5, target=1.0, stretch=2.0),
            stop=StopConfig(
                max_time="1h",
                max_attempts=100,
                stagnation="10m",
                stagnation_action="stop",
            ),
            workspace_strategy="git_worktree",
        ),
        roles={
            "explorer": RoleConfig(
                prompt="You are an explorer agent.",
                heartbeat=HeartbeatConfig(on_attempts=3, on_time="10m"),
            ),
        },
        agents={
            "alpha": AgentConfig(role="explorer", runtime="claude-code"),
        },
    )


# =========================================================================
# HeartbeatTracker tests
# =========================================================================


class TestParseDuration:
    def test_seconds(self):
        assert parse_duration("30s") == 30.0

    def test_minutes(self):
        assert parse_duration("10m") == 600.0

    def test_hours(self):
        assert parse_duration("2h") == 7200.0

    def test_whitespace_stripped(self):
        assert parse_duration("  5s  ") == 5.0

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("10")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("")


class TestHeartbeatTracker:
    def test_attempt_trigger(self):
        hb = HeartbeatTracker(on_attempts=2, on_time_seconds=9999)
        assert not hb.should_fire()
        hb.record_attempt()
        assert not hb.should_fire()
        hb.record_attempt()
        assert hb.should_fire()

    def test_time_trigger(self):
        # Use a very short time window
        hb = HeartbeatTracker(on_attempts=9999, on_time_seconds=0.05)
        assert not hb.should_fire()
        time.sleep(0.06)
        assert hb.should_fire()

    def test_reset(self):
        hb = HeartbeatTracker(on_attempts=1, on_time_seconds=9999)
        hb.record_attempt()
        assert hb.should_fire()
        hb.reset()
        assert not hb.should_fire()

    def test_reset_clears_time(self):
        hb = HeartbeatTracker(on_attempts=9999, on_time_seconds=0.05)
        time.sleep(0.06)
        assert hb.should_fire()
        hb.reset()
        assert not hb.should_fire()


class TestMultiHeartbeat:
    def test_different_frequencies(self):
        from evolution.manager.heartbeat import MultiHeartbeatTracker

        mhb = MultiHeartbeatTracker([
            {"name": "reflect", "every": 1},
            {"name": "consolidate", "every": 3},
        ])

        # After 1 attempt: reflect fires, consolidate doesn't
        mhb.record_attempt()
        pending = mhb.get_pending()
        assert "reflect" in pending
        assert "consolidate" not in pending

        # After 2 more (total 2 since reflect reset): reflect fires again
        mhb.record_attempt()
        pending = mhb.get_pending()
        assert "reflect" in pending
        assert "consolidate" not in pending

        # After 1 more (consolidate has seen 3 total): both fire
        mhb.record_attempt()
        pending = mhb.get_pending()
        assert "reflect" in pending
        assert "consolidate" in pending

    def test_empty_heartbeats(self):
        from evolution.manager.heartbeat import MultiHeartbeatTracker

        mhb = MultiHeartbeatTracker([])
        mhb.record_attempt()
        assert mhb.get_pending() == []

    def test_named_heartbeat_config_in_role(self):
        from evolution.manager.config import NamedHeartbeatConfig, RoleConfig

        role = RoleConfig(
            prompt="test",
            heartbeat=[
                NamedHeartbeatConfig(name="reflect", every=1),
                NamedHeartbeatConfig(name="consolidate", every=10),
            ],
        )
        assert isinstance(role.heartbeat, list)
        assert role.heartbeat[0].name == "reflect"
        assert role.heartbeat[1].every == 10

    def test_runtime_with_multi_heartbeat(self):
        from evolution.manager.config import AgentConfig, NamedHeartbeatConfig, RoleConfig
        from evolution.manager.runtime import AgentRuntime

        role = RoleConfig(
            prompt="test",
            heartbeat=[
                NamedHeartbeatConfig(name="reflect", every=2),
                NamedHeartbeatConfig(name="consolidate", every=5),
            ],
        )
        agent_cfg = AgentConfig(role="test", runtime="claude-code")
        rt = AgentRuntime("agent-1", agent_cfg, role)

        assert rt.multi_heartbeat is not None
        assert rt.heartbeat is None

        rt.multi_heartbeat.record_attempt()
        rt.multi_heartbeat.record_attempt()
        pending = rt.multi_heartbeat.get_pending()
        assert "reflect" in pending
        assert "consolidate" not in pending


# =========================================================================
# AgentRuntime tests
# =========================================================================


class TestAgentRuntime:
    def test_creation(self):
        agent_cfg = AgentConfig(role="explorer", runtime="claude-code")
        role_cfg = RoleConfig(
            prompt="test",
            heartbeat=HeartbeatConfig(on_attempts=5, on_time="1h"),
        )
        rt = AgentRuntime("alpha", agent_cfg, role_cfg)

        assert rt.name == "alpha"
        assert rt.process is None
        assert rt.worktree_path is None
        assert rt.restart_count == 0
        assert rt.paused is False

    def test_is_alive_no_process(self):
        agent_cfg = AgentConfig(role="explorer", runtime="claude-code")
        role_cfg = RoleConfig(prompt="test")
        rt = AgentRuntime("alpha", agent_cfg, role_cfg)

        assert rt.is_alive() is False

    def test_is_dead_no_process(self):
        agent_cfg = AgentConfig(role="explorer", runtime="claude-code")
        role_cfg = RoleConfig(prompt="test")
        rt = AgentRuntime("alpha", agent_cfg, role_cfg)

        assert rt.is_dead() is False

    def test_heartbeat_configured(self):
        agent_cfg = AgentConfig(role="explorer", runtime="claude-code")
        role_cfg = RoleConfig(
            prompt="test",
            heartbeat=HeartbeatConfig(on_attempts=7, on_time="2h"),
        )
        rt = AgentRuntime("alpha", agent_cfg, role_cfg)

        assert rt.heartbeat.on_attempts == 7
        assert rt.heartbeat.on_time_seconds == 7200.0


# =========================================================================
# Manager tests
# =========================================================================


class TestManagerSetup:
    def test_creates_worktrees(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        assert "alpha" in mgr.agents
        rt = mgr.agents["alpha"]
        assert rt.worktree_path is not None
        assert rt.worktree_path.is_dir()
        # Seed file should be copied
        assert (rt.worktree_path / "solution.py").exists()

    def test_shared_dir_linked(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        rt = mgr.agents["alpha"]
        shared_link = rt.worktree_path / ".evolution" / "shared"
        assert shared_link.is_symlink()

    def test_inbox_created(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        rt = mgr.agents["alpha"]
        inbox = rt.worktree_path / ".evolution" / "inbox"
        assert inbox.is_dir()

    def test_adapter_provisions(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        rt = mgr.agents["alpha"]
        # ClaudeCodeAdapter writes .claude/settings.json and CLAUDE.md
        assert (rt.worktree_path / ".claude" / "settings.json").exists()
        assert (rt.worktree_path / "CLAUDE.md").exists()


class TestManagerEval:
    def test_eval_records_attempt(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        # Make a change so git commit succeeds
        rt = mgr.agents["alpha"]
        (rt.worktree_path / "output.txt").write_text("result")

        result = mgr.handle_request({
            "type": "eval",
            "agent": "alpha",
            "description": "first attempt",
        })

        assert result["status"] == "ok"
        assert result["attempt_id"] == 1
        assert result["score"] == 1.0
        assert "Looks good" in result["feedback"]

    def test_eval_unknown_agent(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({
            "type": "eval",
            "agent": "nonexistent",
            "description": "test",
        })

        assert "error" in result

    def test_eval_paused_agent(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.agents["alpha"].paused = True

        result = mgr.handle_request({
            "type": "eval",
            "agent": "alpha",
            "description": "test",
        })

        assert "error" in result
        assert "paused" in result["error"]


class TestManagerNote:
    def test_note_add(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)

        result = mgr.handle_request({
            "type": "note",
            "agent": "alpha",
            "text": "discovered a pattern",
            "tags": ["insight"],
        })

        assert result["status"] == "ok"
        notes = mgr.notes_hub.list()
        assert len(notes) == 1
        assert notes[0].text == "discovered a pattern"


class TestManagerStatus:
    def test_status_returns_agents(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({"type": "status"})

        assert result["status"] == "ok"
        assert "alpha" in result["agents"]
        assert result["total_attempts"] == 0
        assert result["best_score"] is None


class TestManagerMsg:
    def test_msg_to_specific_agent(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({
            "type": "msg",
            "from": "beta",
            "target": "alpha",
            "message": "Try approach X",
        })

        assert result["status"] == "ok"
        assert "alpha" in result["delivered_to"]
        # Verify message file exists in inbox
        inbox = mgr.agents["alpha"].worktree_path / ".evolution" / "inbox"
        md_files = list(inbox.glob("*.md"))
        assert len(md_files) >= 1

    def test_msg_to_all(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({
            "type": "msg",
            "from": "manager",
            "target": "all",
            "message": "Attention everyone",
        })

        assert result["status"] == "ok"
        assert "alpha" in result["delivered_to"]


class TestManagerPauseResume:
    def test_pause_and_resume(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        # Pause
        result = mgr.handle_request({"type": "pause"})
        assert result["status"] == "ok"
        assert mgr.agents["alpha"].paused is True

        # Resume
        result = mgr.handle_request({"type": "resume"})
        assert result["status"] == "ok"
        assert mgr.agents["alpha"].paused is False


class TestManagerKillSpawn:
    def test_kill_removes_agent(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({"type": "kill", "agent": "alpha"})
        assert result["status"] == "ok"
        assert "alpha" not in mgr.agents

    def test_spawn_from_role(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({
            "type": "spawn",
            "name": "beta",
            "role": "explorer",
            "runtime": "claude-code",
        })

        assert result["status"] == "ok"
        assert "beta" in mgr.agents
        assert mgr.agents["beta"].worktree_path.is_dir()

    def test_spawn_clone_from(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        result = mgr.handle_request({
            "type": "spawn",
            "name": "gamma",
            "clone_from": "alpha",
        })

        assert result["status"] == "ok"
        assert "gamma" in mgr.agents


class TestManagerStopConditions:
    def test_max_attempts_stop(self, git_repo, evo_config):
        # Set max_attempts very low
        evo_config.task.stop.max_attempts = 1
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        # Record one attempt
        rt = mgr.agents["alpha"]
        (rt.worktree_path / "output.txt").write_text("result")
        mgr.handle_request({
            "type": "eval",
            "agent": "alpha",
            "description": "attempt 1",
        })

        reason = mgr.check_stop_conditions()
        assert reason is not None
        assert "Max attempts" in reason

    def test_no_stop_initially(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        reason = mgr.check_stop_conditions()
        assert reason is None

    def test_stagnation_stop(self, git_repo, evo_config):
        evo_config.task.stop.stagnation = "1s"
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        # Set stagnation start in the past
        mgr._stagnation_start = time.monotonic() - 2
        reason = mgr.check_stop_conditions()
        assert reason is not None
        assert "Stagnation" in reason


class TestManagerSaveState:
    def test_save_state_writes_json(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr._best_score = 0.95
        mgr._best_agent = "alpha"

        mgr.save_state()

        import json
        state_path = git_repo / ".evolution" / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["best_score"] == 0.95
        assert state["best_agent"] == "alpha"
        assert "alpha" in state["agents"]


class TestManagerCheckImprovement:
    def test_tracks_best_score(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        mgr._check_improvement(0.5, "alpha", "higher_is_better")
        assert mgr._best_score == 0.5

        mgr._check_improvement(0.8, "alpha", "higher_is_better")
        assert mgr._best_score == 0.8

        # Worse score should not update best
        mgr._check_improvement(0.3, "alpha", "higher_is_better")
        assert mgr._best_score == 0.8

    def test_lower_is_better(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        mgr._check_improvement(0.8, "alpha", "lower_is_better")
        assert mgr._best_score == 0.8

        mgr._check_improvement(0.5, "alpha", "lower_is_better")
        assert mgr._best_score == 0.5


# =========================================================================
# Integration test: Manager + ManagerServer over socket
# =========================================================================


class TestManagerIntegration:
    def test_eval_via_socket(self, git_repo, evo_config):
        """Full integration: setup manager, start server, send eval over socket."""
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        sock_path = mgr.socket_path
        server = mgr.server

        # Make a change so git commit works
        rt = mgr.agents["alpha"]
        (rt.worktree_path / "output.txt").write_text("integration test result")

        # Start server in background
        t = threading.Thread(
            target=lambda: server.serve_one(mgr.handle_request),
            daemon=True,
        )
        t.start()
        time.sleep(0.15)

        # Send eval request over socket
        response = send_request(sock_path, {
            "type": "eval",
            "agent": "alpha",
            "description": "integration eval",
        })

        t.join(timeout=5)

        assert response["status"] == "ok"
        assert response["score"] == 1.0
        assert response["attempt_id"] == 1

        # Verify attempt was recorded on disk
        attempts = mgr.attempts_hub.list()
        assert len(attempts) == 1
        assert attempts[0].agent == "alpha"

    def test_status_via_socket(self, git_repo, evo_config):
        """Send a status request over the socket."""
        mgr = Manager(evo_config, git_repo)
        mgr.setup()

        sock_path = mgr.socket_path
        server = mgr.server

        t = threading.Thread(
            target=lambda: server.serve_one(mgr.handle_request),
            daemon=True,
        )
        t.start()
        time.sleep(0.15)

        response = send_request(sock_path, {"type": "status"})
        t.join(timeout=5)

        assert response["status"] == "ok"
        assert "alpha" in response["agents"]
        assert response["total_attempts"] == 0


# =========================================================================
# EvalQueue integration tests
# =========================================================================


class TestInboxBroadcasts:
    def test_eval_broadcasts_leaderboard(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        rt = mgr.agents["alpha"]
        inbox = rt.worktree_path / ".evolution" / "inbox"
        messages = list(inbox.glob("*.md"))
        leaderboard_msgs = [m for m in messages if "[LEADERBOARD]" in m.read_text()]
        assert len(leaderboard_msgs) >= 1

    def test_note_broadcasts_claim(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({
            "type": "note", "agent": "alpha",
            "text": "WORKING ON: retrieval improvements",
            "tags": ["working-on"],
        })
        rt = mgr.agents["alpha"]
        inbox = rt.worktree_path / ".evolution" / "inbox"
        messages = list(inbox.glob("*.md"))
        claim_msgs = [m for m in messages if "[CLAIM]" in m.read_text()]
        assert len(claim_msgs) >= 1

    def test_milestone_broadcasts_with_prefix(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        # Score of 1.0 should hit baseline (0.5) and target (1.0) milestones
        mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        rt = mgr.agents["alpha"]
        inbox = rt.worktree_path / ".evolution" / "inbox"
        messages = list(inbox.glob("*.md"))
        milestone_msgs = [m for m in messages if "[MILESTONE]" in m.read_text()]
        assert len(milestone_msgs) >= 1


class TestManagerEvalQueue:
    def test_eval_returns_queued_when_configured(self, git_repo, evo_config):
        from evolution.manager.config import EvalQueueConfig
        evo_config.task.eval_queue = EvalQueueConfig(max_queued=8)
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        assert result["status"] == "queued"
        assert result["position"] == 1

    def test_eval_synchronous_when_no_queue(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        assert result["status"] == "ok"
        assert "score" in result


# =========================================================================
# Inbox Consolidation tests
# =========================================================================


class TestManagerClaims:
    def test_claims_returns_active(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({
            "type": "note", "agent": "alpha",
            "text": "WORKING ON: retrieval improvements",
            "tags": ["working-on"],
        })
        result = mgr.handle_request({"type": "claims"})
        assert result["status"] == "ok"
        assert len(result["claims"]) == 1
        assert result["claims"][0]["agent"] == "alpha"

    def test_claims_excludes_done(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({
            "type": "note", "agent": "alpha",
            "text": "WORKING ON: retrieval",
            "tags": ["working-on"],
        })
        mgr.handle_request({
            "type": "note", "agent": "alpha",
            "text": "DONE: retrieval",
            "tags": ["done"],
        })
        result = mgr.handle_request({"type": "claims"})
        assert len(result["claims"]) == 0

    def test_claims_multiple_agents(self, git_repo, evo_config):
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({"type": "note", "agent": "alpha", "text": "WORKING ON: retrieval", "tags": ["working-on"]})
        mgr.handle_request({"type": "note", "agent": "beta", "text": "WORKING ON: answer quality", "tags": ["working-on"]})
        result = mgr.handle_request({"type": "claims"})
        assert len(result["claims"]) == 2


class TestManagerDiff:
    def test_diff_returns_changes(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        rt = mgr.agents["alpha"]
        # Make a change in the worktree
        (rt.worktree_path / "README.md").write_text("# Modified by alpha")
        result = mgr.handle_request({"type": "diff", "agent": "alpha"})
        assert result["status"] == "ok"
        assert "Modified" in result["diff"]

    def test_diff_unknown_agent(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "diff", "agent": "nonexistent"})
        assert "error" in result

    def test_diff_no_changes(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "diff", "agent": "alpha"})
        assert result["status"] == "ok"
        assert result["diff"] == "" or result["diff"].strip() == ""


class TestManagerDiffReflink:
    def test_diff_without_git_dir(self, git_repo, evo_config):
        """Diff should work even when worktree has no .git (reflink path)."""
        evo_config.task.workspace_strategy = "reflink"
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        rt = mgr.agents["alpha"]
        # Modify a file
        (rt.worktree_path / "README.md").write_text("# Modified by alpha")
        result = mgr.handle_request({"type": "diff", "agent": "alpha"})
        assert result["status"] == "ok"
        # Should show some diff content
        assert len(result["diff"]) > 0


class TestManagerCherryPick:
    def test_cherry_pick_copies_file(self, git_repo, evo_config):
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        alpha_rt = mgr.agents["alpha"]
        (alpha_rt.worktree_path / "new_file.py").write_text("print('hello')")
        result = mgr.handle_request({
            "type": "cherry_pick",
            "source_agent": "alpha",
            "target_agent": "beta",
            "file": "new_file.py",
        })
        assert result["status"] == "ok"
        beta_rt = mgr.agents["beta"]
        assert (beta_rt.worktree_path / "new_file.py").read_text() == "print('hello')"

    def test_cherry_pick_creates_parent_dirs(self, git_repo, evo_config):
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        alpha_rt = mgr.agents["alpha"]
        deep = alpha_rt.worktree_path / "src" / "deep"
        deep.mkdir(parents=True)
        (deep / "module.py").write_text("x = 1")
        result = mgr.handle_request({
            "type": "cherry_pick",
            "source_agent": "alpha",
            "target_agent": "beta",
            "file": "src/deep/module.py",
        })
        assert result["status"] == "ok"
        beta_rt = mgr.agents["beta"]
        assert (beta_rt.worktree_path / "src" / "deep" / "module.py").read_text() == "x = 1"

    def test_cherry_pick_rejects_path_traversal(self, git_repo, evo_config):
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({
            "type": "cherry_pick",
            "source_agent": "alpha",
            "target_agent": "beta",
            "file": "../../etc/passwd",
        })
        assert "error" in result

    def test_cherry_pick_unknown_agent(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({
            "type": "cherry_pick",
            "source_agent": "nonexistent",
            "target_agent": "alpha",
            "file": "foo.py",
        })
        assert "error" in result


class TestInboxConsolidation:
    def test_consolidate_creates_digest(self, tmp_path):
        from evolution.adapters.base import AgentAdapter
        adapter = AgentAdapter()
        inbox = tmp_path / ".evolution" / "inbox"
        inbox.mkdir(parents=True)
        # Create 5 individual messages
        for i in range(5):
            (inbox / f"msg-{i}.md").write_text(f"[LEADERBOARD] update {i}")

        result = adapter.consolidate_inbox(tmp_path)

        assert result is not None
        assert result.name.startswith("DIGEST-")
        content = result.read_text()
        assert "update 0" in content
        assert "update 4" in content
        # Individual messages removed
        assert not (inbox / "msg-0.md").exists()

    def test_consolidate_skips_single_message(self, tmp_path):
        from evolution.adapters.base import AgentAdapter
        adapter = AgentAdapter()
        inbox = tmp_path / ".evolution" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "msg-0.md").write_text("only one")
        result = adapter.consolidate_inbox(tmp_path)
        assert result is None  # no consolidation needed
        assert (inbox / "msg-0.md").exists()  # not removed


# =========================================================================
# Notes tag filtering tests
# =========================================================================


class TestNotesTagFilter:
    def test_filter_by_tag(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({"type": "note", "agent": "alpha", "text": "BM25 helps", "tags": ["technique"]})
        mgr.handle_request({"type": "note", "agent": "alpha", "text": "Neo4j slow", "tags": ["dead-end"]})
        result = mgr.handle_request({"type": "notes_list", "tag": "technique"})
        assert len(result["notes"]) == 1
        assert "BM25" in result["notes"][0]["text"]

    def test_filter_by_tag_and_agent(self, git_repo, evo_config):
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({"type": "note", "agent": "alpha", "text": "technique A", "tags": ["technique"]})
        mgr.handle_request({"type": "note", "agent": "beta", "text": "technique B", "tags": ["technique"]})
        result = mgr.handle_request({"type": "notes_list", "agent": "alpha", "tag": "technique"})
        assert len(result["notes"]) == 1
        assert result["notes"][0]["text"] == "technique A"

    def test_no_tag_returns_all(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({"type": "note", "agent": "alpha", "text": "a", "tags": ["x"]})
        mgr.handle_request({"type": "note", "agent": "alpha", "text": "b", "tags": ["y"]})
        result = mgr.handle_request({"type": "notes_list"})
        assert len(result["notes"]) >= 2


# =========================================================================
# Hypothesis hub tests
# =========================================================================


class TestManagerHypotheses:
    def test_add_and_list(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "hypothesis_add", "agent": "alpha", "hypothesis": "BM25 > 0.5 hurts TR", "metric": "tr_score"})
        assert result["status"] == "ok"
        assert result["id"] == "H-1"
        listed = mgr.handle_request({"type": "hypothesis_list"})
        assert len(listed["hypotheses"]) == 1

    def test_resolve(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.handle_request({"type": "hypothesis_add", "agent": "alpha", "hypothesis": "test", "metric": "s"})
        result = mgr.handle_request({"type": "hypothesis_resolve", "id": "H-1", "agent": "alpha", "resolution": "validated", "evidence": "confirmed"})
        assert result["status"] == "ok"
        assert result["resolution"] == "validated"


# =========================================================================
# Phase tracking tests
# =========================================================================


class TestPhaseTracking:
    def test_eval_blocked_during_research(self, git_repo, evo_config):
        from evolution.manager.config import PhaseConfig
        evo_config.task.phases = [
            PhaseConfig(name="research", duration="1h", eval_blocked=True),
            PhaseConfig(name="evolve"),
        ]
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        assert result["status"] == "rejected"
        assert "Research phase" in result.get("reason", "") or "research" in result.get("reason", "").lower()

    def test_eval_allowed_without_phases(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        assert result["status"] in ("ok", "queued")

    def test_phase_transition(self, git_repo, evo_config):
        from evolution.manager.config import PhaseConfig
        evo_config.task.phases = [
            PhaseConfig(name="research", duration="0s", eval_blocked=True),  # instant
            PhaseConfig(name="evolve"),
        ]
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        import time; time.sleep(0.1)
        mgr.check_phase_transition()
        # After transition, eval should work
        result = mgr.handle_request({"type": "eval", "agent": "alpha", "description": "test"})
        assert result["status"] in ("ok", "queued")


# =========================================================================
# Convergence tests
# =========================================================================


class TestConvergence:
    def test_converge_resets_worktrees(self, git_repo, evo_config):
        from evolution.manager.config import AgentConfig
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        # Simulate alpha scoring higher
        mgr._best_score = 0.9
        mgr._best_agent = "alpha"
        # Modify alpha's worktree and commit
        alpha_rt = mgr.agents["alpha"]
        (alpha_rt.worktree_path / "solution.py").write_text("# alpha's best solution")
        subprocess.run(["git", "add", "-A"], cwd=str(alpha_rt.worktree_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "alpha work"], cwd=str(alpha_rt.worktree_path), capture_output=True)

        mgr.do_converge()

        # Beta should now have alpha's solution
        beta_rt = mgr.agents["beta"]
        assert (beta_rt.worktree_path / "solution.py").exists()
        assert "alpha's best solution" in (beta_rt.worktree_path / "solution.py").read_text()

    def test_converge_skips_when_no_evals(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        # No best agent set
        mgr.do_converge()  # should not raise

    def test_converge_best_agent_unchanged(self, git_repo, evo_config):
        from evolution.manager.config import AgentConfig
        evo_config.agents["beta"] = AgentConfig(role="explorer", runtime="claude-code")
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr._best_score = 0.9
        mgr._best_agent = "alpha"
        alpha_rt = mgr.agents["alpha"]
        (alpha_rt.worktree_path / "marker.txt").write_text("alpha marker")
        subprocess.run(["git", "add", "-A"], cwd=str(alpha_rt.worktree_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "marker"], cwd=str(alpha_rt.worktree_path), capture_output=True)

        mgr.do_converge()

        # Alpha's worktree should be untouched
        assert (alpha_rt.worktree_path / "marker.txt").read_text() == "alpha marker"


# =========================================================================
# Session archival tests
# =========================================================================


class TestSessionArchival:
    def test_archive_creates_session_dir(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr.archive_session()
        session_dir = git_repo / ".evolution" / "sessions" / "test-session"
        assert session_dir.exists()
        assert (session_dir / "state.json").exists()
        assert (session_dir / "shared" / "attempts").is_dir()

    def test_archive_includes_best_agent_branch(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        mgr._best_agent = "alpha"
        mgr._best_score = 0.95
        mgr.save_state()
        mgr.archive_session()
        import json
        state = json.loads((git_repo / ".evolution" / "sessions" / "test-session" / "state.json").read_text())
        assert state.get("best_agent_branch") == "evolution/alpha"


# =========================================================================
# Session chaining tests
# =========================================================================


class TestSessionChaining:
    def test_seed_from_loads_memory(self, git_repo, evo_config):
        # First session: create and archive
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        # Add a memory file
        memory_dir = git_repo / ".evolution" / "shared" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "insight.yaml").write_text("key insight from session 1")
        mgr._best_agent = "alpha"
        mgr._best_score = 0.9
        mgr.archive_session()

        # Second session with seed_from
        evo_config.session.seed_from = "test-session"
        mgr2 = Manager(evo_config, git_repo)
        mgr2.load_seed_from()

        # Memory should be carried over
        new_memory = git_repo / ".evolution" / "shared" / "memory" / "insight.yaml"
        assert new_memory.exists()
        assert "key insight" in new_memory.read_text()


# =========================================================================
# Merge tests
# =========================================================================


class TestManagerMerge:
    def test_merge_creates_branch(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        # Make a change and record a score
        rt = mgr.agents["alpha"]
        (rt.worktree_path / "solution.py").write_text("# best solution")
        mgr.grade_and_record("alpha", "added solution")
        # Now merge
        result = mgr.handle_request({
            "type": "merge",
            "branch": "evolution/test-merge",
        })
        assert result["status"] == "ok"
        assert result["agent"] == "alpha"
        assert result["branch"] == "evolution/test-merge"
        assert result["files_changed"] >= 1
        assert "changelog" in result
        # Verify branch exists
        br = subprocess.run(
            ["git", "branch", "--list", "evolution/test-merge"],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert "evolution/test-merge" in br.stdout

    def test_merge_dry_run(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        rt = mgr.agents["alpha"]
        (rt.worktree_path / "solution.py").write_text("# best solution")
        mgr.grade_and_record("alpha", "added solution")
        result = mgr.handle_request({
            "type": "merge",
            "dry_run": True,
        })
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert "changelog" in result
        # Branch should NOT be created
        br = subprocess.run(
            ["git", "branch", "--list", "evolution/merge"],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert "evolution/merge" not in br.stdout

    def test_merge_no_evals(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        result = mgr.handle_request({"type": "merge"})
        assert "error" in result

    def test_merge_changelog_includes_attempts(self, git_repo, evo_config):
        mgr = Manager(evo_config, git_repo)
        mgr.setup()
        rt = mgr.agents["alpha"]
        (rt.worktree_path / "solution.py").write_text("# v1")
        mgr.grade_and_record("alpha", "first attempt")
        result = mgr.handle_request({"type": "merge", "dry_run": True})
        assert "first attempt" in result["changelog"]
        assert "Top Attempts" in result["changelog"]


class TestGraderTimeoutFromConfig:
    def test_manager_passes_configured_timeout_to_grader(self, git_repo, tmp_path):
        """Manager should read grader.timeout from config and pass it to grade()."""
        script = tmp_path / "grade.py"
        script.write_text("import sys\nprint('0.5')\nprint('ok', file=sys.stderr)\n")

        config = EvolutionConfig(
            session=SessionConfig(name="test"),
            task=TaskConfig(
                name="t", description="d", path=str(git_repo), seed=".",
                grader={"script": str(script), "timeout": 42},
            ),
            roles={"r": RoleConfig(prompt="p")},
            agents={"a": AgentConfig(role="r", runtime="claude-code")},
        )

        manager = Manager(config, git_repo)
        assert manager._grader_timeout == 42

    def test_manager_grader_timeout_defaults_to_1800(self, git_repo, tmp_path):
        """When no timeout is specified, default to 1800."""
        script = tmp_path / "grade.py"
        script.write_text("print('0.5')\n")

        config = EvolutionConfig(
            session=SessionConfig(name="test"),
            task=TaskConfig(
                name="t", description="d", path=str(git_repo), seed=".",
                grader={"script": str(script)},
            ),
            roles={"r": RoleConfig(prompt="p")},
            agents={"a": AgentConfig(role="r", runtime="claude-code")},
        )

        manager = Manager(config, git_repo)
        assert manager._grader_timeout == 1800
