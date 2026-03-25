"""Tests for evolution.manager.config models."""

import textwrap
import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from evolution.manager.config import (
    AgentConfig,
    EvolutionConfig,
    HeartbeatConfig,
    MilestoneConfig,
    RoleConfig,
    StopConfig,
    TaskConfig,
    SuperagentConfig,
    load_config,
)


# ---------- HeartbeatConfig defaults ----------


def test_heartbeat_defaults():
    hb = HeartbeatConfig()
    assert hb.on_attempts == 3
    assert hb.on_time == "10m"
    assert hb.strategy == "first"


def test_heartbeat_custom():
    hb = HeartbeatConfig(on_attempts=5, on_time="30m", strategy="all")
    assert hb.on_attempts == 5
    assert hb.on_time == "30m"
    assert hb.strategy == "all"


# ---------- RoleConfig ----------


def test_role_config_with_defaults():
    role = RoleConfig(prompt="You are a researcher.")
    assert role.prompt == "You are a researcher."
    assert role.heartbeat.on_attempts == 3  # uses HeartbeatConfig defaults


def test_role_config_custom_heartbeat():
    role = RoleConfig(
        prompt="Coder",
        heartbeat=HeartbeatConfig(on_attempts=1, on_time="5m", strategy="all"),
    )
    assert role.heartbeat.on_attempts == 1


# ---------- AgentConfig ----------


def test_agent_config_requires_role_and_runtime():
    """role and runtime are mandatory fields."""
    with pytest.raises(ValidationError):
        AgentConfig()  # type: ignore[call-arg]


def test_agent_config_minimal():
    agent = AgentConfig(role="researcher", runtime="claude-code")
    assert agent.role == "researcher"
    assert agent.runtime == "claude-code"
    assert agent.skills == []
    assert agent.plugins == []
    assert agent.mcp_servers == []
    assert agent.env == {}
    assert agent.restart.enabled is False


def test_agent_config_full():
    agent = AgentConfig(
        role="coder",
        runtime="codex",
        skills=["bash", "python"],
        plugins=["linter"],
        mcp_servers=["server-a"],
        env={"FOO": "bar"},
    )
    assert agent.skills == ["bash", "python"]
    assert agent.env["FOO"] == "bar"


def test_agent_config_runtime_options_default():
    agent = AgentConfig(role="r", runtime="rt")
    assert agent.runtime_options == {}


def test_agent_config_runtime_options_custom():
    agent = AgentConfig(
        role="r",
        runtime="rt",
        runtime_options={"permission_mode": "enable-auto-mode", "fast_mode": True},
    )
    assert agent.runtime_options["permission_mode"] == "enable-auto-mode"
    assert agent.runtime_options["fast_mode"] is True


# ---------- TaskConfig – single metric ----------


def test_single_metric_task():
    task = TaskConfig(
        name="improve-accuracy",
        description="Boost model accuracy",
        path="./workspace",
        seed="v0",
        metric={"name": "accuracy", "goal": "max"},
    )
    assert task.metric["name"] == "accuracy"
    assert task.metrics is None
    assert task.milestones.baseline is None
    assert task.stop.max_time == "6h"


# ---------- TaskConfig – multi metric ----------


def test_multi_metric_task():
    task = TaskConfig(
        name="improve-all",
        description="Boost multiple metrics",
        path="./workspace",
        seed="v0",
        metrics={
            "accuracy": {"goal": "max"},
            "latency": {"goal": "min"},
        },
        ranking={"method": "weighted", "weights": {"accuracy": 0.7, "latency": 0.3}},
        milestones=MilestoneConfig(baseline=0.5, target=0.8, stretch=0.95),
        stop=StopConfig(max_time="12h", stagnation="2h"),
    )
    assert task.metric is None
    assert "accuracy" in task.metrics
    assert task.milestones.target == 0.8
    assert task.stop.max_time == "12h"


# ---------- load_config from YAML ----------


_SAMPLE_YAML = textwrap.dedent("""\
    session:
      name: test-session
      log_level: debug

    task:
      name: demo
      description: A demo task
      path: ./workspace
      seed: v0
      metric:
        name: score
        goal: max
      milestones:
        baseline: 0.1
        target: 0.9
      stop:
        max_time: 2h
        stagnation: 30m

    roles:
      researcher:
        prompt: You research things.
      coder:
        prompt: You write code.
        heartbeat:
          on_attempts: 5
          on_time: 20m
          strategy: all

    agents:
      agent-a:
        role: researcher
        runtime: claude-code
      agent-b:
        role: coder
        runtime: codex
        skills:
          - python
        env:
          DEBUG: "1"

    superagent:
      enabled: true
      runtime: claude-code
      prompt: You supervise.
""")


def test_load_config_from_yaml():
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        tmp.write(_SAMPLE_YAML)
        tmp.flush()
        cfg = load_config(tmp.name)

    # session
    assert cfg.session.name == "test-session"
    assert cfg.session.log_level == "debug"

    # task
    assert cfg.task.name == "demo"
    assert cfg.task.metric["name"] == "score"
    assert cfg.task.milestones.baseline == 0.1
    assert cfg.task.stop.max_time == "2h"

    # roles
    assert "researcher" in cfg.roles
    assert cfg.roles["coder"].heartbeat.on_attempts == 5

    # agents
    assert cfg.agents["agent-a"].role == "researcher"
    assert cfg.agents["agent-b"].env["DEBUG"] == "1"
    assert cfg.agents["agent-b"].skills == ["python"]

    # superagent
    assert cfg.superagent.enabled is True
    assert cfg.superagent.prompt == "You supervise."


def test_load_config_superagent_defaults():
    """When superagent section is omitted, defaults kick in."""
    minimal_yaml = textwrap.dedent("""\
        session:
          name: minimal
        task:
          name: t
          description: d
          path: p
          seed: s
        roles:
          r:
            prompt: p
        agents:
          a:
            role: r
            runtime: rt
    """)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        tmp.write(minimal_yaml)
        tmp.flush()
        cfg = load_config(tmp.name)

    assert cfg.superagent.enabled is False
    assert cfg.superagent.runtime == "claude-code"


# ---------- EvalQueueConfig ----------


def test_eval_queue_config_defaults():
    from evolution.manager.config import EvalQueueConfig
    eq = EvalQueueConfig()
    assert eq.concurrency == 1
    assert eq.fairness == "round_robin"
    assert eq.max_queued == 8
    assert eq.rate_limit_seconds == 0
    assert eq.priority_boost == "none"

def test_task_config_with_eval_queue():
    from evolution.manager.config import EvalQueueConfig, TaskConfig
    tc = TaskConfig(
        name="test", description="test", path=".", seed=".",
        eval_queue=EvalQueueConfig(concurrency=2, max_queued=16),
    )
    assert tc.eval_queue.concurrency == 2
    assert tc.eval_queue.max_queued == 16

def test_task_config_without_eval_queue():
    from evolution.manager.config import TaskConfig
    tc = TaskConfig(name="test", description="test", path=".", seed=".")
    assert tc.eval_queue is None


# ---------- PhaseConfig ----------


def test_phase_config():
    from evolution.manager.config import PhaseConfig
    p = PhaseConfig(name="research", duration="30m", eval_blocked=True)
    assert p.name == "research"
    assert p.eval_blocked is True

def test_task_config_workspace_strategy_default():
    from evolution.manager.config import TaskConfig
    tc = TaskConfig(name="t", description="d", path=".", seed=".")
    assert tc.workspace_strategy == "auto"

def test_task_config_workspace_strategy_explicit():
    from evolution.manager.config import TaskConfig
    tc = TaskConfig(name="t", description="d", path=".", seed=".", workspace_strategy="reflink")
    assert tc.workspace_strategy == "reflink"

def test_task_config_with_phases():
    from evolution.manager.config import PhaseConfig, TaskConfig
    tc = TaskConfig(
        name="test", description="test", path=".", seed=".",
        phases=[PhaseConfig(name="research", duration="30m", eval_blocked=True)],
    )
    assert len(tc.phases) == 1
