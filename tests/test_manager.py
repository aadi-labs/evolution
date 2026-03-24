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
