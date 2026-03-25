"""Pydantic models for Evolution platform configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class NamedHeartbeatConfig(BaseModel):
    """A single named heartbeat action."""

    name: str
    every: int  # fire every N attempts


class HeartbeatConfig(BaseModel):
    """Configuration for agent heartbeat monitoring.

    Supports two formats:

    Legacy (single heartbeat)::

        heartbeat:
          on_attempts: 3
          on_time: 10m

    Named list (multiple heartbeats at different frequencies)::

        heartbeat:
          - name: reflect
            every: 1
          - name: consolidate
            every: 10
    """

    on_attempts: int = 3
    on_time: str = "10m"
    strategy: str = "first"


class RestartConfig(BaseModel):
    """Configuration for agent restart behaviour.

    Disabled by default — agents are expected to run persistently with
    context compaction.  Enable only for crash recovery if needed.
    """

    enabled: bool = False
    max_restarts: int = 3
    preserve_worktree: bool = True


class RoleConfig(BaseModel):
    """A named role that agents can assume.

    ``heartbeat`` accepts either the legacy dict format or a list of named
    heartbeat actions::

        # Legacy
        heartbeat:
          on_attempts: 3
          on_time: 10m

        # Named list
        heartbeat:
          - name: reflect
            every: 1
          - name: consolidate
            every: 10
    """

    prompt: str
    heartbeat: HeartbeatConfig | list[NamedHeartbeatConfig] = Field(
        default_factory=HeartbeatConfig
    )


class AgentConfig(BaseModel):
    """Configuration for a single agent instance."""

    role: str
    runtime: str
    skills: list[str] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    restart: RestartConfig = Field(default_factory=RestartConfig)


class SessionConfig(BaseModel):
    """Top-level session metadata."""

    name: str
    log_level: str = "info"
    seed_from: str | None = None


class MilestoneConfig(BaseModel):
    """Milestone thresholds for a task."""

    baseline: float | None = None
    target: float | None = None
    stretch: float | None = None


class StopConfig(BaseModel):
    """Rules that govern when a task should stop."""

    max_time: str = "6h"
    max_attempts: int | None = None
    stagnation: str = "1h"
    stagnation_action: str = "stop"
    shake_up_budget: int = 2
    manual: bool = True
    milestone_stop: str | None = None


class EvalQueueConfig(BaseModel):
    """Configuration for the eval submission queue."""

    concurrency: int = 1
    fairness: str = "round_robin"
    max_queued: int = 8
    rate_limit_seconds: int = 0
    priority_boost: str = "none"


class PhaseConfig(BaseModel):
    """Configuration for a session phase (e.g., research, evolve)."""

    name: str
    duration: str | None = None
    eval_blocked: bool = False
    prompt: str | None = None


class TaskConfig(BaseModel):
    """Configuration describing the task to be evolved."""

    name: str
    description: str
    path: str
    seed: str
    metric: dict[str, Any] | None = None
    grader: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    ranking: dict[str, Any] | None = None
    milestones: MilestoneConfig = Field(default_factory=MilestoneConfig)
    stop: StopConfig = Field(default_factory=StopConfig)
    eval_queue: EvalQueueConfig | None = None
    phases: list[PhaseConfig] | None = None
    workspace_strategy: Literal["auto", "reflink", "git_worktree"] = "auto"


class SuperagentConfig(BaseModel):
    """Configuration for the optional super-agent."""

    enabled: bool = False
    runtime: str = "claude-code"
    remote_control: bool = True
    skills: list[str] = Field(default_factory=list)
    prompt: str = ""


class EvolutionConfig(BaseModel):
    """Root configuration object for an Evolution run."""

    session: SessionConfig
    task: TaskConfig
    roles: dict[str, RoleConfig]
    agents: dict[str, AgentConfig]
    superagent: SuperagentConfig = Field(default_factory=SuperagentConfig)


def load_config(path: str) -> EvolutionConfig:
    """Load and validate an Evolution configuration from a YAML file.

    Parameters
    ----------
    path:
        File-system path to the YAML configuration file.

    Returns
    -------
    EvolutionConfig
        A fully validated configuration object.
    """
    raw = Path(path).read_text()
    data = yaml.safe_load(raw)
    return EvolutionConfig.model_validate(data)
