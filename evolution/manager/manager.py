"""Core Manager that orchestrates Evolution agents, evals, heartbeats, and lifecycle."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import ClaudeCodeAdapter
from evolution.adapters.codex import CodexAdapter
from evolution.adapters.opencode import OpenCodeAdapter
from evolution.grader.script import ScriptGrader
from evolution.hub.attempts import AttemptsHub
from evolution.hub.hypotheses import HypothesisHub
from evolution.hub.notes import NotesHub
from evolution.hub.skills import SkillsHub
from evolution.manager.config import EvolutionConfig
from evolution.manager.heartbeat import parse_duration
from evolution.manager.runtime import AgentRuntime
from evolution.manager.server import ManagerServer
from evolution.workspace.setup import WorkspaceManager

logger = logging.getLogger(__name__)

# Maps runtime name strings to adapter classes.
ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
}


class Manager:
    """Orchestrates the full Evolution session: agents, evals, heartbeats, milestones."""

    def __init__(self, config: EvolutionConfig, repo_root: Path) -> None:
        self.config = config
        self.repo_root = Path(repo_root)

        # Workspace manager
        strategy = getattr(config.task, "workspace_strategy", "auto")
        self.workspace = WorkspaceManager(self.repo_root, strategy=strategy)

        # Shared directory
        self.shared_dir = self.workspace.create_shared_dir()

        # Hubs
        self.attempts_hub = AttemptsHub(self.shared_dir / "attempts")
        self.notes_hub = NotesHub(self.shared_dir / "notes")
        self.skills_hub = SkillsHub(self.shared_dir / "skills")
        self.hypotheses_hub = HypothesisHub(self.shared_dir / "hypotheses")

        # Socket server
        self.evolution_dir = self.repo_root / ".evolution"
        self.evolution_dir.mkdir(parents=True, exist_ok=True)
        socket_path = str(self.evolution_dir / "manager.sock")
        # macOS AF_UNIX path limit is 104 bytes; use /tmp/ if too long
        if len(socket_path) > 100:
            import hashlib
            short_hash = hashlib.md5(socket_path.encode()).hexdigest()[:12]
            socket_path = f"/tmp/evolution-{short_hash}.sock"
        self.socket_path = socket_path
        self.server = ManagerServer(socket_path)

        # Agent runtimes: name -> AgentRuntime
        self.agents: dict[str, AgentRuntime] = {}

        # Session state
        self._running = False
        self._best_score: float | None = None
        self._best_agent: str | None = None
        self._stagnation_start: float = time.monotonic()
        self._session_start: float = time.monotonic()
        self._shake_up_count = 0

        # Grader (set up from config)
        self._grader: ScriptGrader | None = None
        if config.task.grader:
            script = config.task.grader.get("script")
            if script:
                self._grader = ScriptGrader(script)

        # Metric direction
        self._direction = "lower_is_better"
        if config.task.metric:
            self._direction = config.task.metric.get("direction", "lower_is_better")

        # Eval queue (optional — when configured, evals are queued not immediate)
        self._eval_queue = None
        if config.task.eval_queue:
            from evolution.manager.eval_queue import EvalQueue
            eq = config.task.eval_queue
            self._eval_queue = EvalQueue(
                max_queued=eq.max_queued,
                fairness=eq.fairness,
                rate_limit_seconds=eq.rate_limit_seconds,
            )

        # Phase tracking
        self._phases = config.task.phases or []
        self._current_phase_index = 0
        self._phase_start = time.monotonic()
        # Validate durations eagerly
        for phase in self._phases:
            if phase.duration:
                parse_duration(phase.duration)  # raises ValueError on invalid

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Provision all agents: create worktrees, copy seed, configure adapters."""
        self.load_seed_from()

        seed_path = Path(self.config.task.seed)
        if not seed_path.is_absolute():
            seed_path = self.repo_root / seed_path

        for agent_name, agent_cfg in self.config.agents.items():
            role_cfg = self.config.roles[agent_cfg.role]

            # Create worktree (git worktree add — tracked files are checked out)
            wt_path = self.workspace.create_worktree(agent_name)

            # Overlay seed files if seed path differs from repo root
            if seed_path.resolve() != self.repo_root.resolve():
                self.workspace.copy_seed(wt_path, seed_path)

            # Link shared directory
            self.workspace.link_shared(wt_path, self.shared_dir)

            # Create inbox
            self.workspace.create_inbox(wt_path)

            # Provision adapter
            adapter_cls = ADAPTERS.get(agent_cfg.runtime)
            if adapter_cls:
                adapter = adapter_cls()
                adapter.provision(wt_path, agent_cfg)
                adapter.write_instructions(
                    wt_path, role_cfg.prompt, self.config.task.description
                )

            # Create runtime
            runtime = AgentRuntime(agent_name, agent_cfg, role_cfg)
            runtime.worktree_path = wt_path
            self.agents[agent_name] = runtime

    def load_seed_from(self) -> None:
        """Load best code and memory from a previous session."""
        seed_from = self.config.session.seed_from
        if not seed_from:
            return

        session_dir = self.evolution_dir / "sessions" / seed_from
        if not session_dir.exists():
            logger.warning("seed_from session '%s' not found at %s", seed_from, session_dir)
            return

        # Copy memory from previous session
        prev_memory = session_dir / "shared" / "memory"
        new_memory = self.shared_dir / "memory"
        if prev_memory.exists():
            import shutil
            new_memory.mkdir(parents=True, exist_ok=True)
            for f in prev_memory.iterdir():
                shutil.copy2(f, new_memory / f.name)
            logger.info("Loaded %d memory files from session '%s'", len(list(prev_memory.iterdir())), seed_from)

        # Read best agent branch for potential code checkout
        state_path = session_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            best_branch = state.get("best_agent_branch")
            if best_branch:
                logger.info("Previous best: %s (branch: %s)", state.get("best_agent"), best_branch)
                # The branch still exists from the previous session's worktree
                # New worktrees will be created from HEAD; if user wants to use
                # the best branch, they should merge it to main before starting

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def handle_request(self, request: dict) -> dict:
        """Route an incoming JSON request to the appropriate handler."""
        req_type = request.get("type", "")
        try:
            if req_type == "eval":
                return self._handle_eval(request)
            elif req_type == "note":
                return self._handle_note(request)
            elif req_type == "skill":
                return self._handle_skill(request)
            elif req_type == "status":
                return self._handle_status(request)
            elif req_type == "attempts_list":
                return self._handle_attempts_list(request)
            elif req_type == "attempts_show":
                return self._handle_attempts_show(request)
            elif req_type == "notes_list":
                return self._handle_notes_list(request)
            elif req_type == "skills_list":
                return self._handle_skills_list(request)
            elif req_type == "msg":
                return self._handle_msg(request)
            elif req_type == "pause":
                return self._handle_pause(request)
            elif req_type == "resume":
                return self._handle_resume(request)
            elif req_type == "kill":
                return self._handle_kill(request)
            elif req_type == "spawn":
                return self._handle_spawn(request)
            elif req_type == "claims":
                return self._handle_claims(request)
            elif req_type == "diff":
                return self._handle_diff(request)
            elif req_type == "cherry_pick":
                return self._handle_cherry_pick(request)
            elif req_type == "hypothesis_add":
                return self._handle_hypothesis_add(request)
            elif req_type == "hypothesis_list":
                return self._handle_hypothesis_list(request)
            elif req_type == "hypothesis_resolve":
                return self._handle_hypothesis_resolve(request)
            elif req_type == "stop":
                return self._handle_stop(request)
            elif req_type == "merge":
                return self._handle_merge(request)
            else:
                return {"error": f"Unknown request type: {req_type}"}
        except Exception as exc:
            logger.exception("Error handling request type=%s", req_type)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Phase tracking
    # ------------------------------------------------------------------

    def is_eval_blocked(self) -> bool:
        """Check if current phase blocks eval submissions."""
        if not self._phases or self._current_phase_index >= len(self._phases):
            return False
        return self._phases[self._current_phase_index].eval_blocked

    def check_phase_transition(self) -> None:
        """Advance to next phase if current phase duration expired."""
        if not self._phases or self._current_phase_index >= len(self._phases):
            return
        phase = self._phases[self._current_phase_index]
        if phase.duration is None:
            return
        elapsed = time.monotonic() - self._phase_start
        if elapsed >= parse_duration(phase.duration):
            self._current_phase_index += 1
            self._phase_start = time.monotonic()
            next_name = (
                self._phases[self._current_phase_index].name
                if self._current_phase_index < len(self._phases)
                else "default"
            )
            self._broadcast_message(
                "manager",
                f"[PHASE] Phase '{phase.name}' complete. Entering '{next_name}' phase.",
            )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_eval(self, request: dict) -> dict:
        if self.is_eval_blocked():
            return {"status": "rejected", "reason": "Research phase active. Share findings with: evolution note add"}

        agent_name = request.get("agent", "")
        description = request.get("description", "")

        runtime = self.agents.get(agent_name)
        if runtime is None:
            return {"error": f"Unknown agent: {agent_name}"}

        if runtime.paused:
            return {"error": f"Agent {agent_name} is paused"}

        wt_path = runtime.worktree_path
        if wt_path is None:
            return {"error": f"Agent {agent_name} has no worktree"}

        # When an eval queue is configured, submit and return immediately
        if self._eval_queue is not None:
            return self._eval_queue.submit(agent_name, description)

        # Otherwise, grade synchronously (preserves existing behaviour)
        return self.grade_and_record(agent_name, description)

    def grade_and_record(self, agent_name: str, description: str) -> dict:
        """Run the grader, record the attempt, track heartbeat, and check improvement.

        This method is called either synchronously from ``_handle_eval`` or
        asynchronously by the eval-worker thread when an ``EvalQueue`` is active.
        """
        runtime = self.agents.get(agent_name)
        if runtime is None:
            return {"error": f"Unknown agent: {agent_name}"}

        wt_path = runtime.worktree_path
        if wt_path is None:
            return {"error": f"Agent {agent_name} has no worktree"}

        # Synthetic commit hash (no git operations)
        commit_hash = f"eval-{agent_name}-{len(self.attempts_hub.list()) + 1}"

        # Run grader
        score = None
        feedback = "No grader configured"
        metrics: dict[str, float] = {}
        if self._grader:
            grade_result = self._grader.grade(str(wt_path))
            score = grade_result.score
            feedback = grade_result.feedback
            metrics = grade_result.metrics

        # Record attempt
        attempt = self.attempts_hub.record(
            agent=agent_name,
            score=score,
            description=description,
            commit=commit_hash,
            feedback=feedback,
            metrics=metrics,
        )

        # Track heartbeat
        if runtime.multi_heartbeat is not None:
            runtime.multi_heartbeat.record_attempt()
        elif runtime.heartbeat is not None:
            runtime.heartbeat.record_attempt()

        # Check improvement
        if score is not None:
            self._check_improvement(score, agent_name, self._direction)

        # Broadcast leaderboard update
        board = self.attempts_hub.leaderboard(self._direction)
        top3 = ", ".join(f"{a.agent}={a.score}" for a in board[:3])
        self._broadcast_message("manager", f"[LEADERBOARD] {agent_name} scored {score}. Top 3: {top3}")

        result = {
            "status": "ok",
            "attempt_id": attempt.id,
            "score": score,
            "feedback": feedback,
            "improvement": attempt.improvement,
        }

        # Deliver result to agent's inbox when running asynchronously
        if self._eval_queue is not None and runtime.worktree_path:
            adapter = self._get_adapter(runtime)
            if adapter:
                msg = (
                    f"Eval complete — score: {score}, feedback: {feedback}, "
                    f"improvement: {attempt.improvement}"
                )
                adapter.deliver_message(runtime.worktree_path, "manager", msg)

        return result

    def _handle_note(self, request: dict) -> dict:
        agent = request.get("agent", "")
        text = request.get("text", "")
        tags = request.get("tags", [])

        note = self.notes_hub.add(agent=agent, text=text, tags=tags)

        # Broadcast work claims
        if "WORKING ON" in text or "working-on" in tags:
            self._broadcast_message("manager", f"[CLAIM] {agent} is {text[:200]}")

        return {"status": "ok", "agent": note.agent, "timestamp": note.timestamp}

    def _handle_skill(self, request: dict) -> dict:
        author = request.get("author", "")
        name = request.get("name", "")
        content = request.get("content", "")
        tags = request.get("tags", [])

        skill = self.skills_hub.add(author=author, name=name, content=content, tags=tags)
        return {"status": "ok", "name": skill.name, "timestamp": skill.timestamp}

    def _handle_status(self, request: dict) -> dict:
        agents_info = {}
        for name, rt in self.agents.items():
            agents_info[name] = {
                "role": rt.agent_config.role,
                "runtime": rt.agent_config.runtime,
                "alive": rt.is_alive(),
                "paused": rt.paused,
                "restart_count": rt.restart_count,
            }

        total_attempts = len(self.attempts_hub.list())

        return {
            "status": "ok",
            "agents": agents_info,
            "total_attempts": total_attempts,
            "best_score": self._best_score,
            "best_agent": self._best_agent,
        }

    def _handle_attempts_list(self, request: dict) -> dict:
        board = self.attempts_hub.leaderboard(self._direction)
        entries = []
        for a in board:
            entries.append({
                "id": a.id,
                "agent": a.agent,
                "score": a.score,
                "improvement": a.improvement,
                "timestamp": a.timestamp,
            })
        return {"status": "ok", "attempts": entries}

    def _handle_attempts_show(self, request: dict) -> dict:
        attempt_id = request.get("id")
        if attempt_id is None:
            return {"error": "Missing attempt id"}
        attempt = self.attempts_hub.get(int(attempt_id))
        if attempt is None:
            return {"error": f"Attempt {attempt_id} not found"}
        return {
            "status": "ok",
            "id": attempt.id,
            "agent": attempt.agent,
            "score": attempt.score,
            "description": attempt.description,
            "feedback": attempt.feedback,
            "commit": attempt.commit,
            "timestamp": attempt.timestamp,
            "improvement": attempt.improvement,
            "metrics": attempt.metrics,
        }

    def _handle_notes_list(self, request: dict) -> dict:
        agent = request.get("agent")
        tag_filter = request.get("tag")
        notes = self.notes_hub.list(agent=agent)
        entries = []
        for n in notes:
            # Tag filter (AND with agent filter)
            if tag_filter and tag_filter not in n.tags:
                continue
            entries.append({
                "agent": n.agent,
                "text": n.text,
                "tags": n.tags,
                "timestamp": n.timestamp,
            })
        return {"status": "ok", "notes": entries}

    def _handle_skills_list(self, request: dict) -> dict:
        skills = self.skills_hub.list()
        entries = []
        for s in skills:
            entries.append({
                "name": s.name,
                "author": s.author,
                "tags": s.tags,
                "timestamp": s.timestamp,
            })
        return {"status": "ok", "skills": entries}

    def _handle_hypothesis_add(self, request: dict) -> dict:
        agent = request.get("agent", "")
        hypothesis = request.get("hypothesis", "")
        metric = request.get("metric", "")
        h = self.hypotheses_hub.add(agent=agent, hypothesis=hypothesis, metric=metric)
        return {"status": "ok", "id": h.id, "hypothesis": h.hypothesis}

    def _handle_hypothesis_list(self, request: dict) -> dict:
        status_filter = request.get("status")
        hypotheses = self.hypotheses_hub.list(status=status_filter)
        entries = [{"id": h.id, "agent": h.agent, "hypothesis": h.hypothesis, "metric": h.metric, "status": h.status} for h in hypotheses]
        return {"status": "ok", "hypotheses": entries}

    def _handle_hypothesis_resolve(self, request: dict) -> dict:
        h_id = request.get("id", "")
        status = request.get("resolution", "")
        resolved_by = request.get("agent", "")
        evidence = request.get("evidence", "")
        h = self.hypotheses_hub.resolve(h_id, status=status, resolved_by=resolved_by, evidence=evidence)
        if h is None:
            return {"error": f"Hypothesis {h_id} not found"}
        return {"status": "ok", "id": h.id, "resolution": h.status}

    def _handle_msg(self, request: dict) -> dict:
        sender = request.get("from", "manager")
        message = request.get("message", "")
        target = request.get("target")  # agent name, "all", or role name

        if not message:
            return {"error": "Empty message"}

        delivered_to = []
        if target == "all":
            for name, rt in self.agents.items():
                if rt.worktree_path:
                    adapter = self._get_adapter(rt)
                    if adapter:
                        adapter.deliver_message(rt.worktree_path, sender, message)
                        delivered_to.append(name)
        elif target in self.agents:
            rt = self.agents[target]
            if rt.worktree_path:
                adapter = self._get_adapter(rt)
                if adapter:
                    adapter.deliver_message(rt.worktree_path, sender, message)
                    delivered_to.append(target)
        else:
            # Treat target as a role name
            for name, rt in self.agents.items():
                if rt.agent_config.role == target and rt.worktree_path:
                    adapter = self._get_adapter(rt)
                    if adapter:
                        adapter.deliver_message(rt.worktree_path, sender, message)
                        delivered_to.append(name)

        return {"status": "ok", "delivered_to": delivered_to}

    def _handle_pause(self, request: dict) -> dict:
        agent_name = request.get("agent")
        if agent_name and agent_name in self.agents:
            targets = [agent_name]
        else:
            targets = list(self.agents.keys())

        for name in targets:
            rt = self.agents[name]
            rt.paused = True
            if rt.worktree_path:
                adapter = self._get_adapter(rt)
                if adapter:
                    adapter.deliver_message(
                        rt.worktree_path, "manager", "You have been paused. Stop submitting evals until you receive a resume message."
                    )

        return {"status": "ok", "paused": targets}

    def _handle_resume(self, request: dict) -> dict:
        agent_name = request.get("agent")
        if agent_name and agent_name in self.agents:
            targets = [agent_name]
        else:
            targets = list(self.agents.keys())

        for name in targets:
            rt = self.agents[name]
            rt.paused = False
            if rt.worktree_path:
                adapter = self._get_adapter(rt)
                if adapter:
                    adapter.deliver_message(
                        rt.worktree_path, "manager", "You have been resumed. You may continue submitting evals."
                    )

        return {"status": "ok", "resumed": targets}

    def _handle_kill(self, request: dict) -> dict:
        agent_name = request.get("agent", "")
        rt = self.agents.get(agent_name)
        if rt is None:
            return {"error": f"Unknown agent: {agent_name}"}

        # Terminate process
        if rt.process is not None:
            try:
                rt.process.terminate()
                rt.process.wait(timeout=5)
            except Exception:
                try:
                    rt.process.kill()
                except Exception:
                    pass

        # Teardown worktree
        try:
            self.workspace.teardown_worktree(agent_name)
        except Exception as exc:
            logger.warning("Failed to teardown worktree for %s: %s", agent_name, exc)

        del self.agents[agent_name]
        return {"status": "ok", "killed": agent_name}

    def _handle_spawn(self, request: dict) -> dict:
        new_name = request.get("name", "")
        clone_from = request.get("clone_from")
        role = request.get("role")
        runtime = request.get("runtime", "claude-code")

        if not new_name:
            return {"error": "Missing agent name"}

        if new_name in self.agents:
            return {"error": f"Agent {new_name} already exists"}

        if clone_from and clone_from in self.agents:
            # Clone from existing agent
            source = self.agents[clone_from]
            agent_cfg = source.agent_config
            role_cfg = source.role_config
        elif role and role in self.config.roles:
            from evolution.manager.config import AgentConfig
            agent_cfg = AgentConfig(role=role, runtime=runtime)
            role_cfg = self.config.roles[role]
        else:
            return {"error": "Must specify clone_from (existing agent) or role"}

        # Create worktree
        wt_path = self.workspace.create_worktree(new_name)

        # Set up workspace
        seed_path = Path(self.config.task.seed)
        if not seed_path.is_absolute():
            seed_path = self.repo_root / seed_path
        if seed_path.exists():
            self.workspace.copy_seed(wt_path, seed_path)

        self.workspace.link_shared(wt_path, self.shared_dir)
        self.workspace.create_inbox(wt_path)

        # Provision adapter
        adapter_cls = ADAPTERS.get(agent_cfg.runtime)
        if adapter_cls:
            adapter = adapter_cls()
            adapter.provision(wt_path, agent_cfg)
            adapter.write_instructions(
                wt_path, role_cfg.prompt, self.config.task.description
            )

        # Create runtime
        rt = AgentRuntime(new_name, agent_cfg, role_cfg)
        rt.worktree_path = wt_path
        self.agents[new_name] = rt

        return {"status": "ok", "spawned": new_name}

    def _handle_claims(self, request: dict) -> dict:
        """Return active work claims across all agents."""
        notes = self.notes_hub.list()
        active: dict[str, dict] = {}
        for note in notes:
            if "WORKING ON" in note.text or "working-on" in note.tags:
                active[note.agent] = {"agent": note.agent, "text": note.text, "timestamp": note.timestamp}
            elif ("DONE" in note.text or "done" in note.tags) and note.agent in active:
                del active[note.agent]
        return {"status": "ok", "claims": list(active.values())}

    def _handle_diff(self, request: dict) -> dict:
        """Return diff for a specific agent's worktree."""
        agent_name = request.get("agent", "")
        rt = self.agents.get(agent_name)
        if rt is None:
            return {"error": f"Unknown agent: {agent_name}"}
        if rt.worktree_path is None:
            return {"error": f"Agent {agent_name} has no worktree"}

        # Try git diff first (works for git worktree strategy)
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(rt.worktree_path),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and (rt.worktree_path / ".git").exists():
            return {"status": "ok", "diff": result.stdout, "agent": agent_name}

        # Fallback: diff against original repo (for reflink worktrees without .git)
        result = subprocess.run(
            ["diff", "-ru", "--exclude=.evolution", "--exclude=.git",
             str(self.repo_root), str(rt.worktree_path)],
            capture_output=True,
            text=True,
        )
        # diff returns 1 when files differ (not an error), 2 on trouble
        return {"status": "ok", "diff": result.stdout, "agent": agent_name}

    def _handle_cherry_pick(self, request: dict) -> dict:
        """Copy a file from one agent's worktree to another."""
        import shutil

        source_name = request.get("source_agent", "")
        target_name = request.get("target_agent", "")
        file_path = request.get("file", "")

        source = self.agents.get(source_name)
        target = self.agents.get(target_name)

        if not source or not source.worktree_path:
            return {"error": f"Unknown source agent: {source_name}"}
        if not target or not target.worktree_path:
            return {"error": f"Unknown target agent: {target_name}"}
        if not file_path:
            return {"error": "Missing file path"}

        # Path traversal safety
        src = (source.worktree_path / file_path).resolve()
        if not str(src).startswith(str(source.worktree_path.resolve())):
            return {"error": "Path traversal rejected — file must be within worktree"}
        if not src.exists():
            return {"error": f"File not found: {file_path}"}

        dst = target.worktree_path / file_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        return {"status": "ok", "file": file_path, "from": source_name, "to": target_name}

    def _handle_stop(self, request: dict) -> dict:
        self._running = False
        return {"status": "ok", "stopped": True}

    def _handle_merge(self, request: dict) -> dict:
        """Create a branch with the best agent's changes and a changelog commit."""
        agent_name = request.get("agent") or self._best_agent
        branch_name = request.get("branch", "evolution/merge")
        dry_run = request.get("dry_run", False)

        if agent_name is None:
            return {"error": "No best agent — no evals submitted yet"}

        rt = self.agents.get(agent_name)
        if rt is None:
            return {"error": f"Unknown agent: {agent_name}"}
        if rt.worktree_path is None:
            return {"error": f"Agent {agent_name} has no worktree"}

        # Build changelog from attempts and notes
        changelog = self._build_changelog(agent_name)

        if dry_run:
            return {
                "status": "ok",
                "dry_run": True,
                "agent": agent_name,
                "score": self._best_score,
                "branch": branch_name,
                "changelog": changelog,
            }

        # Create a new branch from HEAD in the main repo
        result = subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(self.repo_root),
            capture_output=True,
        )  # delete if exists (ignore errors)

        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {"error": f"Failed to create branch: {result.stderr.strip()}"}

        # Copy changed files from agent worktree to main repo
        changed_files = self._get_changed_files(rt.worktree_path)
        import shutil
        for rel_path in changed_files:
            src = rt.worktree_path / rel_path
            dst = self.repo_root / rel_path
            if src.exists() and src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            elif dst.exists() and dst.is_file():
                dst.unlink()  # file was deleted by agent

        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(self.repo_root),
            capture_output=True,
        )

        # Commit with changelog
        commit_msg = (
            f"evolution: merge {agent_name} (score {self._best_score})\n\n"
            f"{changelog}"
        )
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--no-gpg-sign"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )

        # Switch back to previous branch
        subprocess.run(
            ["git", "checkout", "-"],
            cwd=str(self.repo_root),
            capture_output=True,
        )

        return {
            "status": "ok",
            "agent": agent_name,
            "score": self._best_score,
            "branch": branch_name,
            "files_changed": len(changed_files),
            "changelog": changelog,
        }

    def _get_changed_files(self, worktree_path: Path) -> list[str]:
        """Get list of files that differ between worktree and repo root."""
        changed: list[str] = []

        # Try git diff if worktree has .git
        if (worktree_path / ".git").exists():
            result = subprocess.run(
                ["git", "diff", "HEAD", "--name-only"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()

        # Fallback: walk worktree and compare files against repo root
        import filecmp
        skip = {".evolution", ".git", ".venv", "node_modules", "__pycache__", ".DS_Store", ".claude"}
        for root, dirs, files in os.walk(worktree_path):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                wt_file = Path(root) / f
                rel = str(wt_file.relative_to(worktree_path))
                repo_file = self.repo_root / rel
                if not repo_file.exists():
                    changed.append(rel)  # new file
                elif not filecmp.cmp(str(wt_file), str(repo_file), shallow=False):
                    changed.append(rel)  # modified file

        return changed

    def _build_changelog(self, agent_name: str) -> str:
        """Build a changelog from the session's attempts and notes."""
        lines = []
        lines.append(f"## Evolution Session: {self.config.session.name}")
        lines.append(f"**Best agent:** {agent_name}")
        lines.append(f"**Best score:** {self._best_score}")
        lines.append("")

        # Top attempts
        board = self.attempts_hub.leaderboard(self._direction)
        if board:
            lines.append("### Top Attempts")
            for a in board[:10]:
                marker = " *" if a.agent == agent_name else ""
                lines.append(f"- #{a.id} {a.agent}: {a.score} — {a.description[:80]}{marker}")
            lines.append("")

        # Key findings from notes
        notes = self.notes_hub.list()
        findings = [n for n in notes if any(
            tag in n.tags for tag in ("technique", "finding", "dead-end")
        ) or any(prefix in n.text for prefix in ("FINDING:", "DEAD END:", "DONE:"))]
        if findings:
            lines.append("### Key Findings")
            for n in findings[:20]:
                lines.append(f"- [{n.agent}] {n.text[:120]}")
            lines.append("")

        # Hypotheses
        if hasattr(self, 'hypotheses_hub'):
            hypotheses = self.hypotheses_hub.list()
            if hypotheses:
                lines.append("### Hypotheses")
                for h in hypotheses:
                    status_icon = {"validated": "✓", "invalidated": "✗", "open": "?"}.get(h.status, "?")
                    lines.append(f"- [{status_icon}] {h.hypothesis}")
                lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Improvement & milestones
    # ------------------------------------------------------------------

    def _check_improvement(self, score: float, agent_name: str, direction: str) -> None:
        """Update best score and reset stagnation timer if improved."""
        is_better = False
        if self._best_score is None:
            is_better = True
        elif direction == "lower_is_better":
            is_better = score < self._best_score
        else:
            is_better = score > self._best_score

        if is_better:
            self._best_score = score
            self._best_agent = agent_name
            self._stagnation_start = time.monotonic()
            self._check_milestones(score, agent_name)

    def _check_milestones(self, score: float, agent_name: str) -> None:
        """Check if any milestones have been reached and broadcast."""
        milestones = self.config.task.milestones
        direction = self._direction

        thresholds: list[tuple[str, float | None]] = [
            ("baseline", milestones.baseline),
            ("target", milestones.target),
            ("stretch", milestones.stretch),
        ]

        for name, threshold in thresholds:
            if threshold is None:
                continue

            reached = False
            if direction == "lower_is_better":
                reached = score <= threshold
            else:
                reached = score >= threshold

            if reached:
                message = (
                    f"[MILESTONE] '{name}' reached! Score {score} by agent {agent_name} "
                    f"(threshold: {threshold})"
                )
                self._broadcast_message("manager", message)

    # ------------------------------------------------------------------
    # Stop conditions
    # ------------------------------------------------------------------

    def check_stop_conditions(self) -> str | None:
        """Check whether any stop condition has been met.

        Returns
        -------
        str | None
            A reason string if we should stop, or None to continue.
        """
        stop = self.config.task.stop

        # Max time
        max_time_secs = parse_duration(stop.max_time)
        elapsed = time.monotonic() - self._session_start
        if elapsed >= max_time_secs:
            return f"Max time reached ({stop.max_time})"

        # Max attempts
        if stop.max_attempts is not None:
            total = len(self.attempts_hub.list())
            if total >= stop.max_attempts:
                return f"Max attempts reached ({stop.max_attempts})"

        # Stagnation
        stagnation_secs = parse_duration(stop.stagnation)
        stagnation_elapsed = time.monotonic() - self._stagnation_start
        if stagnation_elapsed >= stagnation_secs:
            if stop.stagnation_action == "shake_up" and self._shake_up_count < stop.shake_up_budget:
                # Deliver shake-up message and reset timer
                self._broadcast_message(
                    "manager",
                    "SHAKE UP: No improvement detected. Try a radically different approach!",
                )
                self._stagnation_start = time.monotonic()
                self._shake_up_count += 1
                return None
            else:
                return f"Stagnation detected (no improvement for {stop.stagnation})"

        # Milestone stop
        if stop.milestone_stop and self._best_score is not None:
            milestones = self.config.task.milestones
            threshold = getattr(milestones, stop.milestone_stop, None)
            if threshold is not None:
                if self._direction == "lower_is_better":
                    if self._best_score <= threshold:
                        return f"Milestone '{stop.milestone_stop}' reached"
                else:
                    if self._best_score >= threshold:
                        return f"Milestone '{stop.milestone_stop}' reached"

        return None

    # ------------------------------------------------------------------
    # Convergence
    # ------------------------------------------------------------------

    def do_converge(self) -> None:
        """Reset all agent worktrees to the best-scoring agent's code."""
        if self._best_agent is None:
            logger.info("Convergence skipped — no evals yet")
            return

        best_rt = self.agents.get(self._best_agent)
        if best_rt is None or best_rt.worktree_path is None:
            logger.warning("Convergence skipped — best agent %s not found", self._best_agent)
            return

        best_branch = f"evolution/{self._best_agent}"

        for name, rt in self.agents.items():
            if name == self._best_agent or rt.worktree_path is None:
                continue

            try:
                wt = str(rt.worktree_path)
                # Snapshot current state
                subprocess.run(["git", "add", "-A"], cwd=wt, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", "pre-convergence snapshot"],
                    cwd=wt, capture_output=True,
                )
                # Checkout best agent's files
                subprocess.run(
                    ["git", "checkout", best_branch, "--", "."],
                    cwd=wt, capture_output=True, check=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", f"converge to {self._best_agent} (score {self._best_score})"],
                    cwd=wt, capture_output=True,
                )
                logger.info("Converged %s to %s", name, self._best_agent)
            except Exception as exc:
                logger.error("Convergence failed for %s: %s", name, exc)

        # Broadcast
        self._broadcast_message(
            "manager",
            f"[CONVERGE] Rebased all worktrees to {self._best_agent}'s code (score {self._best_score}). "
            f"Your previous changes are in git history (git diff HEAD~1). Build from this baseline.",
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """Write session state to .evolution/state.json."""
        state: dict[str, Any] = {
            "best_score": self._best_score,
            "best_agent": self._best_agent,
            "shake_up_count": self._shake_up_count,
            "agents": {},
        }
        for name, rt in self.agents.items():
            state["agents"][name] = {
                "role": rt.agent_config.role,
                "runtime": rt.agent_config.runtime,
                "worktree_path": str(rt.worktree_path) if rt.worktree_path else None,
                "restart_count": rt.restart_count,
                "paused": rt.paused,
                "alive": rt.is_alive(),
            }

        state_path = self.evolution_dir / "state.json"
        state_path.write_text(json.dumps(state, indent=2) + "\n")

    # ------------------------------------------------------------------
    # Session archival
    # ------------------------------------------------------------------

    def archive_session(self) -> None:
        """Archive current session's shared state and state.json for session chaining."""
        import shutil
        session_name = self.config.session.name
        sessions_dir = self.evolution_dir / "sessions" / session_name

        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)

            # Copy shared directory
            shared_src = self.evolution_dir / "shared"
            shared_dst = sessions_dir / "shared"
            if shared_src.exists():
                if shared_dst.exists():
                    shutil.rmtree(shared_dst)
                shutil.copytree(shared_src, shared_dst)

            # Save state with best_agent_branch
            self.save_state()
            state_src = self.evolution_dir / "state.json"
            if state_src.exists():
                state_data = json.loads(state_src.read_text())
                if self._best_agent:
                    state_data["best_agent_branch"] = f"evolution/{self._best_agent}"
                (sessions_dir / "state.json").write_text(json.dumps(state_data, indent=2) + "\n")

            logger.info("Archived session '%s' to %s", session_name, sessions_dir)
        except Exception as exc:
            logger.warning("Session archival failed (best-effort): %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_adapter(self, runtime: AgentRuntime) -> AgentAdapter | None:
        """Get an adapter instance for the given runtime."""
        adapter_cls = ADAPTERS.get(runtime.agent_config.runtime)
        if adapter_cls:
            return adapter_cls()
        return None

    def _broadcast_message(self, sender: str, message: str) -> None:
        """Deliver a message to all agents."""
        for name, rt in self.agents.items():
            if rt.worktree_path:
                adapter = self._get_adapter(rt)
                if adapter:
                    adapter.deliver_message(rt.worktree_path, sender, message)
