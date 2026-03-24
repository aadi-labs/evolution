"""Core Manager that orchestrates Evolution agents, evals, heartbeats, and lifecycle."""

from __future__ import annotations

import json
import logging
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
        self.workspace = WorkspaceManager(self.repo_root)

        # Shared directory
        self.shared_dir = self.workspace.create_shared_dir()

        # Hubs
        self.attempts_hub = AttemptsHub(self.shared_dir / "attempts")
        self.notes_hub = NotesHub(self.shared_dir / "notes")
        self.skills_hub = SkillsHub(self.shared_dir / "skills")

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

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Provision all agents: create worktrees, copy seed, configure adapters."""
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
            elif req_type == "stop":
                return self._handle_stop(request)
            else:
                return {"error": f"Unknown request type: {req_type}"}
        except Exception as exc:
            logger.exception("Error handling request type=%s", req_type)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _handle_eval(self, request: dict) -> dict:
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

        # No git operations — just record the eval
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
        runtime.heartbeat.record_attempt()

        # Check improvement
        if score is not None:
            self._check_improvement(score, agent_name, self._direction)

        return {
            "status": "ok",
            "attempt_id": attempt.id,
            "score": score,
            "feedback": feedback,
            "improvement": attempt.improvement,
        }

    def _handle_note(self, request: dict) -> dict:
        agent = request.get("agent", "")
        text = request.get("text", "")
        tags = request.get("tags", [])

        note = self.notes_hub.add(agent=agent, text=text, tags=tags)
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
        notes = self.notes_hub.list(agent=agent)
        entries = []
        for n in notes:
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

    def _handle_stop(self, request: dict) -> dict:
        self._running = False
        return {"status": "ok", "stopped": True}

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
                    f"Milestone '{name}' reached! Score {score} by agent {agent_name} "
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
