"""Runtime state for a single Evolution agent."""

from __future__ import annotations

from evolution.manager.config import AgentConfig, HeartbeatConfig, RoleConfig
from evolution.manager.heartbeat import HeartbeatTracker, MultiHeartbeatTracker, parse_duration


class AgentRuntime:
    """Holds runtime state for an agent: process handle, worktree, heartbeat, etc."""

    def __init__(
        self, name: str, agent_config: AgentConfig, role_config: RoleConfig
    ) -> None:
        self.name = name
        self.agent_config = agent_config
        self.role_config = role_config
        self.process = None  # subprocess.Popen | None
        self.worktree_path = None  # Path | None
        self.restart_count = 0
        self.paused = False

        # Build heartbeat tracker — supports both legacy and named-list formats
        hb = role_config.heartbeat
        if isinstance(hb, list):
            # Named list: [{name: "reflect", every: 1}, ...]
            self.multi_heartbeat = MultiHeartbeatTracker(
                [{"name": h.name, "every": h.every} for h in hb]
            )
            self.heartbeat = None  # type: ignore[assignment]
        else:
            # Legacy single heartbeat
            self.multi_heartbeat = None
            self.heartbeat = HeartbeatTracker(
                on_attempts=hb.on_attempts,
                on_time_seconds=parse_duration(hb.on_time),
            )

    def is_alive(self) -> bool:
        """Return True if the process is running."""
        return self.process is not None and self.process.poll() is None

    def is_dead(self) -> bool:
        """Return True if the process has exited."""
        return self.process is not None and self.process.poll() is not None
