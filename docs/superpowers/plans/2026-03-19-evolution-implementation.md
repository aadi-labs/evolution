# Evolution Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-agent research & code evolution platform where heterogeneous AI agents collaborate to optimize code against user-defined grading functions.

**Architecture:** Agents run as autonomous subprocesses in isolated git worktrees. A central manager process serializes all writes (evals, notes, skills) via a Unix domain socket. Agents communicate through shared knowledge files and an inbox-based message delivery system. A Claude Code superagent provides remote control.

**Tech Stack:** Python 3.11+, uv, pydantic, pyyaml, openrouter SDK, stdlib (subprocess, argparse, logging, socket, json, pathlib)

**Spec:** `docs/superpowers/specs/2026-03-18-evolution-platform-design.md`

---

## Build Order & Dependencies

```
Task 1: Scaffold + Config ──────────────────────┐
Task 2: Hub (attempts/notes/skills) ────────────┤
Task 3: Workspace (git worktrees) ──────────────┤
Task 4: Grader — Script ────────────────────────┤
                                                 ▼
Task 5: Manager Socket Server ──────────────────┐
Task 6: Adapters — Base + Claude Code ──────────┤
                                                 ▼
Task 7: Manager Core (spawn/monitor/heartbeat) ─┐
Task 8: CLI — Core Commands ────────────────────┤
                                                 ▼
Task 9: Integration Test — Single Agent Loop ───┐
                                                 ▼
Task 10: Grader — LLM + Hybrid ─────────────────┤
Task 11: Adapters — Codex + OpenCode ───────────┤
Task 12: Multi-Metric Eval + Ranking ───────────┤
Task 13: Superagent ────────────────────────────┤
Task 14: Benchmark Tasks ───────────────────────┤
Task 15: Post-Session Analysis ─────────────────┘
```

Tasks 1-4 can be built in parallel (no interdependencies).
Tasks 10-15 can be built in any order after Task 9 passes.

---

### Task 1: Project Scaffold + Config Models

**Files:**
- Create: `pyproject.toml`
- Create: `evolution/__init__.py`
- Create: `evolution/manager/__init__.py`
- Create: `evolution/manager/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "evolution"
version = "0.1.0"
description = "Multi-agent research & code evolution platform"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "openrouter>=0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.5",
    "mypy>=1.10",
]

[project.scripts]
evolution = "evolution.cli.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create package structure**

```bash
mkdir -p evolution/{cli,manager,workspace,hub,grader,superagent,adapters}
mkdir -p tests
touch evolution/__init__.py
touch evolution/{cli,manager,workspace,hub,grader,superagent,adapters}/__init__.py
```

- [ ] **Step 3: Write failing test for config parsing**

```python
# tests/test_config.py
import pytest
import yaml
from evolution.manager.config import (
    SessionConfig,
    TaskConfig,
    RoleConfig,
    AgentConfig,
    HeartbeatConfig,
    SuperagentConfig,
    EvolutionConfig,
    load_config,
)


def test_heartbeat_config_defaults():
    hb = HeartbeatConfig()
    assert hb.on_attempts == 3
    assert hb.on_time == "10m"
    assert hb.strategy == "first"


def test_role_config():
    role = RoleConfig(prompt="You are a researcher.")
    assert role.prompt == "You are a researcher."
    assert role.heartbeat.on_attempts == 3  # default


def test_agent_config_requires_role_and_runtime():
    agent = AgentConfig(role="researcher", runtime="claude-code")
    assert agent.role == "researcher"
    assert agent.runtime == "claude-code"
    assert agent.skills == []
    assert agent.env == {}


def test_task_config_single_metric():
    task = TaskConfig(
        name="test-task",
        description="A test",
        metric={"name": "score", "direction": "lower_is_better"},
        grader={"type": "script", "script": "./grader.py"},
        seed="./seed/",
    )
    assert task.name == "test-task"
    assert task.metric["direction"] == "lower_is_better"


def test_task_config_multi_metric():
    task = TaskConfig(
        name="multi-task",
        description="Multi metric test",
        seed="./seed/",
        metrics={
            "m1": {
                "grader": "./g1.py",
                "direction": "higher_is_better",
                "weight": 0.6,
            },
            "m2": {
                "grader": "./g2.py",
                "direction": "lower_is_better",
                "weight": 0.4,
            },
        },
        ranking={"strategy": "weighted_sum", "normalize": True},
    )
    assert len(task.metrics) == 2
    assert task.ranking["strategy"] == "weighted_sum"


SAMPLE_YAML = """
session:
  name: test-run

task:
  name: test-task
  path: ./tasks/test
  description: A test task

roles:
  researcher:
    prompt: You are a researcher.
    heartbeat:
      on_attempts: 3
      on_time: 10m
      strategy: first

agents:
  claude-researcher:
    role: researcher
    runtime: claude-code
    skills:
      - superpowers

superagent:
  enabled: true
  runtime: claude-code
  remote_control: true
  prompt: You are the superagent.
"""


def test_load_config_from_yaml(tmp_path):
    config_path = tmp_path / "evolution.yaml"
    config_path.write_text(SAMPLE_YAML)
    config = load_config(str(config_path))
    assert config.session.name == "test-run"
    assert "researcher" in config.roles
    assert config.agents["claude-researcher"].runtime == "claude-code"
    assert config.superagent.enabled is True
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_config.py -v`
Expected: FAIL — module not found

- [ ] **Step 5: Implement config models**

```python
# evolution/manager/config.py
from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import BaseModel, Field


class HeartbeatConfig(BaseModel):
    on_attempts: int = 3
    on_time: str = "10m"
    strategy: str = "first"


class RestartConfig(BaseModel):
    enabled: bool = True
    max_restarts: int = 3
    backoff: str = "exponential"
    preserve_worktree: bool = True


class RoleConfig(BaseModel):
    prompt: str
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


class AgentConfig(BaseModel):
    role: str
    runtime: str  # "claude-code", "codex", "opencode"
    skills: list[str] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    restart: RestartConfig = Field(default_factory=RestartConfig)


class SessionConfig(BaseModel):
    name: str
    log_level: str = "info"


class MetricConfig(BaseModel):
    name: str = ""
    direction: str = "lower_is_better"


class MilestoneConfig(BaseModel):
    baseline: float | None = None
    target: float | None = None
    stretch: float | None = None


class StopConfig(BaseModel):
    max_time: str = "6h"
    max_attempts: int | None = None
    stagnation: str = "1h"
    stagnation_action: str = "stop"
    shake_up_budget: int = 2
    manual: bool = True
    milestone_stop: str | None = None


class TaskConfig(BaseModel):
    name: str
    description: str = ""
    path: str = ""
    seed: str = ""
    # Single metric
    metric: dict | None = None
    grader: dict | None = None
    # Multi metric
    metrics: dict[str, dict] | None = None
    ranking: dict | None = None
    # Common
    milestones: MilestoneConfig = Field(default_factory=MilestoneConfig)
    stop: StopConfig = Field(default_factory=StopConfig)


class SuperagentConfig(BaseModel):
    enabled: bool = False
    runtime: str = "claude-code"
    remote_control: bool = True
    skills: list[str] = Field(default_factory=list)
    prompt: str = ""


class EvolutionConfig(BaseModel):
    session: SessionConfig
    task: TaskConfig
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    superagent: SuperagentConfig = Field(default_factory=SuperagentConfig)


def load_config(path: str) -> EvolutionConfig:
    """Load and validate evolution.yaml."""
    raw = yaml.safe_load(Path(path).read_text())
    return EvolutionConfig(**raw)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_config.py -v`
Expected: All PASS

- [ ] **Step 7: Install project in dev mode and verify CLI entry point**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv sync --extra dev`

---

### Task 2: Hub — Shared Knowledge Layer

**Files:**
- Create: `evolution/hub/attempts.py`
- Create: `evolution/hub/notes.py`
- Create: `evolution/hub/skills.py`
- Test: `tests/test_hub.py`

- [ ] **Step 1: Write failing tests for hub**

```python
# tests/test_hub.py
import pytest
from pathlib import Path
from evolution.hub.attempts import AttemptsHub, Attempt
from evolution.hub.notes import NotesHub, Note
from evolution.hub.skills import SkillsHub, Skill


class TestAttemptsHub:
    def test_record_attempt(self, tmp_path):
        hub = AttemptsHub(tmp_path / "attempts")
        attempt = hub.record(
            agent="claude-researcher",
            score=0.38091,
            description="Switched to simulated annealing",
            commit="a1b2c3d",
            feedback="Good improvement",
        )
        assert attempt.id == 1
        assert attempt.agent == "claude-researcher"
        assert attempt.score == 0.38091

    def test_attempt_ids_are_monotonic(self, tmp_path):
        hub = AttemptsHub(tmp_path / "attempts")
        a1 = hub.record(agent="a", score=1.0, description="first", commit="aaa", feedback="")
        a2 = hub.record(agent="b", score=2.0, description="second", commit="bbb", feedback="")
        assert a2.id == a1.id + 1

    def test_list_attempts(self, tmp_path):
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record(agent="a", score=0.5, description="first", commit="aaa", feedback="")
        hub.record(agent="b", score=0.3, description="second", commit="bbb", feedback="")
        attempts = hub.list()
        assert len(attempts) == 2

    def test_leaderboard_sorted(self, tmp_path):
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record(agent="a", score=0.5, description="worse", commit="aaa", feedback="")
        hub.record(agent="b", score=0.3, description="better", commit="bbb", feedback="")
        board = hub.leaderboard(direction="lower_is_better")
        assert board[0].score == 0.3

    def test_get_attempt_by_id(self, tmp_path):
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record(agent="a", score=1.0, description="test", commit="aaa", feedback="ok")
        attempt = hub.get(1)
        assert attempt.agent == "a"

    def test_attempt_written_as_markdown(self, tmp_path):
        hub = AttemptsHub(tmp_path / "attempts")
        hub.record(agent="a", score=0.5, description="test", commit="abc", feedback="good")
        files = list((tmp_path / "attempts").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "agent: a" in content
        assert "score: 0.5" in content


class TestNotesHub:
    def test_add_note(self, tmp_path):
        hub = NotesHub(tmp_path / "notes")
        note = hub.add(agent="claude-researcher", text="Cooling is a dead end", tags=["dead-end"])
        assert note.agent == "claude-researcher"
        assert "dead-end" in note.tags

    def test_list_notes(self, tmp_path):
        hub = NotesHub(tmp_path / "notes")
        hub.add(agent="a", text="note 1")
        hub.add(agent="b", text="note 2")
        notes = hub.list()
        assert len(notes) == 2

    def test_list_notes_by_agent(self, tmp_path):
        hub = NotesHub(tmp_path / "notes")
        hub.add(agent="a", text="note 1")
        hub.add(agent="b", text="note 2")
        notes = hub.list(agent="a")
        assert len(notes) == 1
        assert notes[0].agent == "a"


class TestSkillsHub:
    def test_add_skill(self, tmp_path):
        hub = SkillsHub(tmp_path / "skills")
        skill = hub.add(
            author="codex-researcher",
            name="binary-search",
            content="Use binary search on overlap bounds.",
            tags=["optimization"],
        )
        assert skill.author == "codex-researcher"
        assert skill.name == "binary-search"

    def test_list_skills(self, tmp_path):
        hub = SkillsHub(tmp_path / "skills")
        hub.add(author="a", name="s1", content="skill 1")
        hub.add(author="b", name="s2", content="skill 2")
        skills = hub.list()
        assert len(skills) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_hub.py -v`
Expected: FAIL — modules not found

- [ ] **Step 3: Implement AttemptsHub**

```python
# evolution/hub/attempts.py
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Attempt:
    id: int
    agent: str
    score: float | None
    description: str
    commit: str
    feedback: str
    timestamp: str = ""
    previous_best: float | None = None
    improvement: bool = False
    metrics: dict[str, float] = field(default_factory=dict)


class AttemptsHub:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._next_id = self._compute_next_id()

    def _compute_next_id(self) -> int:
        files = list(self.path.glob("*.md"))
        if not files:
            return 1
        ids = []
        for f in files:
            try:
                ids.append(int(f.name.split("-")[0]))
            except ValueError:
                continue
        return max(ids, default=0) + 1

    def record(
        self,
        agent: str,
        score: float | None,
        description: str,
        commit: str,
        feedback: str,
        metrics: dict[str, float] | None = None,
    ) -> Attempt:
        attempt = Attempt(
            id=self._next_id,
            agent=agent,
            score=score,
            description=description,
            commit=commit,
            feedback=feedback,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metrics=metrics or {},
        )
        self._write(attempt)
        self._next_id += 1
        return attempt

    def _write(self, attempt: Attempt) -> None:
        score_str = f"{attempt.score}" if attempt.score is not None else "failed"
        filename = f"{attempt.id:03d}-{attempt.agent}-score-{score_str}.md"
        frontmatter = {
            "id": attempt.id,
            "agent": attempt.agent,
            "score": attempt.score,
            "timestamp": attempt.timestamp,
            "commit": attempt.commit,
            "improvement": attempt.improvement,
        }
        if attempt.metrics:
            frontmatter["metrics"] = attempt.metrics
        content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n\n"
        content += f"## Description\n{attempt.description}\n\n"
        content += f"## Grader Feedback\n{attempt.feedback}\n"
        (self.path / filename).write_text(content)

    def list(self) -> list[Attempt]:
        attempts = []
        for f in sorted(self.path.glob("*.md")):
            attempt = self._read(f)
            if attempt:
                attempts.append(attempt)
        return attempts

    def get(self, attempt_id: int) -> Attempt | None:
        for f in self.path.glob(f"{attempt_id:03d}-*.md"):
            return self._read(f)
        return None

    def leaderboard(self, direction: str = "lower_is_better") -> list[Attempt]:
        attempts = [a for a in self.list() if a.score is not None]
        reverse = direction == "higher_is_better"
        return sorted(attempts, key=lambda a: a.score, reverse=reverse)

    def best(self, direction: str = "lower_is_better") -> Attempt | None:
        board = self.leaderboard(direction)
        return board[0] if board else None

    def _read(self, path: Path) -> Attempt | None:
        text = path.read_text()
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        meta = yaml.safe_load(parts[1])
        return Attempt(
            id=meta.get("id", 0),
            agent=meta.get("agent", ""),
            score=meta.get("score"),
            description="",  # could parse body if needed
            commit=meta.get("commit", ""),
            feedback="",
            timestamp=meta.get("timestamp", ""),
            improvement=meta.get("improvement", False),
            metrics=meta.get("metrics", {}),
        )
```

- [ ] **Step 4: Implement NotesHub**

```python
# evolution/hub/notes.py
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Note:
    agent: str
    text: str
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""


class NotesHub:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._next_id = self._compute_next_id()

    def _compute_next_id(self) -> int:
        files = list(self.path.glob("*.md"))
        if not files:
            return 1
        ids = []
        for f in files:
            try:
                ids.append(int(f.name.split("-")[0]))
            except ValueError:
                continue
        return max(ids, default=0) + 1

    def add(self, agent: str, text: str, tags: list[str] | None = None) -> Note:
        note = Note(
            agent=agent,
            text=text,
            tags=tags or [],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._write(note)
        return note

    def _write(self, note: Note) -> None:
        filename = f"{self._next_id:03d}-{note.agent}.md"
        frontmatter = {
            "agent": note.agent,
            "timestamp": note.timestamp,
            "tags": note.tags,
        }
        content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n\n"
        content += note.text + "\n"
        (self.path / filename).write_text(content)
        self._next_id += 1

    def list(self, agent: str | None = None) -> list[Note]:
        notes = []
        for f in sorted(self.path.glob("*.md")):
            note = self._read(f)
            if note and (agent is None or note.agent == agent):
                notes.append(note)
        return notes

    def _read(self, path: Path) -> Note | None:
        text = path.read_text()
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        meta = yaml.safe_load(parts[1])
        body = parts[2].strip()
        return Note(
            agent=meta.get("agent", ""),
            text=body,
            tags=meta.get("tags", []),
            timestamp=meta.get("timestamp", ""),
        )
```

- [ ] **Step 5: Implement SkillsHub**

```python
# evolution/hub/skills.py
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Skill:
    author: str
    name: str
    content: str
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""


class SkillsHub:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def add(
        self, author: str, name: str, content: str, tags: list[str] | None = None
    ) -> Skill:
        skill = Skill(
            author=author,
            name=name,
            content=content,
            tags=tags or [],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._write(skill)
        return skill

    def _write(self, skill: Skill) -> None:
        filename = f"{skill.name}.md"
        frontmatter = {
            "author": skill.author,
            "timestamp": skill.timestamp,
            "tags": skill.tags,
        }
        content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n\n"
        content += skill.content + "\n"
        (self.path / filename).write_text(content)

    def list(self) -> list[Skill]:
        skills = []
        for f in sorted(self.path.glob("*.md")):
            skill = self._read(f)
            if skill:
                skills.append(skill)
        return skills

    def _read(self, path: Path) -> Skill | None:
        text = path.read_text()
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        meta = yaml.safe_load(parts[1])
        body = parts[2].strip()
        return Skill(
            author=meta.get("author", ""),
            name=path.stem,
            content=body,
            tags=meta.get("tags", []),
            timestamp=meta.get("timestamp", ""),
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_hub.py -v`
Expected: All PASS

---

### Task 3: Workspace — Git Worktree Management

**Files:**
- Create: `evolution/workspace/setup.py`
- Test: `tests/test_workspace.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_workspace.py
import subprocess
import pytest
from pathlib import Path
from evolution.workspace.setup import WorkspaceManager


@pytest.fixture
def git_repo(tmp_path):
    """Create a bare git repo with one commit for worktree tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


class TestWorkspaceManager:
    def test_create_worktree(self, git_repo):
        ws = WorkspaceManager(git_repo)
        wt_path = ws.create_worktree("agent-1")
        assert wt_path.exists()
        assert (wt_path / "README.md").exists()

    def test_create_shared_dir(self, git_repo):
        ws = WorkspaceManager(git_repo)
        shared = ws.create_shared_dir()
        assert (shared / "attempts").is_dir()
        assert (shared / "notes").is_dir()
        assert (shared / "skills").is_dir()

    def test_symlink_shared_into_worktree(self, git_repo):
        ws = WorkspaceManager(git_repo)
        shared = ws.create_shared_dir()
        wt_path = ws.create_worktree("agent-1")
        ws.link_shared(wt_path, shared)
        linked = wt_path / ".evolution" / "shared"
        assert linked.is_symlink()
        assert linked.resolve() == shared.resolve()

    def test_create_inbox(self, git_repo):
        ws = WorkspaceManager(git_repo)
        wt_path = ws.create_worktree("agent-1")
        inbox = ws.create_inbox(wt_path)
        assert inbox.is_dir()

    def test_copy_seed(self, git_repo):
        seed_dir = git_repo / "seed"
        seed_dir.mkdir()
        (seed_dir / "solver.py").write_text("# solver")
        ws = WorkspaceManager(git_repo)
        wt_path = ws.create_worktree("agent-1")
        ws.copy_seed(wt_path, seed_dir)
        assert (wt_path / "solver.py").exists()

    def test_teardown_worktree(self, git_repo):
        ws = WorkspaceManager(git_repo)
        wt_path = ws.create_worktree("agent-1")
        assert wt_path.exists()
        ws.teardown_worktree("agent-1")
        assert not wt_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_workspace.py -v`
Expected: FAIL

- [ ] **Step 3: Implement WorkspaceManager**

```python
# evolution/workspace/setup.py
from __future__ import annotations

import shutil
import subprocess
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class WorkspaceManager:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.evolution_dir = self.repo_root / ".evolution"
        self.worktrees_dir = self.evolution_dir / "worktrees"

    def create_worktree(self, agent_name: str) -> Path:
        """Create an isolated git worktree for an agent."""
        wt_path = self.worktrees_dir / agent_name
        branch = f"evolution/{agent_name}"
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(wt_path)],
            cwd=self.repo_root,
            capture_output=True,
            check=True,
        )
        log.info(f"Created worktree for {agent_name} at {wt_path}")
        return wt_path

    def teardown_worktree(self, agent_name: str) -> None:
        """Remove a worktree and its branch."""
        wt_path = self.worktrees_dir / agent_name
        branch = f"evolution/{agent_name}"
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            cwd=self.repo_root,
            capture_output=True,
        )
        subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=self.repo_root,
            capture_output=True,
        )
        log.info(f"Removed worktree for {agent_name}")

    def create_shared_dir(self) -> Path:
        """Create the shared knowledge directory."""
        shared = self.evolution_dir / "shared"
        for subdir in ["attempts", "notes", "skills"]:
            (shared / subdir).mkdir(parents=True, exist_ok=True)
        log.info(f"Created shared directory at {shared}")
        return shared

    def link_shared(self, worktree_path: Path, shared_path: Path) -> None:
        """Symlink the shared directory into a worktree."""
        evo_dir = worktree_path / ".evolution"
        evo_dir.mkdir(exist_ok=True)
        link = evo_dir / "shared"
        if not link.exists():
            link.symlink_to(shared_path.resolve())

    def create_inbox(self, worktree_path: Path) -> Path:
        """Create an inbox directory for an agent."""
        inbox = worktree_path / ".evolution" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        return inbox

    def copy_seed(self, worktree_path: Path, seed_path: Path) -> None:
        """Copy seed code into a worktree."""
        for item in seed_path.iterdir():
            dest = worktree_path / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        log.info(f"Copied seed from {seed_path} to {worktree_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_workspace.py -v`
Expected: All PASS

---

### Task 4: Grader — Script Grader

**Files:**
- Create: `evolution/grader/protocol.py`
- Create: `evolution/grader/script.py`
- Test: `tests/test_grader.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_grader.py
import pytest
from pathlib import Path
from evolution.grader.protocol import GradeResult
from evolution.grader.script import ScriptGrader


@pytest.fixture
def dummy_grader_script(tmp_path):
    """A grader script that prints a score to stdout."""
    script = tmp_path / "grader.py"
    script.write_text(
        '#!/usr/bin/env python3\nimport sys\nprint("0.38091")\nprint("Good improvement", file=sys.stderr)\n'
    )
    return str(script)


@pytest.fixture
def failing_grader_script(tmp_path):
    script = tmp_path / "grader.py"
    script.write_text("#!/usr/bin/env python3\nraise Exception('grader broke')\n")
    return str(script)


def test_grade_result_dataclass():
    result = GradeResult(score=0.5, feedback="ok")
    assert result.score == 0.5
    assert result.feedback == "ok"
    assert result.metrics == {}


def test_script_grader_parses_score(tmp_path, dummy_grader_script):
    grader = ScriptGrader(script_path=dummy_grader_script)
    result = grader.grade(str(tmp_path))
    assert result.score == pytest.approx(0.38091)


def test_script_grader_handles_failure(tmp_path, failing_grader_script):
    grader = ScriptGrader(script_path=failing_grader_script)
    result = grader.grade(str(tmp_path))
    assert result.score is None
    assert "error" in result.feedback.lower() or "exception" in result.feedback.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_grader.py -v`
Expected: FAIL

- [ ] **Step 3: Implement GradeResult and ScriptGrader**

```python
# evolution/grader/protocol.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GradeResult:
    score: float | None
    feedback: str
    metrics: dict[str, float] = field(default_factory=dict)
```

```python
# evolution/grader/script.py
from __future__ import annotations

import subprocess
import logging
from evolution.grader.protocol import GradeResult

log = logging.getLogger(__name__)


class ScriptGrader:
    def __init__(self, script_path: str):
        self.script_path = script_path

    def grade(self, attempt_path: str) -> GradeResult:
        """Run grader script against attempt directory. Script prints score to stdout."""
        try:
            result = subprocess.run(
                ["python3", self.script_path],
                cwd=attempt_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                return GradeResult(
                    score=None,
                    feedback=f"Grader error (exit {result.returncode}): {result.stderr.strip()}",
                )
            score = float(result.stdout.strip().split("\n")[0])
            feedback = result.stderr.strip() if result.stderr else ""
            return GradeResult(score=score, feedback=feedback)
        except (ValueError, IndexError) as e:
            return GradeResult(score=None, feedback=f"Error parsing grader output: {e}")
        except subprocess.TimeoutExpired:
            return GradeResult(score=None, feedback="Grader timed out after 300s")
        except Exception as e:
            return GradeResult(score=None, feedback=f"Error running grader: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_grader.py -v`
Expected: All PASS

---

### Task 5: Manager Socket Server

**Files:**
- Create: `evolution/manager/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server.py
import json
import socket
import threading
import pytest
from pathlib import Path
from evolution.manager.server import ManagerServer


def test_server_starts_and_accepts_connection(tmp_path):
    sock_path = tmp_path / "manager.sock"
    server = ManagerServer(str(sock_path))

    def handler(request: dict) -> dict:
        return {"status": "ok", "echo": request.get("message")}

    t = threading.Thread(target=server.serve_one, args=(handler,), daemon=True)
    t.start()
    # Wait for socket to exist
    import time
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)

    # Connect and send a request
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(sock_path))
    request = json.dumps({"type": "eval", "message": "hello"}).encode() + b"\n"
    client.sendall(request)
    response = b""
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        response += chunk
        if b"\n" in response:
            break
    client.close()
    data = json.loads(response.decode().strip())
    assert data["status"] == "ok"
    assert data["echo"] == "hello"
    server.shutdown()


def test_server_cleans_up_socket(tmp_path):
    sock_path = tmp_path / "manager.sock"
    server = ManagerServer(str(sock_path))
    server.shutdown()
    # Socket file should not remain after shutdown if never started
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_server.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ManagerServer**

```python
# evolution/manager/server.py
from __future__ import annotations

import json
import socket
import logging
import os
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

RequestHandler = Callable[[dict], dict]


class ManagerServer:
    """Unix domain socket server for manager communication."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self._socket: socket.socket | None = None
        self._running = False

    def serve_one(self, handler: RequestHandler) -> None:
        """Accept and handle one connection. Useful for testing."""
        self._bind()
        conn, _ = self._socket.accept()
        self._handle_connection(conn, handler)

    def serve_forever(self, handler: RequestHandler) -> None:
        """Accept connections in a loop until shutdown."""
        self._bind()
        self._running = True
        self._socket.settimeout(1.0)
        while self._running:
            try:
                conn, _ = self._socket.accept()
                self._handle_connection(conn, handler)
            except socket.timeout:
                continue
            except OSError:
                break

    def shutdown(self) -> None:
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    def _bind(self) -> None:
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(self.socket_path)
        self._socket.listen(5)
        log.info(f"Manager listening on {self.socket_path}")

    def _handle_connection(self, conn: socket.socket, handler: RequestHandler) -> None:
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
            if data:
                request = json.loads(data.decode().strip())
                response = handler(request)
                conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception as e:
            log.error(f"Error handling connection: {e}")
            try:
                conn.sendall(json.dumps({"error": str(e)}).encode() + b"\n")
            except OSError:
                pass
        finally:
            conn.close()


def send_request(socket_path: str, request: dict) -> dict:
    """Client helper: send a request to the manager and return the response."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(socket_path)
    try:
        client.sendall(json.dumps(request).encode() + b"\n")
        data = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        return json.loads(data.decode().strip())
    finally:
        client.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_server.py -v`
Expected: All PASS

---

### Task 6: Adapters — Base + Claude Code

**Files:**
- Create: `evolution/adapters/base.py`
- Create: `evolution/adapters/claude_code.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_adapters.py
import json
import pytest
from pathlib import Path
from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import ClaudeCodeAdapter
from evolution.manager.config import AgentConfig, RoleConfig, HeartbeatConfig


@pytest.fixture
def agent_config():
    return AgentConfig(
        role="researcher",
        runtime="claude-code",
        skills=["superpowers", "alphaxiv-paper-lookup"],
        plugins=["huggingface-skills"],
        mcp_servers=["huggingface"],
    )


@pytest.fixture
def role_config():
    return RoleConfig(prompt="You are a researcher.")


class TestClaudeCodeAdapter:
    def test_instruction_file_name(self):
        adapter = ClaudeCodeAdapter()
        assert adapter.instruction_file == "CLAUDE.md"

    def test_write_instructions(self, tmp_path, role_config):
        adapter = ClaudeCodeAdapter()
        task_desc = "Minimize C5"
        adapter.write_instructions(tmp_path, role_config.prompt, task_desc)
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "You are a researcher" in content
        assert "Minimize C5" in content
        assert "evolution eval" in content  # protocol instructions

    def test_provision_writes_settings(self, tmp_path, agent_config):
        adapter = ClaudeCodeAdapter()
        adapter.provision(tmp_path, agent_config)
        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "superpowers" in str(data)

    def test_deliver_message_creates_inbox_file(self, tmp_path):
        adapter = ClaudeCodeAdapter()
        inbox = tmp_path / ".evolution" / "inbox"
        inbox.mkdir(parents=True)
        adapter.deliver_message(tmp_path, "test-agent", "Check the leaderboard")
        files = list(inbox.glob("*.md"))
        assert len(files) == 1
        assert "Check the leaderboard" in files[0].read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_adapters.py -v`
Expected: FAIL

- [ ] **Step 3: Implement base adapter and Claude Code adapter**

```python
# evolution/adapters/base.py
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from evolution.manager.config import AgentConfig


class AgentAdapter:
    """Base interface for agent runtime adapters."""
    name: str = ""
    instruction_file: str = ""

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """Write runtime-specific config files into the worktree."""
        raise NotImplementedError

    def write_instructions(self, worktree_path: Path, prompt: str, task_description: str) -> None:
        """Write the instruction file (CLAUDE.md / AGENTS.md) into the worktree."""
        raise NotImplementedError

    def spawn(self, worktree_path: Path, agent_config: AgentConfig) -> subprocess.Popen:
        """Start the agent subprocess."""
        raise NotImplementedError

    def deliver_message(self, worktree_path: Path, agent_name: str, message: str) -> None:
        """Write a message to the agent's inbox."""
        inbox = worktree_path / ".evolution" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        filename = f"{timestamp}.md"
        (inbox / filename).write_text(message + "\n")
```

```python
# evolution/adapters/claude_code.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from evolution.adapters.base import AgentAdapter
from evolution.manager.config import AgentConfig

INSTRUCTION_TEMPLATE = """# Agent Instructions

## Your Role
{prompt}

## Task
{task_description}

## How to Work
- Make changes to the code in this directory
- Submit with: `evolution eval -m "description of what you changed"`
- Read others' work: `evolution attempts list`, `evolution notes list`
- Share insights: `evolution note add "your insight"`
- Publish reusable techniques: `evolution skill add skill-name.md`
- Check your inbox before each new approach: `.evolution/inbox/`
- Check your inbox after each eval submission

## Constraints
- You will receive heartbeat prompts — reflect and share when asked
- Prioritize messages from the user over your current work
"""


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"
    instruction_file = "CLAUDE.md"

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """Write .claude/settings.json with skills, plugins, MCP servers."""
        claude_dir = worktree_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        settings = {}
        if agent_config.skills:
            settings["skills"] = agent_config.skills
        if agent_config.plugins:
            settings["plugins"] = agent_config.plugins
        if agent_config.mcp_servers:
            settings["mcpServers"] = agent_config.mcp_servers
        (claude_dir / "settings.json").write_text(json.dumps(settings, indent=2))

    def write_instructions(self, worktree_path: Path, prompt: str, task_description: str) -> None:
        content = INSTRUCTION_TEMPLATE.format(prompt=prompt, task_description=task_description)
        (worktree_path / self.instruction_file).write_text(content)

    def spawn(self, worktree_path: Path, agent_config: AgentConfig) -> subprocess.Popen:
        import os
        env = {**os.environ, **agent_config.env} if agent_config.env else None
        return subprocess.Popen(
            ["claude", "--dangerously-skip-permissions"],
            cwd=str(worktree_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_adapters.py -v`
Expected: All PASS

---

### Task 7: Manager Core — Spawn, Monitor, Heartbeat

**Files:**
- Create: `evolution/manager/manager.py`
- Create: `evolution/manager/heartbeat.py`
- Create: `evolution/manager/runtime.py`
- Test: `tests/test_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_manager.py
import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from evolution.manager.config import (
    EvolutionConfig, SessionConfig, TaskConfig, RoleConfig,
    AgentConfig, HeartbeatConfig, SuperagentConfig, load_config,
)
from evolution.manager.heartbeat import HeartbeatTracker
from evolution.manager.runtime import AgentRuntime


class TestHeartbeatTracker:
    def test_time_trigger(self):
        hb = HeartbeatTracker(on_attempts=100, on_time_seconds=0.1)
        # Should not trigger immediately
        assert not hb.should_fire()
        time.sleep(0.15)
        assert hb.should_fire()

    def test_attempt_trigger(self):
        hb = HeartbeatTracker(on_attempts=2, on_time_seconds=9999)
        hb.record_attempt()
        assert not hb.should_fire()
        hb.record_attempt()
        assert hb.should_fire()

    def test_reset_after_fire(self):
        hb = HeartbeatTracker(on_attempts=1, on_time_seconds=9999)
        hb.record_attempt()
        assert hb.should_fire()
        hb.reset()
        assert not hb.should_fire()


class TestAgentRuntime:
    def test_create_runtime(self):
        runtime = AgentRuntime(
            name="claude-researcher",
            agent_config=AgentConfig(role="researcher", runtime="claude-code"),
            role_config=RoleConfig(prompt="test"),
        )
        assert runtime.name == "claude-researcher"
        assert runtime.is_alive() is False  # not spawned yet

    def test_restart_count(self):
        runtime = AgentRuntime(
            name="test",
            agent_config=AgentConfig(role="r", runtime="claude-code"),
            role_config=RoleConfig(prompt="test"),
        )
        assert runtime.restart_count == 0
        runtime.restart_count += 1
        assert runtime.restart_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_manager.py -v`
Expected: FAIL

- [ ] **Step 3: Implement HeartbeatTracker**

```python
# evolution/manager/heartbeat.py
from __future__ import annotations

import re
import time


def parse_duration(s: str) -> float:
    """Parse duration string like '10m', '1h', '30s' to seconds."""
    match = re.match(r"^(\d+)(s|m|h)$", s.strip())
    if not match:
        raise ValueError(f"Invalid duration: {s}")
    value, unit = int(match.group(1)), match.group(2)
    multiplier = {"s": 1, "m": 60, "h": 3600}
    return value * multiplier[unit]


class HeartbeatTracker:
    def __init__(self, on_attempts: int, on_time_seconds: float):
        self.on_attempts = on_attempts
        self.on_time_seconds = on_time_seconds
        self._attempt_count = 0
        self._last_reset = time.monotonic()

    def record_attempt(self) -> None:
        self._attempt_count += 1

    def should_fire(self) -> bool:
        if self._attempt_count >= self.on_attempts:
            return True
        if time.monotonic() - self._last_reset >= self.on_time_seconds:
            return True
        return False

    def reset(self) -> None:
        self._attempt_count = 0
        self._last_reset = time.monotonic()
```

- [ ] **Step 4: Implement AgentRuntime**

```python
# evolution/manager/runtime.py
from __future__ import annotations

import subprocess
import logging
from pathlib import Path
from evolution.manager.config import AgentConfig, RoleConfig
from evolution.manager.heartbeat import HeartbeatTracker, parse_duration

log = logging.getLogger(__name__)


class AgentRuntime:
    """Tracks a single agent's subprocess and state."""

    def __init__(self, name: str, agent_config: AgentConfig, role_config: RoleConfig):
        self.name = name
        self.agent_config = agent_config
        self.role_config = role_config
        self.process: subprocess.Popen | None = None
        self.worktree_path: Path | None = None
        self.restart_count: int = 0
        self.paused: bool = False
        self.heartbeat = HeartbeatTracker(
            on_attempts=role_config.heartbeat.on_attempts,
            on_time_seconds=parse_duration(role_config.heartbeat.on_time),
        )

    def is_alive(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    def is_dead(self) -> bool:
        return self.process is not None and self.process.poll() is not None
```

- [ ] **Step 5: Implement Manager (core orchestrator)**

```python
# evolution/manager/manager.py
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path

from evolution.manager.config import EvolutionConfig, load_config
from evolution.manager.heartbeat import parse_duration
from evolution.manager.runtime import AgentRuntime
from evolution.manager.server import ManagerServer, send_request
from evolution.workspace.setup import WorkspaceManager
from evolution.hub.attempts import AttemptsHub
from evolution.hub.notes import NotesHub
from evolution.hub.skills import SkillsHub
from evolution.grader.script import ScriptGrader
from evolution.grader.protocol import GradeResult
from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import ClaudeCodeAdapter

log = logging.getLogger(__name__)

ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
}


class Manager:
    def __init__(self, config: EvolutionConfig, repo_root: Path):
        self.config = config
        self.repo_root = repo_root
        self.workspace = WorkspaceManager(repo_root)
        self.evolution_dir = repo_root / ".evolution"

        # Shared knowledge
        shared = self.workspace.create_shared_dir()
        self.attempts = AttemptsHub(shared / "attempts")
        self.notes = NotesHub(shared / "notes")
        self.skills = SkillsHub(shared / "skills")

        # Agent runtimes
        self.agents: dict[str, AgentRuntime] = {}

        # Socket server
        self.server = ManagerServer(str(self.evolution_dir / "manager.sock"))

        # State
        self._running = False
        self._best_score: float | None = None
        self._best_agent: str = ""
        self._stagnation_start: float = time.monotonic()
        self._session_start: float = time.monotonic()
        self._shake_up_count: int = 0

    def setup(self) -> None:
        """Create worktrees and provision all agents."""
        task_path = Path(self.config.task.path)
        seed_path = task_path / "seed" if (task_path / "seed").exists() else None

        for agent_name, agent_config in self.config.agents.items():
            role_config = self.config.roles[agent_config.role]
            adapter = ADAPTERS[agent_config.runtime]()

            # Create worktree
            wt_path = self.workspace.create_worktree(agent_name)

            # Copy seed if exists
            if seed_path and seed_path.exists():
                self.workspace.copy_seed(wt_path, seed_path)

            # Symlink shared directory
            shared = self.evolution_dir / "shared"
            self.workspace.link_shared(wt_path, shared)

            # Create inbox
            self.workspace.create_inbox(wt_path)

            # Provision and write instructions
            adapter.provision(wt_path, agent_config)
            adapter.write_instructions(
                wt_path, role_config.prompt, self.config.task.description
            )

            # Create runtime
            runtime = AgentRuntime(agent_name, agent_config, role_config)
            runtime.worktree_path = wt_path
            self.agents[agent_name] = runtime

            log.info(f"Provisioned agent: {agent_name}")

    def handle_request(self, request: dict) -> dict:
        """Handle a request from the Unix socket."""
        req_type = request.get("type", "")
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
            self._running = False
            return {"status": "stopping"}
        else:
            return {"error": f"Unknown request type: {req_type}"}

    def _handle_eval(self, request: dict) -> dict:
        agent_name = request.get("agent", "")
        description = request.get("description", "")
        runtime = self.agents.get(agent_name)

        if not runtime:
            return {"error": f"Unknown agent: {agent_name}"}
        if runtime.paused:
            return {"error": "Agent is paused"}

        # Commit current worktree state
        wt = runtime.worktree_path
        subprocess.run(["git", "add", "-A"], cwd=wt, capture_output=True)
        commit_result = subprocess.run(
            ["git", "commit", "-m", description],
            cwd=wt, capture_output=True,
        )
        if commit_result.returncode != 0:
            # Nothing to commit — still grade the current state
            pass
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=wt, capture_output=True, text=True,
        ).stdout.strip()

        # Grade
        grader_config = self.config.task.grader or {}
        grader_script = grader_config.get("script", "")
        if grader_script:
            task_path = Path(self.config.task.path)
            script_path = str(task_path / grader_script.lstrip("./"))
            grader = ScriptGrader(script_path)
            result = grader.grade(str(wt))
        else:
            result = GradeResult(score=None, feedback="No grader configured")

        # Record attempt
        direction = "lower_is_better"
        if self.config.task.metric:
            direction = self.config.task.metric.get("direction", "lower_is_better")

        attempt = self.attempts.record(
            agent=agent_name,
            score=result.score,
            description=description,
            commit=commit,
            feedback=result.feedback,
        )

        # Track heartbeat
        runtime.heartbeat.record_attempt()

        # Check for improvement
        if result.score is not None:
            self._check_improvement(result.score, agent_name, direction)

        return {
            "status": "ok",
            "attempt_id": attempt.id,
            "score": result.score,
            "feedback": result.feedback,
        }

    def _handle_note(self, request: dict) -> dict:
        agent = request.get("agent", "")
        text = request.get("text", "")
        tags = request.get("tags", [])
        note = self.notes.add(agent=agent, text=text, tags=tags)
        return {"status": "ok", "timestamp": note.timestamp}

    def _handle_skill(self, request: dict) -> dict:
        author = request.get("author", "")
        name = request.get("name", "")
        content = request.get("content", "")
        tags = request.get("tags", [])
        skill = self.skills.add(author=author, name=name, content=content, tags=tags)
        return {"status": "ok", "name": skill.name}

    def _handle_status(self, request: dict) -> dict:
        agent_filter = request.get("agent")
        agents_status = {}
        for name, runtime in self.agents.items():
            if agent_filter and name != agent_filter:
                continue
            agents_status[name] = {
                "alive": runtime.is_alive(),
                "paused": runtime.paused,
                "restarts": runtime.restart_count,
            }
        best = self.attempts.best(
            direction=self.config.task.metric.get("direction", "lower_is_better")
            if self.config.task.metric else "lower_is_better"
        )
        return {
            "status": "ok",
            "agents": agents_status,
            "total_attempts": len(self.attempts.list()),
            "best_score": best.score if best else None,
            "best_agent": best.agent if best else None,
        }

    def _handle_attempts_list(self, request: dict) -> dict:
        direction = "lower_is_better"
        if self.config.task.metric:
            direction = self.config.task.metric.get("direction", "lower_is_better")
        board = self.attempts.leaderboard(direction)
        return {
            "status": "ok",
            "attempts": [
                {"id": a.id, "agent": a.agent, "score": a.score}
                for a in board
            ],
        }

    def _handle_attempts_show(self, request: dict) -> dict:
        attempt_id = request.get("id", 0)
        attempt = self.attempts.get(attempt_id)
        if not attempt:
            return {"error": f"Attempt {attempt_id} not found"}
        return {
            "status": "ok",
            "id": attempt.id,
            "agent": attempt.agent,
            "score": attempt.score,
            "description": attempt.description,
            "feedback": attempt.feedback,
        }

    def _handle_notes_list(self, request: dict) -> dict:
        agent = request.get("agent")
        notes = self.notes.list(agent=agent)
        return {
            "status": "ok",
            "notes": [{"agent": n.agent, "text": n.text, "tags": n.tags} for n in notes],
        }

    def _handle_msg(self, request: dict) -> dict:
        target = request.get("target", "")  # agent name, --all, or --role=X
        message = request.get("message", "")
        role = request.get("role")
        broadcast = request.get("all", False)
        msg_content = f"## Message from User\n\n{message}\n"

        targets = []
        if broadcast:
            targets = list(self.agents.keys())
        elif role:
            targets = [
                name for name, rt in self.agents.items()
                if rt.agent_config.role == role
            ]
        elif target in self.agents:
            targets = [target]
        else:
            return {"error": f"Unknown target: {target}"}

        for agent_name in targets:
            runtime = self.agents[agent_name]
            adapter = ADAPTERS[runtime.agent_config.runtime]()
            adapter.deliver_message(runtime.worktree_path, agent_name, msg_content)

        return {"status": "ok", "delivered_to": targets}

    def _handle_pause(self, request: dict) -> dict:
        agent_name = request.get("agent", "")
        runtime = self.agents.get(agent_name)
        if not runtime:
            return {"error": f"Unknown agent: {agent_name}"}
        runtime.paused = True
        adapter = ADAPTERS[runtime.agent_config.runtime]()
        adapter.deliver_message(
            runtime.worktree_path, agent_name,
            "## System: You are PAUSED\n\nStop working. Wait for a resume signal.",
        )
        return {"status": "ok", "agent": agent_name, "paused": True}

    def _handle_resume(self, request: dict) -> dict:
        agent_name = request.get("agent", "")
        runtime = self.agents.get(agent_name)
        if not runtime:
            return {"error": f"Unknown agent: {agent_name}"}
        runtime.paused = False
        adapter = ADAPTERS[runtime.agent_config.runtime]()
        adapter.deliver_message(
            runtime.worktree_path, agent_name,
            "## System: You are RESUMED\n\nContinue working.",
        )
        return {"status": "ok", "agent": agent_name, "paused": False}

    def _handle_kill(self, request: dict) -> dict:
        agent_name = request.get("agent", "")
        runtime = self.agents.get(agent_name)
        if not runtime:
            return {"error": f"Unknown agent: {agent_name}"}
        if runtime.process and runtime.is_alive():
            runtime.process.terminate()
        self.workspace.teardown_worktree(agent_name)
        del self.agents[agent_name]
        return {"status": "ok", "killed": agent_name}

    def _handle_spawn(self, request: dict) -> dict:
        clone_from = request.get("clone")
        role = request.get("role")
        runtime_name = request.get("runtime")

        if clone_from:
            if clone_from not in self.agents:
                return {"error": f"Unknown agent to clone: {clone_from}"}
            source = self.agents[clone_from]
            # Auto-suffix name
            i = 2
            new_name = f"{clone_from}-{i}"
            while new_name in self.agents:
                i += 1
                new_name = f"{clone_from}-{i}"
            agent_config = source.agent_config
            role_config = source.role_config
        elif role and runtime_name:
            if role not in self.config.roles:
                return {"error": f"Unknown role: {role}"}
            role_config = self.config.roles[role]
            agent_config = AgentConfig(role=role, runtime=runtime_name)
            new_name = f"{runtime_name}-{role}-spawned"
        else:
            return {"error": "Specify --clone or --role + --runtime"}

        # Create worktree from best attempt's code
        wt_path = self.workspace.create_worktree(new_name)
        shared = self.evolution_dir / "shared"
        self.workspace.link_shared(wt_path, shared)
        self.workspace.create_inbox(wt_path)

        adapter = ADAPTERS[agent_config.runtime]()
        adapter.provision(wt_path, agent_config)
        adapter.write_instructions(wt_path, role_config.prompt, self.config.task.description)

        rt = AgentRuntime(new_name, agent_config, role_config)
        rt.worktree_path = wt_path
        rt.process = adapter.spawn(wt_path, agent_config)
        self.agents[new_name] = rt

        return {"status": "ok", "spawned": new_name}

    def _check_improvement(self, score: float, agent_name: str, direction: str) -> None:
        improved = False
        if self._best_score is None:
            improved = True
        elif direction == "lower_is_better" and score < self._best_score:
            improved = True
        elif direction == "higher_is_better" and score > self._best_score:
            improved = True

        if improved:
            self._best_score = score
            self._best_agent = agent_name
            self._stagnation_start = time.monotonic()
            # Check milestones
            self._check_milestones(score, agent_name)

    def _check_milestones(self, score: float, agent_name: str) -> None:
        milestones = self.config.task.milestones
        direction = "lower_is_better"
        if self.config.task.metric:
            direction = self.config.task.metric.get("direction", "lower_is_better")

        for level in ["baseline", "target", "stretch"]:
            threshold = getattr(milestones, level, None)
            if threshold is None:
                continue
            reached = (direction == "lower_is_better" and score <= threshold) or \
                      (direction == "higher_is_better" and score >= threshold)
            if reached:
                msg = (
                    f"## Milestone Reached: {level}\n\n"
                    f"Score {score} by {agent_name} beats {level} ({threshold}).\n"
                    f"Session continues.\n"
                )
                for name, rt in self.agents.items():
                    adapter = ADAPTERS[rt.agent_config.runtime]()
                    adapter.deliver_message(rt.worktree_path, name, msg)

    def check_stop_conditions(self) -> str | None:
        """Return stop reason if any condition is met, else None."""
        stop = self.config.task.stop

        # Max time
        from evolution.manager.heartbeat import parse_duration
        max_seconds = parse_duration(stop.max_time)
        if time.monotonic() - self._session_start >= max_seconds:
            return f"Max time reached ({stop.max_time})"

        # Max attempts
        if stop.max_attempts and len(self.attempts.list()) >= stop.max_attempts:
            return f"Max attempts reached ({stop.max_attempts})"

        # Stagnation
        stagnation_seconds = parse_duration(stop.stagnation)
        if time.monotonic() - self._stagnation_start >= stagnation_seconds:
            if stop.stagnation_action == "shake_up" and self._shake_up_count < stop.shake_up_budget:
                self._shake_up_count += 1
                msg = (
                    f"## Shake-Up #{self._shake_up_count}\n\n"
                    f"No improvement for {stop.stagnation}. "
                    f"Try a radically different approach — abandon your current line of work.\n"
                )
                for name, rt in self.agents.items():
                    adapter = ADAPTERS[rt.agent_config.runtime]()
                    adapter.deliver_message(rt.worktree_path, name, msg)
                self._stagnation_start = time.monotonic()
                return None
            return f"Stagnation ({stop.stagnation})"

        return None

    def save_state(self) -> None:
        """Persist manager state for crash recovery."""
        state = {
            "best_score": self._best_score,
            "best_agent": self._best_agent,
            "agents": {
                name: {"restart_count": rt.restart_count, "paused": rt.paused}
                for name, rt in self.agents.items()
            },
        }
        state_path = self.evolution_dir / "state.json"
        state_path.write_text(json.dumps(state, indent=2))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_manager.py -v`
Expected: All PASS

---

### Task 8: CLI — Core Commands

**Files:**
- Create: `evolution/cli/main.py`
- Create: `evolution/cli/run.py`
- Create: `evolution/cli/eval.py`
- Create: `evolution/cli/status.py`
- Create: `evolution/cli/note.py`
- Create: `evolution/cli/msg.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for CLI parsing**

```python
# tests/test_cli.py
import pytest
from unittest.mock import patch, MagicMock
from evolution.cli.main import build_parser


def test_parser_has_subcommands():
    parser = build_parser()
    # Should not raise
    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_parser_eval_with_message():
    parser = build_parser()
    args = parser.parse_args(["eval", "-m", "test change"])
    assert args.command == "eval"
    assert args.message == "test change"


def test_parser_note_add():
    parser = build_parser()
    args = parser.parse_args(["note", "add", "my insight"])
    assert args.command == "note"
    assert args.note_command == "add"
    assert args.text == "my insight"


def test_parser_msg_to_agent():
    parser = build_parser()
    args = parser.parse_args(["msg", "claude-researcher", "try this approach"])
    assert args.command == "msg"
    assert args.target == "claude-researcher"
    assert args.message == "try this approach"


def test_parser_msg_broadcast():
    parser = build_parser()
    args = parser.parse_args(["msg", "--all", "focus on score"])
    assert args.command == "msg"
    assert args.all is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CLI main with argparse**

```python
# evolution/cli/main.py
from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evolution", description="Multi-agent evolution platform")
    sub = parser.add_subparsers(dest="command")

    # evolution run
    run_p = sub.add_parser("run", help="Start an evolution session")
    run_p.add_argument("--config", default="evolution.yaml", help="Config file path")
    run_p.add_argument("--resume", action="store_true", help="Resume a crashed session")

    # evolution eval
    eval_p = sub.add_parser("eval", help="Submit work for evaluation")
    eval_p.add_argument("-m", "--message", required=True, help="Description of changes")

    # evolution note
    note_p = sub.add_parser("note", help="Share knowledge")
    note_sub = note_p.add_subparsers(dest="note_command")
    note_add = note_sub.add_parser("add", help="Add a note")
    note_add.add_argument("text", help="Note text")
    note_add.add_argument("--tags", default="", help="Comma-separated tags")

    # evolution skill
    skill_p = sub.add_parser("skill", help="Publish reusable tools")
    skill_sub = skill_p.add_subparsers(dest="skill_command")
    skill_add = skill_sub.add_parser("add", help="Add a skill")
    skill_add.add_argument("file", help="Skill markdown file")

    # evolution status
    status_p = sub.add_parser("status", help="Query system state")
    status_p.add_argument("--agent", default=None, help="Filter by agent name")

    # evolution attempts
    att_p = sub.add_parser("attempts", help="View attempts")
    att_sub = att_p.add_subparsers(dest="attempts_command")
    att_sub.add_parser("list", help="List all attempts")
    att_show = att_sub.add_parser("show", help="Show attempt details")
    att_show.add_argument("id", type=int, help="Attempt ID")

    # evolution notes
    notes_p = sub.add_parser("notes", help="View notes")
    notes_sub = notes_p.add_subparsers(dest="notes_command")
    notes_list = notes_sub.add_parser("list", help="List notes")
    notes_list.add_argument("--agent", default=None, help="Filter by agent")

    # evolution skills
    skills_p = sub.add_parser("skills", help="View skills")
    skills_sub = skills_p.add_subparsers(dest="skills_command")
    skills_sub.add_parser("list", help="List skills")

    # evolution msg
    msg_p = sub.add_parser("msg", help="Send message to agent(s)")
    msg_p.add_argument("target", nargs="?", default=None, help="Agent name")
    msg_p.add_argument("message", nargs="?", default="", help="Message text")
    msg_p.add_argument("--all", action="store_true", help="Broadcast to all agents")
    msg_p.add_argument("--role", default=None, help="Send to agents with this role")

    # evolution pause/resume/kill/stop/spawn
    sub.add_parser("stop", help="Stop the session")
    pause_p = sub.add_parser("pause", help="Pause an agent")
    pause_p.add_argument("agent", help="Agent name")
    resume_p = sub.add_parser("resume", help="Resume an agent")
    resume_p.add_argument("agent", help="Agent name")
    kill_p = sub.add_parser("kill", help="Kill an agent")
    kill_p.add_argument("agent", help="Agent name")
    spawn_p = sub.add_parser("spawn", help="Spawn a new agent")
    spawn_p.add_argument("--clone", default=None, help="Clone existing agent config")
    spawn_p.add_argument("--role", default=None, help="Role name")
    spawn_p.add_argument("--runtime", default=None, help="Runtime name")

    # evolution benchmark
    bench_p = sub.add_parser("benchmark", help="Run benchmarks")
    bench_p.add_argument("--all", action="store_true", help="Run all benchmarks")
    bench_p.add_argument("--compare", default=None, help="Compare against baseline")

    # evolution report/export/timeline
    sub.add_parser("report", help="Session summary")
    export_p = sub.add_parser("export", help="Export attempts")
    export_p.add_argument("--format", default="csv", help="Output format")
    sub.add_parser("timeline", help="Agent timeline")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Import handlers lazily to keep startup fast
    from evolution.manager.server import send_request

    # Resolve socket path from git repo root (works from any worktree)
    import subprocess as _sp
    _root = _sp.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    ).stdout.strip()
    # If inside a worktree, find the main repo root
    _common = _sp.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True,
    ).stdout
    for line in _common.splitlines():
        if line.startswith("worktree ") and not line.endswith(_root):
            # First worktree listed is the main one
            _root = line.split("worktree ", 1)[1]
            break
    sock_path = str(Path(_root) / ".evolution" / "manager.sock")

    if args.command == "run":
        from evolution.cli.run import cmd_run
        cmd_run(args)
    elif args.command == "eval":
        resp = send_request(sock_path, {
            "type": "eval",
            "agent": _detect_agent_name(),
            "description": args.message,
        })
        _print_eval_result(resp)
    elif args.command == "note" and args.note_command == "add":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        resp = send_request(sock_path, {
            "type": "note",
            "agent": _detect_agent_name(),
            "text": args.text,
            "tags": tags,
        })
        print(f"Note added: {resp.get('timestamp', '')}")
    elif args.command == "status":
        resp = send_request(sock_path, {"type": "status", "agent": args.agent})
        _print_status(resp)
    elif args.command == "attempts":
        if args.attempts_command == "list":
            resp = send_request(sock_path, {"type": "attempts_list"})
            _print_attempts(resp)
        elif args.attempts_command == "show":
            resp = send_request(sock_path, {"type": "attempts_show", "id": args.id})
            _print_attempt_detail(resp)
    elif args.command == "notes" and args.notes_command == "list":
        resp = send_request(sock_path, {"type": "notes_list", "agent": args.agent})
        _print_notes(resp)
    elif args.command == "msg":
        resp = send_request(sock_path, {
            "type": "msg",
            "target": args.target or "",
            "message": args.message,
            "all": args.all,
            "role": args.role,
        })
        targets = resp.get("delivered_to", [])
        print(f"Message delivered to: {', '.join(targets)}")
    elif args.command == "pause":
        resp = send_request(sock_path, {"type": "pause", "agent": args.agent})
        print(f"Paused: {args.agent}")
    elif args.command == "resume":
        resp = send_request(sock_path, {"type": "resume", "agent": args.agent})
        print(f"Resumed: {args.agent}")
    elif args.command == "kill":
        resp = send_request(sock_path, {"type": "kill", "agent": args.agent})
        print(f"Killed: {args.agent}")
    elif args.command == "spawn":
        resp = send_request(sock_path, {
            "type": "spawn",
            "clone": args.clone,
            "role": args.role,
            "runtime": args.runtime,
        })
        print(f"Spawned: {resp.get('spawned', 'error')}")
    elif args.command == "skills" and getattr(args, "skills_command", None) == "list":
        resp = send_request(sock_path, {"type": "skills_list"})
        for s in resp.get("skills", []):
            print(f"  {s['name']} (by {s['author']})")
    elif args.command == "stop":
        resp = send_request(sock_path, {"type": "stop"})
        print("Session stopping...")
    elif args.command == "report":
        from evolution.cli.report import format_report
        from evolution.hub.attempts import AttemptsHub
        hub = AttemptsHub(Path(_root) / ".evolution" / "shared" / "attempts")
        print(format_report(hub))
    elif args.command == "export":
        from evolution.cli.report import export_csv
        from evolution.hub.attempts import AttemptsHub
        hub = AttemptsHub(Path(_root) / ".evolution" / "shared" / "attempts")
        out = f"evolution-export.{args.format}"
        export_csv(hub, out)
        print(f"Exported to {out}")
    else:
        parser.print_help()


def _detect_agent_name() -> str:
    """Detect which agent we are based on the current working directory."""
    import os
    cwd = os.getcwd()
    # Worktree path contains agent name: .evolution/worktrees/<agent-name>
    if ".evolution/worktrees/" in cwd:
        parts = cwd.split(".evolution/worktrees/")
        return parts[1].split("/")[0]
    return "unknown"


def _print_eval_result(resp: dict) -> None:
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    score = resp.get("score", "N/A")
    print(f"Attempt #{resp.get('attempt_id')}: score={score}")
    if resp.get("feedback"):
        print(f"Feedback: {resp['feedback']}")


def _print_status(resp: dict) -> None:
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    print(f"Total attempts: {resp.get('total_attempts', 0)}")
    print(f"Best score: {resp.get('best_score', 'N/A')} by {resp.get('best_agent', 'N/A')}")
    for name, info in resp.get("agents", {}).items():
        status = "alive" if info["alive"] else "dead"
        if info["paused"]:
            status = "paused"
        print(f"  {name}: {status} (restarts: {info['restarts']})")


def _print_attempts(resp: dict) -> None:
    for a in resp.get("attempts", []):
        print(f"  #{a['id']:03d}  {a['agent']:<25} score={a['score']}")


def _print_attempt_detail(resp: dict) -> None:
    if "error" in resp:
        print(f"Error: {resp['error']}")
        return
    print(f"Attempt #{resp['id']} by {resp['agent']}")
    print(f"Score: {resp['score']}")
    print(f"Description: {resp['description']}")
    print(f"Feedback: {resp['feedback']}")


def _print_notes(resp: dict) -> None:
    for n in resp.get("notes", []):
        tags = f" [{', '.join(n['tags'])}]" if n['tags'] else ""
        print(f"  {n['agent']}{tags}: {n['text'][:80]}")
```

- [ ] **Step 4: Implement `evolution run` command**

```python
# evolution/cli/run.py
from __future__ import annotations

import logging
import threading
from pathlib import Path
from evolution.manager.config import load_config
from evolution.manager.manager import Manager


def cmd_run(args) -> None:
    """Start an evolution session."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log = logging.getLogger("evolution")

    config = load_config(args.config)
    log.info(f"Starting session: {config.session.name}")

    repo_root = Path(".").resolve()
    manager = Manager(config, repo_root)

    # Setup worktrees and provision agents
    manager.setup()

    # Start socket server in a thread
    server_thread = threading.Thread(
        target=manager.server.serve_forever,
        args=(manager.handle_request,),
        daemon=True,
    )
    server_thread.start()
    log.info("Manager socket server started")

    # Spawn agents (use manager's ADAPTERS registry)
    from evolution.manager.manager import ADAPTERS

    for name, runtime in manager.agents.items():
        adapter_cls = ADAPTERS.get(runtime.agent_config.runtime)
        if adapter_cls:
            adapter = adapter_cls()
            runtime.process = adapter.spawn(runtime.worktree_path, runtime.agent_config)
            log.info(f"Spawned agent: {name} (pid={runtime.process.pid})")
        else:
            log.error(f"No adapter for runtime: {runtime.agent_config.runtime}")

    log.info("All agents spawned. Manager loop running. Press Ctrl+C to stop.")

    # Manager loop
    import time as _time
    try:
        manager._running = True
        while manager._running:
            # Check stop conditions
            stop_reason = manager.check_stop_conditions()
            if stop_reason:
                log.info(f"Stopping: {stop_reason}")
                break

            # Check agent health and heartbeats
            for name, runtime in list(manager.agents.items()):
                if runtime.is_dead() and not runtime.paused:
                    if (runtime.restart_count < runtime.agent_config.restart.max_restarts
                            and runtime.agent_config.restart.enabled):
                        log.warning(f"Agent {name} died, restarting...")
                        runtime.restart_count += 1
                        adapter_cls = ADAPTERS.get(runtime.agent_config.runtime)
                        if adapter_cls:
                            adapter = adapter_cls()
                            runtime.process = adapter.spawn(
                                runtime.worktree_path, runtime.agent_config
                            )
                    else:
                        log.error(f"Agent {name} died and exceeded max restarts")

                if runtime.is_alive() and runtime.heartbeat.should_fire():
                    adapter_cls = ADAPTERS.get(runtime.agent_config.runtime)
                    if adapter_cls:
                        adapter = adapter_cls()
                        best = manager.attempts.best()
                        heartbeat_msg = _build_heartbeat_message(manager, name, best)
                        adapter.deliver_message(
                            runtime.worktree_path, name, heartbeat_msg
                        )
                        runtime.heartbeat.reset()

            manager.save_state()
            _time.sleep(5)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        manager.server.shutdown()
        for name, runtime in manager.agents.items():
            if runtime.process and runtime.is_alive():
                runtime.process.terminate()
        log.info("Session ended.")


def _build_heartbeat_message(manager: Manager, agent_name: str, best) -> str:
    msg = "## Heartbeat — Time to Reflect\n\n"
    msg += "Before continuing:\n\n"
    msg += "1. Check the leaderboard: `evolution attempts list`\n"
    msg += "2. Read recent notes: `evolution notes list`\n"
    if best:
        msg += f"3. Current best score: {best.score} by {best.agent}\n"
    msg += "\nConsider:\n"
    msg += "- Is your current approach still promising?\n"
    msg += "- Can you build on anyone else's insights?\n"
    msg += "- Write a note about what you've learned so far.\n"
    return msg
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_cli.py -v`
Expected: All PASS

---

### Task 9: Integration Test — Single Agent Loop

**Files:**
- Create: `tests/test_integration.py`
- Create: `tests/fixtures/simple_task/task.yaml`
- Create: `tests/fixtures/simple_task/grader.py`
- Create: `tests/fixtures/simple_task/seed/solver.py`

- [ ] **Step 1: Create test fixtures**

```yaml
# tests/fixtures/simple_task/task.yaml
name: simple-test
description: "Maximize the value returned by solver.py"
metric:
  name: score
  direction: higher_is_better
grader:
  type: script
  script: ./grader.py
seed: ./seed/
milestones:
  baseline: 0.0
  target: 5.0
stop:
  max_time: 1h
  manual: true
```

```python
# tests/fixtures/simple_task/grader.py
#!/usr/bin/env python3
"""Simple grader: imports solver and prints its output."""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("solver", "solver.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.solve())
```

```python
# tests/fixtures/simple_task/seed/solver.py
def solve():
    return 1.0
```

- [ ] **Step 2: Write integration test**

```python
# tests/test_integration.py
"""Integration test: setup manager, eval an attempt, verify leaderboard."""
import json
import subprocess
import threading
import time
import pytest
from pathlib import Path
from evolution.manager.config import load_config, EvolutionConfig, SessionConfig, TaskConfig, RoleConfig, AgentConfig, SuperagentConfig
from evolution.manager.manager import Manager
from evolution.manager.server import send_request


@pytest.fixture
def integration_repo(tmp_path):
    """Create a git repo with a simple task for integration testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)

    # Create task
    task_dir = repo / "tasks" / "simple"
    task_dir.mkdir(parents=True)
    seed_dir = task_dir / "seed"
    seed_dir.mkdir()
    (seed_dir / "solver.py").write_text("def solve():\n    return 1.0\n")
    (task_dir / "grader.py").write_text(
        "#!/usr/bin/env python3\n"
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('solver', 'solver.py')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "print(mod.solve())\n"
    )

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


@pytest.fixture
def integration_config(integration_repo):
    return EvolutionConfig(
        session=SessionConfig(name="test-integration"),
        task=TaskConfig(
            name="simple-test",
            description="Maximize solver output",
            path=str(integration_repo / "tasks" / "simple"),
            seed="./seed/",
            metric={"name": "score", "direction": "higher_is_better"},
            grader={"type": "script", "script": "./grader.py"},
        ),
        roles={"researcher": RoleConfig(prompt="You are a test researcher.")},
        agents={"test-agent": AgentConfig(role="researcher", runtime="claude-code")},
        superagent=SuperagentConfig(enabled=False),
    )


def test_manager_setup_creates_worktrees(integration_repo, integration_config):
    manager = Manager(integration_config, integration_repo)
    manager.setup()
    wt = integration_repo / ".evolution" / "worktrees" / "test-agent"
    assert wt.exists()
    assert (wt / "solver.py").exists()
    assert (wt / "CLAUDE.md").exists()
    assert (wt / ".evolution" / "shared").is_symlink()
    assert (wt / ".evolution" / "inbox").is_dir()


def test_eval_via_socket(integration_repo, integration_config):
    manager = Manager(integration_config, integration_repo)
    manager.setup()

    # Start server
    server_thread = threading.Thread(
        target=manager.server.serve_forever,
        args=(manager.handle_request,),
        daemon=True,
    )
    server_thread.start()
    time.sleep(0.2)

    try:
        sock_path = str(integration_repo / ".evolution" / "manager.sock")
        resp = send_request(sock_path, {
            "type": "eval",
            "agent": "test-agent",
            "description": "Initial seed eval",
        })
        assert resp["status"] == "ok"
        assert resp["score"] == 1.0
        assert resp["attempt_id"] == 1

        # Check leaderboard
        resp2 = send_request(sock_path, {"type": "attempts_list"})
        assert len(resp2["attempts"]) == 1
        assert resp2["attempts"][0]["score"] == 1.0

        # Check status
        resp3 = send_request(sock_path, {"type": "status"})
        assert resp3["total_attempts"] == 1
        assert resp3["best_score"] == 1.0
    finally:
        manager.server.shutdown()
```

- [ ] **Step 3: Run integration test**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_integration.py -v`
Expected: All PASS

---

### Task 10: Grader — LLM + Hybrid

**Files:**
- Create: `evolution/grader/llm.py`
- Create: `evolution/grader/hybrid.py`
- Test: `tests/test_grader_llm.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_grader_llm.py
import pytest
from unittest.mock import patch, MagicMock
from evolution.grader.llm import LLMGrader
from evolution.grader.hybrid import HybridGrader


def test_llm_grader_calls_openrouter(tmp_path):
    with patch("evolution.grader.llm.call_openrouter") as mock_call:
        mock_call.return_value = {"score": 7.5, "feedback": "Good approach"}
        grader = LLMGrader(task_description="Optimize code", model="openai/gpt-4o")
        result = grader.grade(str(tmp_path))
        assert result.score == 7.5
        assert "Good approach" in result.feedback


def test_llm_grader_handles_api_error(tmp_path):
    with patch("evolution.grader.llm.call_openrouter") as mock_call:
        mock_call.side_effect = Exception("API timeout")
        grader = LLMGrader(task_description="test", model="openai/gpt-4o")
        result = grader.grade(str(tmp_path))
        assert result.score is None
        assert "error" in result.feedback.lower()


def test_hybrid_grader_combines_script_and_llm(tmp_path):
    script = tmp_path / "grader.py"
    script.write_text("print('0.38091')")
    with patch("evolution.grader.llm.call_openrouter") as mock_call:
        mock_call.return_value = {"score": 8.0, "feedback": "Try cooling schedules"}
        grader = HybridGrader(
            script_path=str(script),
            task_description="Minimize overlap",
            model="openai/gpt-4o",
        )
        result = grader.grade(str(tmp_path))
        assert result.score == pytest.approx(0.38091)  # script score wins
        assert "Try cooling" in result.feedback  # LLM feedback included
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_grader_llm.py -v`
Expected: FAIL

- [ ] **Step 3: Implement LLM grader**

```python
# evolution/grader/llm.py
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from evolution.grader.protocol import GradeResult

log = logging.getLogger(__name__)


def call_openrouter(prompt: str, model: str) -> dict:
    """Call OpenRouter API. Returns dict with 'score' and 'feedback' keys."""
    try:
        from openrouter import OpenRouter
        client = OpenRouter()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content
        # Parse JSON from response
        return json.loads(text)
    except ImportError:
        raise ImportError("openrouter package not installed")


class LLMGrader:
    def __init__(self, task_description: str, model: str = "openai/gpt-4o"):
        self.task_description = task_description
        self.model = model

    def grade(self, attempt_path: str) -> GradeResult:
        try:
            # Get diff
            diff = subprocess.run(
                ["git", "diff", "HEAD~1"],
                cwd=attempt_path,
                capture_output=True,
                text=True,
            ).stdout or "(no diff available)"

            prompt = (
                f"You are evaluating code for this task: {self.task_description}\n\n"
                f"Here is the diff:\n```\n{diff[:4000]}\n```\n\n"
                f"Respond with ONLY valid JSON: {{\"score\": <float 0-10>, \"feedback\": \"<text>\"}}"
            )
            result = call_openrouter(prompt, self.model)
            return GradeResult(
                score=float(result.get("score", 0)),
                feedback=result.get("feedback", ""),
            )
        except Exception as e:
            return GradeResult(score=None, feedback=f"LLM grader error: {e}")
```

- [ ] **Step 4: Implement hybrid grader**

```python
# evolution/grader/hybrid.py
from __future__ import annotations

import logging
from evolution.grader.protocol import GradeResult
from evolution.grader.script import ScriptGrader
from evolution.grader.llm import LLMGrader

log = logging.getLogger(__name__)


class HybridGrader:
    """Script provides the hard metric, LLM provides strategic feedback."""

    def __init__(self, script_path: str, task_description: str, model: str = "openai/gpt-4o"):
        self.script_grader = ScriptGrader(script_path)
        self.llm_grader = LLMGrader(task_description, model)

    def grade(self, attempt_path: str) -> GradeResult:
        # Script score is authoritative
        script_result = self.script_grader.grade(attempt_path)

        # LLM provides qualitative feedback (best-effort)
        try:
            llm_result = self.llm_grader.grade(attempt_path)
            feedback = llm_result.feedback
        except Exception as e:
            feedback = f"(LLM feedback unavailable: {e})"

        combined_feedback = ""
        if script_result.feedback:
            combined_feedback += f"**Script:** {script_result.feedback}\n"
        combined_feedback += f"**LLM:** {feedback}"

        return GradeResult(
            score=script_result.score,
            feedback=combined_feedback,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_grader_llm.py -v`
Expected: All PASS

---

### Task 11: Adapters — Codex + OpenCode

**Files:**
- Create: `evolution/adapters/codex.py`
- Create: `evolution/adapters/opencode.py`
- Test: `tests/test_adapters_extra.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_adapters_extra.py
import pytest
from pathlib import Path
from evolution.adapters.codex import CodexAdapter
from evolution.adapters.opencode import OpenCodeAdapter
from evolution.manager.config import AgentConfig


def test_codex_instruction_file():
    assert CodexAdapter().instruction_file == "AGENTS.md"


def test_codex_write_instructions(tmp_path):
    adapter = CodexAdapter()
    adapter.write_instructions(tmp_path, "You are a researcher.", "Minimize C5")
    assert (tmp_path / "AGENTS.md").exists()
    content = (tmp_path / "AGENTS.md").read_text()
    assert "researcher" in content
    assert "evolution eval" in content


def test_opencode_instruction_file():
    assert OpenCodeAdapter().instruction_file == "AGENTS.md"


def test_opencode_write_instructions(tmp_path):
    adapter = OpenCodeAdapter()
    adapter.write_instructions(tmp_path, "You are an explorer.", "Optimize kernel")
    assert (tmp_path / "AGENTS.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_adapters_extra.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Codex and OpenCode adapters**

```python
# evolution/adapters/codex.py
from __future__ import annotations

import subprocess
from pathlib import Path
from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import INSTRUCTION_TEMPLATE
from evolution.manager.config import AgentConfig


class CodexAdapter(AgentAdapter):
    name = "codex"
    instruction_file = "AGENTS.md"

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        # Codex reads AGENTS.md directly, minimal config needed
        pass

    def write_instructions(self, worktree_path: Path, prompt: str, task_description: str) -> None:
        content = INSTRUCTION_TEMPLATE.format(prompt=prompt, task_description=task_description)
        (worktree_path / self.instruction_file).write_text(content)

    def spawn(self, worktree_path: Path, agent_config: AgentConfig) -> subprocess.Popen:
        import os
        env = {**os.environ, **agent_config.env} if agent_config.env else None
        return subprocess.Popen(
            ["codex", "--approval-mode", "full-auto"],
            cwd=str(worktree_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
```

```python
# evolution/adapters/opencode.py
from __future__ import annotations

import subprocess
from pathlib import Path
from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import INSTRUCTION_TEMPLATE
from evolution.manager.config import AgentConfig


class OpenCodeAdapter(AgentAdapter):
    name = "opencode"
    instruction_file = "AGENTS.md"

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        pass

    def write_instructions(self, worktree_path: Path, prompt: str, task_description: str) -> None:
        content = INSTRUCTION_TEMPLATE.format(prompt=prompt, task_description=task_description)
        (worktree_path / self.instruction_file).write_text(content)

    def spawn(self, worktree_path: Path, agent_config: AgentConfig) -> subprocess.Popen:
        import os
        env = {**os.environ, **agent_config.env} if agent_config.env else None
        return subprocess.Popen(
            ["opencode"],
            cwd=str(worktree_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
```

- [ ] **Step 4: Register adapters in manager**

In `evolution/manager/manager.py`, update the ADAPTERS dict:

```python
from evolution.adapters.codex import CodexAdapter
from evolution.adapters.opencode import OpenCodeAdapter

ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_adapters_extra.py -v`
Expected: All PASS

---

### Task 12: Multi-Metric Evaluation + Ranking

**Files:**
- Create: `evolution/grader/ranking.py`
- Modify: `evolution/manager/manager.py` (multi-metric eval path)
- Test: `tests/test_ranking.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ranking.py
import pytest
from evolution.grader.ranking import (
    normalize_score,
    weighted_sum,
    pareto_dominates,
    pareto_rank,
    min_rank,
    all_must_improve,
)


def test_normalize_higher_is_better():
    assert normalize_score(75, 50, 100, "higher_is_better") == pytest.approx(0.5)
    assert normalize_score(100, 50, 100, "higher_is_better") == pytest.approx(1.0)


def test_normalize_lower_is_better():
    assert normalize_score(0.38, 0.40, 0.35, "lower_is_better") == pytest.approx(0.4)


def test_weighted_sum():
    scores = {"m1": 0.8, "m2": 0.6}
    weights = {"m1": 0.5, "m2": 0.5}
    assert weighted_sum(scores, weights) == pytest.approx(0.7)


def test_pareto_dominates():
    a = {"m1": 5, "m2": 3}
    b = {"m1": 4, "m2": 2}
    directions = {"m1": "higher_is_better", "m2": "higher_is_better"}
    assert pareto_dominates(a, b, directions)
    assert not pareto_dominates(b, a, directions)


def test_pareto_no_dominance():
    a = {"m1": 5, "m2": 2}
    b = {"m1": 4, "m2": 3}
    directions = {"m1": "higher_is_better", "m2": "higher_is_better"}
    assert not pareto_dominates(a, b, directions)
    assert not pareto_dominates(b, a, directions)


def test_all_must_improve_accepts():
    current_best = {"m1": 80, "m2": 70}
    new_scores = {"m1": 85, "m2": 75}
    directions = {"m1": "higher_is_better", "m2": "higher_is_better"}
    assert all_must_improve(new_scores, current_best, directions)


def test_all_must_improve_rejects_regression():
    current_best = {"m1": 80, "m2": 70}
    new_scores = {"m1": 85, "m2": 65}
    directions = {"m1": "higher_is_better", "m2": "higher_is_better"}
    assert not all_must_improve(new_scores, current_best, directions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_ranking.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ranking module**

```python
# evolution/grader/ranking.py
from __future__ import annotations


def normalize_score(
    value: float, worst: float, best: float, direction: str
) -> float:
    """Normalize a score to 0-1 range. 1.0 = best possible."""
    if best == worst:
        return 1.0
    if direction == "higher_is_better":
        return (value - worst) / (best - worst)
    else:  # lower_is_better
        return (worst - value) / (worst - best)


def weighted_sum(normalized_scores: dict[str, float], weights: dict[str, float]) -> float:
    """Compute weighted sum of normalized scores."""
    total = 0.0
    for metric, score in normalized_scores.items():
        total += score * weights.get(metric, 0)
    return total


def pareto_dominates(
    a: dict[str, float],
    b: dict[str, float],
    directions: dict[str, str],
) -> bool:
    """Return True if a dominates b (a is better on ALL metrics)."""
    dominated = True
    for metric in a:
        if directions.get(metric, "lower_is_better") == "higher_is_better":
            if a[metric] <= b[metric]:
                dominated = False
                break
        else:
            if a[metric] >= b[metric]:
                dominated = False
                break
    return dominated


def pareto_rank(
    attempts: list[dict[str, float]],
    directions: dict[str, str],
) -> list[int]:
    """Return Pareto rank for each attempt (0 = frontier)."""
    n = len(attempts)
    ranks = [0] * n
    for i in range(n):
        for j in range(n):
            if i != j and pareto_dominates(attempts[j], attempts[i], directions):
                ranks[i] += 1
    return ranks


def min_rank(
    attempts: list[dict[str, float]],
    directions: dict[str, str],
) -> list[int]:
    """Return worst per-metric rank for each attempt."""
    metrics = list(attempts[0].keys()) if attempts else []
    n = len(attempts)
    worst_ranks = [0] * n
    for metric in metrics:
        reverse = directions.get(metric) == "higher_is_better"
        sorted_indices = sorted(range(n), key=lambda i: attempts[i][metric], reverse=reverse)
        for rank, idx in enumerate(sorted_indices):
            worst_ranks[idx] = max(worst_ranks[idx], rank)
    return worst_ranks


def all_must_improve(
    new_scores: dict[str, float],
    current_best: dict[str, float],
    directions: dict[str, str],
) -> bool:
    """Return True only if new_scores improves EVERY metric."""
    for metric, new_val in new_scores.items():
        old_val = current_best.get(metric, new_val)
        if directions.get(metric) == "higher_is_better":
            if new_val <= old_val:
                return False
        else:
            if new_val >= old_val:
                return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_ranking.py -v`
Expected: All PASS

---

### Task 13: Superagent

**Files:**
- Create: `evolution/superagent/agent.py`
- Create: `evolution/superagent/commands.py`
- Test: `tests/test_superagent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_superagent.py
import pytest
from evolution.superagent.commands import build_superagent_instructions


def test_superagent_instructions_include_cli_commands():
    instructions = build_superagent_instructions(session_name="test-run")
    assert "evolution status" in instructions
    assert "evolution msg" in instructions
    assert "evolution attempts" in instructions
    assert "evolution pause" in instructions
    assert "evolution spawn" in instructions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_superagent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement superagent commands**

```python
# evolution/superagent/commands.py
from __future__ import annotations


def build_superagent_instructions(session_name: str) -> str:
    """Build the CLAUDE.md content for the superagent."""
    return f"""# Evolution Superagent

You are the superagent for evolution session: **{session_name}**

You have full access to the `evolution` CLI. Use it to monitor and control the session.

## Available Commands

### Monitoring
- `evolution status` — Show all agents, scores, uptime
- `evolution status --agent <name>` — Show specific agent
- `evolution attempts list` — Leaderboard
- `evolution attempts show <id>` — Attempt details
- `evolution notes list` — All notes
- `evolution notes list --agent <name>` — Notes from specific agent
- `evolution skills list` — Available skills

### Communication
- `evolution msg <agent> "message"` — Message specific agent
- `evolution msg --all "message"` — Broadcast to all
- `evolution msg --role <role> "message"` — Message by role

### Control
- `evolution pause <agent>` — Pause an agent
- `evolution resume <agent>` — Resume an agent
- `evolution kill <agent>` — Kill an agent
- `evolution spawn --clone <agent>` — Clone an agent
- `evolution spawn --role <role> --runtime <runtime>` — Spawn new agent
- `evolution stop` — End the session

### Analysis
- `evolution report` — Session summary
- `evolution timeline` — Agent timeline

## Behavior
- When the user connects, proactively report current status
- Translate natural language requests into CLI commands
- Summarize results conversationally
"""
```

```python
# evolution/superagent/agent.py
from __future__ import annotations

import subprocess
import logging
from pathlib import Path
from evolution.superagent.commands import build_superagent_instructions
from evolution.manager.config import SuperagentConfig

log = logging.getLogger(__name__)


def spawn_superagent(
    config: SuperagentConfig,
    session_name: str,
    worktree_path: Path,
) -> subprocess.Popen | None:
    """Spawn the superagent as a Claude Code instance."""
    if not config.enabled:
        return None

    # Write CLAUDE.md
    instructions = build_superagent_instructions(session_name)
    (worktree_path / "CLAUDE.md").write_text(instructions)

    log.info(f"Spawning superagent at {worktree_path}")
    return subprocess.Popen(
        ["claude", "--dangerously-skip-permissions"],
        cwd=str(worktree_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_superagent.py -v`
Expected: All PASS

---

### Task 14: Benchmark Tasks

**Files:**
- Create: `tasks/erdos_overlap/task.yaml`
- Create: `tasks/erdos_overlap/grader.py`
- Create: `tasks/erdos_overlap/seed/solver.py`
- Create: `tasks/kernel_engineering/task.yaml`
- Create: `tasks/kernel_engineering/grader.py`
- Create: `tasks/kernel_engineering/seed/kernel.py`
- Create: `tasks/openvaccine/task.yaml`
- Create: `tasks/openvaccine/grader.py`
- Create: `tasks/openvaccine/seed/model.py`

- [ ] **Step 1: Create Erdos Minimum Overlap task**

```yaml
# tasks/erdos_overlap/task.yaml
name: erdos-minimum-overlap
description: |
  Minimize the overlap constant C₅ for the Erdős Minimum Overlap Problem.
  Given n, find a permutation of {1,...,2n} that minimizes the maximum overlap
  across all subsets of size n.
metric:
  name: C5
  direction: lower_is_better
grader:
  type: hybrid
  script: ./grader.py
  llm_feedback: true
seed: ./seed/

milestones:
  baseline: 0.38111
  target: 0.38089
  stretch: 0.3808703

stop:
  max_time: 6h
  max_attempts: 200
  stagnation: 30m
  stagnation_action: shake_up
  shake_up_budget: 2
```

```python
# tasks/erdos_overlap/grader.py
#!/usr/bin/env python3
"""Grader for Erdos Minimum Overlap problem.
Imports solver.py and evaluates the overlap constant C5.
Prints score to stdout.
"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("solver", "solver.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

try:
    result = mod.compute_c5()
    print(f"{result}")
except Exception as e:
    print("999.0", file=sys.stdout)  # worst possible score
    print(f"Error: {e}", file=sys.stderr)
```

```python
# tasks/erdos_overlap/seed/solver.py
"""Erdos Minimum Overlap Problem — seed implementation.
Your goal: minimize the value returned by compute_c5().
"""


def compute_c5(n: int = 500) -> float:
    """Compute the overlap constant C5.
    This is a naive baseline — improve it!
    """
    # Naive: identity permutation gives worst-case overlap
    perm = list(range(1, 2 * n + 1))
    max_overlap = 0
    for k in range(1, n + 1):
        overlap = sum(1 for i in range(k) if perm[i] <= n)
        expected = k * n / (2 * n)
        diff = abs(overlap - expected)
        max_overlap = max(max_overlap, diff / n)
    return 0.5 + max_overlap  # baseline around 0.5
```

- [ ] **Step 2: Create Kernel Engineering task (placeholder)**

```yaml
# tasks/kernel_engineering/task.yaml
name: kernel-engineering
description: |
  Optimize GPU kernel implementation for minimum cycle count.
  Modify kernel.py to reduce the number of cycles.
metric:
  name: cycles
  direction: lower_is_better
grader:
  type: script
  script: ./grader.py
seed: ./seed/

milestones:
  baseline: 1363
  target: 1103

stop:
  max_time: 6h
  stagnation: 30m
```

```python
# tasks/kernel_engineering/grader.py
#!/usr/bin/env python3
"""Placeholder grader for kernel engineering task.
Replace with actual GPU cycle measurement.
"""
import importlib.util
spec = importlib.util.spec_from_file_location("kernel", "kernel.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.benchmark())
```

```python
# tasks/kernel_engineering/seed/kernel.py
"""GPU Kernel — seed implementation.
Your goal: minimize the cycle count returned by benchmark().
"""

def benchmark() -> int:
    """Simulate kernel cycle count. Replace with real GPU benchmark."""
    # Placeholder: simulate a baseline cycle count
    return 1363
```

- [ ] **Step 3: Create OpenVaccine task (placeholder)**

```yaml
# tasks/openvaccine/task.yaml
name: stanford-openvaccine
description: |
  Minimize MCRMSE on Stanford OpenVaccine RNA degradation prediction.
  Modify model.py to improve predictions.
metric:
  name: mcrmse
  direction: lower_is_better
grader:
  type: hybrid
  script: ./grader.py
  llm_feedback: true
seed: ./seed/

milestones:
  baseline: 0.34198

stop:
  max_time: 8h
  stagnation: 45m
```

```python
# tasks/openvaccine/grader.py
#!/usr/bin/env python3
"""Placeholder grader for OpenVaccine task."""
import importlib.util
spec = importlib.util.spec_from_file_location("model", "model.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.evaluate())
```

```python
# tasks/openvaccine/seed/model.py
"""OpenVaccine RNA degradation prediction — seed implementation.
Your goal: minimize the MCRMSE returned by evaluate().
"""

def evaluate() -> float:
    """Placeholder evaluation. Replace with real MCRMSE computation."""
    return 0.34198  # baseline human score
```

- [ ] **Step 4: Verify task files are valid YAML**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['tasks/erdos_overlap/task.yaml', 'tasks/kernel_engineering/task.yaml', 'tasks/openvaccine/task.yaml']]" && echo "All valid"`
Expected: "All valid"

---

### Task 15: Post-Session Analysis

**Files:**
- Create: `evolution/cli/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_report.py
import pytest
from pathlib import Path
from evolution.hub.attempts import AttemptsHub
from evolution.cli.report import format_report, export_csv


def test_format_report(tmp_path):
    hub = AttemptsHub(tmp_path / "attempts")
    hub.record(agent="a", score=0.5, description="first", commit="aaa", feedback="ok")
    hub.record(agent="b", score=0.3, description="second", commit="bbb", feedback="better")
    report = format_report(hub, direction="lower_is_better")
    assert "0.3" in report
    assert "agent" in report.lower()


def test_export_csv(tmp_path):
    hub = AttemptsHub(tmp_path / "attempts")
    hub.record(agent="a", score=0.5, description="first", commit="aaa", feedback="ok")
    hub.record(agent="b", score=0.3, description="second", commit="bbb", feedback="better")
    csv_path = tmp_path / "export.csv"
    export_csv(hub, str(csv_path))
    content = csv_path.read_text()
    assert "agent" in content
    assert "0.5" in content
    assert "0.3" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_report.py -v`
Expected: FAIL

- [ ] **Step 3: Implement report module**

```python
# evolution/cli/report.py
from __future__ import annotations

import csv
from io import StringIO
from evolution.hub.attempts import AttemptsHub


def format_report(hub: AttemptsHub, direction: str = "lower_is_better") -> str:
    """Generate a session summary report."""
    attempts = hub.list()
    board = hub.leaderboard(direction)
    best = board[0] if board else None

    lines = []
    lines.append("=" * 50)
    lines.append("EVOLUTION SESSION REPORT")
    lines.append("=" * 50)
    lines.append(f"Total attempts: {len(attempts)}")

    if best:
        lines.append(f"Best score: {best.score} by {best.agent} (attempt #{best.id})")

    # Per-agent summary
    agents = {}
    for a in attempts:
        if a.agent not in agents:
            agents[a.agent] = {"count": 0, "best": None}
        agents[a.agent]["count"] += 1
        if a.score is not None:
            if agents[a.agent]["best"] is None:
                agents[a.agent]["best"] = a.score
            elif direction == "lower_is_better":
                agents[a.agent]["best"] = min(agents[a.agent]["best"], a.score)
            else:
                agents[a.agent]["best"] = max(agents[a.agent]["best"], a.score)

    lines.append("")
    lines.append("Per-agent breakdown:")
    for name, info in agents.items():
        lines.append(f"  {name}: {info['count']} attempts, best={info['best']}")

    # Leaderboard
    lines.append("")
    lines.append("Leaderboard:")
    for i, a in enumerate(board[:10]):
        lines.append(f"  {i+1}. #{a.id:03d} {a.agent:<25} score={a.score}")

    return "\n".join(lines)


def export_csv(hub: AttemptsHub, output_path: str) -> None:
    """Export all attempts as CSV."""
    attempts = hub.list()
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "agent", "score", "timestamp", "commit"])
        for a in attempts:
            writer.writerow([a.id, a.agent, a.score, a.timestamp, a.commit])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/test_report.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/sayan/Projects/aadi-labs/evolution && uv run pytest tests/ -v`
Expected: All PASS

---

## Final Verification

After all tasks are complete:

- [ ] Run full test suite: `uv run pytest tests/ -v`
- [ ] Run linter: `uv run ruff check evolution/`
- [ ] Run type checker: `uv run mypy evolution/`
- [ ] Verify CLI entry point: `uv run evolution --help`
- [ ] Test simple end-to-end: `uv run evolution run --config tests/fixtures/simple_task/evolution.yaml`
