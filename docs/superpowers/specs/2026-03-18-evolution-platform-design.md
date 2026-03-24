# Evolution: Multi-Agent Research & Code Evolution Platform

**Date:** 2026-03-18
**Status:** Design approved, pending implementation plan

## Overview

Evolution is a task-agnostic platform where multiple heterogeneous AI agents (Claude Code, Codex, OpenCode) collaborate to optimize code against user-defined grading functions. Agents run as autonomous subprocesses in isolated git worktrees, sharing knowledge through a common filesystem and CLI protocol.

Inspired by [CORAL](https://human-agent-society.github.io/CORAL/) and [AutoResearch](https://github.com/karpathy/autoresearch), but with three key differentiators:

1. **Heterogeneous agents** — different AI runtimes (Claude Code, Codex, OpenCode) work on the same problem simultaneously, configured via YAML
2. **Remote control via superagent** — a Claude Code instance acts as a conversational interface, piggybacking on Claude Code's remote session capabilities
3. **Pluggable task system** — task-agnostic with support for single-metric and multi-metric evaluation

## Design Principles

- **Readable, understandable code** — optimize for clarity over cleverness
- **Use popular libraries** — avoid custom abstractions when a well-known library handles it
- **Files as truth, CLI as ergonomics** — shared knowledge lives on the filesystem; CLI commands are convenience wrappers
- **Manager as serializer** — agents never write to shared state directly; all writes go through the manager via CLI commands, eliminating race conditions
- **Loose coupling** — the manager watches the filesystem and delivers messages via inbox files; agents are autonomous
- **Agents are trusted** — agents run on the user's own machine with full access; no sandboxing (out of scope for v1)

## Tech Stack

- **Language:** Python 3.11+
- **Package manager:** uv
- **Config validation:** pydantic
- **YAML parsing:** pyyaml
- **LLM grader:** openrouter (Python SDK)
- **Everything else:** stdlib (subprocess, argparse, logging, pathlib, json, socket)

## Project Structure

```
evolution/
├── evolution/
│   ├── __init__.py
│   ├── cli/                    # CLI entry points
│   │   ├── __init__.py
│   │   ├── main.py             # `evolution` command router
│   │   ├── run.py              # `evolution run` — start a session
│   │   ├── eval.py             # `evolution eval` — agents submit attempts
│   │   ├── note.py             # `evolution note` — agents share knowledge
│   │   ├── skill.py            # `evolution skill` — agents publish reusable tools
│   │   ├── status.py           # `evolution status` — query system state
│   │   ├── msg.py              # `evolution msg` — user interjection
│   │   ├── benchmark.py        # `evolution benchmark` — run validation tasks
│   │   └── superagent.py       # `evolution superagent` — start remote control agent
│   ├── manager/                # Agent lifecycle & orchestration
│   │   ├── __init__.py
│   │   ├── manager.py          # Core manager — spawn, monitor, heartbeat
│   │   ├── runtime.py          # Agent subprocess management
│   │   ├── heartbeat.py        # Heartbeat scheduler (time + attempt hybrid)
│   │   └── config.py           # YAML config parser & validator
│   ├── workspace/              # Git worktree isolation
│   │   ├── __init__.py
│   │   └── setup.py            # Worktree creation, teardown, symlinks
│   ├── hub/                    # Shared knowledge layer
│   │   ├── __init__.py
│   │   ├── attempts.py         # Attempt tracking, leaderboard, history
│   │   ├── notes.py            # Agent notes & observations
│   │   └── skills.py           # Reusable tools & techniques
│   ├── grader/                 # Evaluation system
│   │   ├── __init__.py
│   │   ├── protocol.py         # Grader interface definition
│   │   ├── script.py           # Script-based grader
│   │   ├── llm.py              # LLM-as-judge grader
│   │   └── hybrid.py           # Script + LLM hybrid grader
│   ├── superagent/             # Remote control via Claude Code
│   │   ├── __init__.py
│   │   ├── agent.py            # Superagent logic
│   │   └── commands.py         # Command handlers (status, pause, spawn, etc.)
│   └── adapters/               # Agent runtime adapters
│       ├── __init__.py
│       ├── base.py             # Base adapter interface
│       ├── claude_code.py      # Claude Code adapter
│       ├── codex.py            # Codex adapter
│       └── opencode.py         # OpenCode adapter
├── tasks/                      # Benchmark tasks (CORAL-compatible)
│   ├── erdos_overlap/
│   │   ├── task.yaml
│   │   ├── grader.py
│   │   └── seed/
│   ├── kernel_engineering/
│   │   ├── task.yaml
│   │   ├── grader.py
│   │   └── seed/
│   └── openvaccine/
│       ├── task.yaml
│       ├── grader.py
│       └── seed/
├── pyproject.toml
└── evolution.yaml              # Top-level session config
```

## YAML Configuration

### Roles and Agents

Roles define research personality (prompt, heartbeat). Agents bind a role to a runtime with its tooling.

```yaml
session:
  name: "erdos-overlap-run-1"

task:
  name: "erdos-minimum-overlap"
  path: ./tasks/erdos_overlap
  description: "Minimize the overlap constant C₅"

roles:
  researcher:
    prompt: |
      You are a research agent working on the Erdos Minimum Overlap problem.
      Focus on mathematical insights and novel algorithmic approaches.
    heartbeat:
      on_attempts: 3
      on_time: 10m
      strategy: first

  optimizer:
    prompt: |
      You are an optimization agent. Focus on implementation efficiency
      and micro-optimizations to the current best solution.
    heartbeat:
      on_attempts: 5
      on_time: 15m
      strategy: first

  explorer:
    prompt: |
      You are an exploration agent. Try unconventional approaches
      and search for insights in the shared notes.
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
      - alphaxiv-paper-lookup
    plugins:
      - huggingface-skills
    mcp_servers:
      - huggingface

  codex-researcher:
    role: researcher
    runtime: codex
    env:
      CODEX_MODEL: o3-pro

  opencode-researcher:
    role: researcher
    runtime: opencode
    env:
      OPENCODE_MODEL: o3-pro

  claude-optimizer:
    role: optimizer
    runtime: claude-code
    skills:
      - superpowers

  codex-explorer:
    role: explorer
    runtime: codex
    env:
      CODEX_MODEL: o3-pro

superagent:
  enabled: true
  runtime: claude-code
  remote_control: true
  skills:
    - superpowers
  prompt: |
    You are the superagent for this evolution session.
    You have access to all `evolution` CLI commands.
    When the user connects remotely, report status proactively
    and await instructions.
```

### Single-Metric Task

```yaml
# tasks/erdos_overlap/task.yaml
name: erdos-minimum-overlap
description: "Minimize the overlap constant C₅ for the Erdős Minimum Overlap Problem"
metric:
  name: C5
  direction: lower_is_better
grader:
  type: hybrid
  script: ./grader.py
  llm_feedback: true
seed: ./seed/

milestones:
  baseline: 0.38111     # OpenEvolve — "we're in the game"
  target: 0.38089       # CORAL — "we matched them"
  stretch: 0.3808703    # CORAL + web search — "we beat them"

stop:
  max_time: 6h
  max_attempts: 200
  stagnation: 30m
  manual: true
```

### Multi-Metric Task

```yaml
# tasks/memory_system/task.yaml
name: memory-system
description: "Build a memory system that excels across multiple benchmarks"
seed: ./seed/

metrics:
  locomo:
    grader: ./graders/locomo.py
    direction: higher_is_better
    weight: 0.4
    milestones:
      baseline: 72.5
      target: 85.0
      stretch: 90.0

  longmemeval_s:
    grader: ./graders/longmemeval_s.py
    direction: higher_is_better
    weight: 0.35
    milestones:
      baseline: 68.0
      target: 80.0
      stretch: 88.0

  custom_recall:
    grader: ./graders/recall.py
    direction: higher_is_better
    weight: 0.25
    milestones:
      baseline: 0.70
      target: 0.90
      stretch: 0.95

ranking:
  strategy: weighted_sum  # or: pareto, min_rank, all_must_improve
  normalize: true

stop:
  max_time: 8h
  stagnation: 45m
  milestone_stop: all_targets
```

## Agent Lifecycle

### Startup Sequence

```
evolution run
  │
  ├─ 1. Parse evolution.yaml — merge role defaults + agent overrides
  │
  ├─ 2. Create worktrees
  │     git worktree add .evolution/worktrees/<agent-name>
  │
  ├─ 3. Provision shared knowledge
  │     mkdir .evolution/shared/{attempts,notes,skills}
  │     Symlink .evolution/shared/ into each worktree
  │
  ├─ 4. Provision agent tooling (via adapter)
  │     Claude Code → write .claude/settings.json with skills, plugins, MCP servers
  │     Codex       → write config with env vars, model
  │     OpenCode    → write config with env vars, model
  │
  ├─ 5. Write instruction file (via adapter)
  │     Claude Code → CLAUDE.md (role prompt + task + CLI protocol)
  │     Codex       → AGENTS.md
  │     OpenCode    → AGENTS.md
  │
  ├─ 6. Spawn agent subprocesses
  │
  └─ 7. Start manager loop
        ├─ Monitor agent health (process alive?)
        ├─ Process eval/note/skill requests via Unix socket
        ├─ Trigger heartbeats (time or attempt, whichever first)
        ├─ Watch for user interjections (.evolution/inbox/)
        ├─ Update leaderboard
        └─ Broadcast milestone notifications
```

### Workspace Layout

```
.evolution/worktrees/claude-researcher/
├── <task seed code>
├── CLAUDE.md                     # instruction file (runtime-specific name)
├── .claude/settings.json         # provisioned skills, plugins, MCP servers
└── .evolution/shared/ → symlink
    ├── attempts/
    │   ├── 001-claude-researcher-score-0.3812.md
    │   └── 002-codex-researcher-score-0.3810.md
    ├── notes/
    │   └── claude-researcher-insight-1.md
    └── skills/
        └── binary-search-optimization.md
```

### Adapter Pattern

Each adapter encapsulates runtime-specific details behind a common interface:

```python
class AgentAdapter:
    """Base interface — each runtime implements this."""
    name: str                      # "claude-code", "codex", "opencode"
    instruction_file: str          # "CLAUDE.md" or "AGENTS.md"

    def provision(self, worktree_path, agent_config): ...
    def write_instructions(self, worktree_path, prompt): ...
    def spawn(self, worktree_path, agent_config) -> subprocess.Popen: ...
    def deliver_message(self, worktree_path, agent_name, message): ...
```

### Message Delivery

Messages (heartbeats, user interjections, milestone notifications) are delivered via **inbox files**, not stdin injection. Each agent has an inbox directory that it polls:

```
.evolution/worktrees/<agent-name>/.evolution/inbox/
├── 001-heartbeat.md
├── 002-user-message.md
└── 003-milestone.md
```

The instruction file (CLAUDE.md / AGENTS.md) tells agents to check their inbox:
- **Before starting each new approach**
- **After each eval submission** (the eval response also includes any pending inbox messages as a piggyback, so agents always get messages when they eval)

This is reliable across all runtimes — every agent can read files, regardless of whether stdin injection works for that runtime.

The adapter's `deliver_message` method writes to the inbox directory. The manager calls this method for heartbeats, interjections, and milestones.

### Agent Crash Recovery

```yaml
# Per-agent restart policy (optional, defaults shown)
agents:
  claude-researcher:
    role: researcher
    runtime: claude-code
    restart:
      enabled: true          # auto-restart on crash
      max_restarts: 3        # give up after 3 crashes
      backoff: exponential   # 10s, 20s, 40s between restarts
      preserve_worktree: true # keep worktree state on restart
```

When an agent crashes:
1. Manager detects process exit
2. If `restart.enabled` and under `max_restarts`: wait (backoff), re-spawn in same worktree
3. If over `max_restarts`: mark agent as dead, notify superagent
4. Worktree is preserved by default — agent resumes where it left off

### Manager Recovery

The manager writes its state to `.evolution/state.json` on every state change. If the manager crashes and is restarted (`evolution run --resume`), it reads this file to reconstruct agent states, attempt counts, and heartbeat timers.

## Shared Knowledge Layer

### File Formats

**Attempt:**
```markdown
---
id: 7
agent: claude-researcher
score: 0.38091
previous_best: 0.38095
improvement: true
timestamp: 2026-03-18T14:23:01Z
commit: a1b2c3d
---

## Description
Switched to simulated annealing with adaptive cooling schedule.

## Grader Feedback
**Script score:** 0.38091 (improvement over 0.38095)
**LLM feedback:** Consider combining with the binary search optimization skill.

## Diff Summary
Modified solver.py: replaced greedy search with simulated annealing (±47 lines)
```

**Note:**
```markdown
---
agent: claude-researcher
timestamp: 2026-03-18T14:30:00Z
tags: [insight, cooling-schedule, dead-end]
---

Tried exponential cooling schedules with rates 0.99, 0.95, 0.90.
All performed worse than adaptive cooling. The problem landscape has
many local minima — aggressive cooling gets trapped.

Recommendation: future attempts should use adaptive or restart-based cooling.
```

**Skill:**
```markdown
---
author: codex-researcher
timestamp: 2026-03-18T13:45:00Z
tags: [optimization, search]
---

## Binary Search on Overlap Bounds

When evaluating candidate permutations, binary search on the overlap bound
before computing the full overlap. Reduces evaluation time by ~40%.
```

### CLI Commands

```bash
# Agents submit work
evolution eval -m "description of what I changed"

# Agents share knowledge (routed through manager, same as eval)
evolution note add "insight text"
evolution note add --tags "dead-end,cooling" "text"
evolution skill add skill-name.md

# Agents read knowledge
evolution attempts list
evolution attempts show 7
evolution notes list
evolution notes list --agent codex-researcher
evolution skills list

# System status
evolution status
evolution status --agent claude-researcher
```

## User Interjection

```bash
# Message a specific agent
evolution msg claude-researcher "Try the Mian-Chowla sequence approach"

# Broadcast to all agents
evolution msg --all "Focus on score < 0.3809"

# Message by role
evolution msg --role researcher "Pivot to constructive methods"

# Agent control (pause = block evals + inbox message to stop; resume = unblock + inbox message)
evolution pause codex-researcher
evolution resume codex-researcher
evolution spawn --agent opencode-optimizer
evolution kill opencode-researcher
evolution stop                              # end the session
```

The `evolution msg` command writes to `.evolution/inbox/<agent-name>/<timestamp>.md` via the manager. The agent sees it on its next inbox check:

```markdown
## Message from User

Try looking at the Mian-Chowla sequence approach.
Prioritize this over your current work.
```

## Superagent (Remote Control)

The superagent is a Claude Code instance with full access to the `evolution` CLI. It piggybacks on Claude Code's built-in remote session capabilities — no custom dashboard or API needed.

```
Phone → Claude Code remote session → superagent with evolution CLI access
```

Natural language maps to CLI commands:

| User says | Superagent runs |
|---|---|
| "how's it going?" | `evolution status` + `evolution attempts list` |
| "tell researchers to try constructive methods" | `evolution msg --role researcher "..."` |
| "kill the opencode agent" | `evolution kill opencode-researcher` |
| "spin up another claude researcher" | `evolution spawn --agent claude-researcher-2` |

## Heartbeat System

Configurable per-role, hybrid time + attempt triggers (whichever fires first):

```yaml
heartbeat:
  on_attempts: 3    # after every 3 eval submissions
  on_time: 10m      # or every 10 minutes
  strategy: first   # whichever triggers first
```

When a heartbeat fires, the manager injects:

```markdown
## Heartbeat — Time to Reflect

You've been working for 10 minutes. Before continuing:

1. Check the leaderboard: `evolution attempts list`
2. Read recent notes: `evolution notes list --since 10m`
3. Current best score: 0.38091 by claude-researcher (attempt #7)
4. Your best score: 0.38095 (attempt #4)

Consider:
- Is your current approach still promising?
- Can you build on anyone else's insights?
- Write a note about what you've learned so far.
```

## Grading System

Three built-in grader types implementing a common protocol:

```python
class Grader:
    """Input: attempt directory. Output: score + feedback."""
    def grade(self, attempt_path: str) -> GradeResult: ...

@dataclass
class GradeResult:
    score: float
    feedback: str
    metrics: dict[str, float]   # for multi-metric tasks
```

| Type | How it works |
|---|---|
| `script` | Runs a user-provided script, parses numeric score from stdout |
| `llm` | Sends diff + task description to an LLM, gets score + qualitative feedback |
| `hybrid` | Script provides hard metric, LLM provides strategic feedback |

### Multi-Metric Evaluation

For multi-metric tasks, the eval command runs all graders and produces a table:

```
┌─────────────────┬─────────┬───────────┬────────────┐
│ Metric          │ Score   │ Previous  │ Milestone  │
├─────────────────┼─────────┼───────────┼────────────┤
│ locomo          │ 83.2    │ 81.0  ▲   │ target: 85 │
│ longmemeval_s   │ 79.5    │ 80.1  ▼   │ target: 80 │
│ custom_recall   │ 0.88    │ 0.85  ▲   │ target: 0.90 │
├─────────────────┼─────────┼───────────┼────────────┤
│ composite       │ 0.847   │ 0.831 ▲   │            │
└─────────────────┴─────────┴───────────┴────────────┘
```

### Ranking Strategies

| Strategy | Definition | Example |
|---|---|---|
| `weighted_sum` | Normalize each metric to 0-1, multiply by weight, sum. Single composite score. | locomo=83.2 (w=0.4) + longmemeval=79.5 (w=0.35) + recall=0.88 (w=0.25) → 0.847 |
| `pareto` | Attempt A beats B only if A is better on ALL metrics. Non-dominated attempts form the Pareto frontier. Frontier attempts are ranked by composite score. | A(83,80,0.88) dominates B(82,79,0.87) but not C(84,78,0.90) — C is also on the frontier. |
| `min_rank` | Rank each attempt per-metric (1=best), take the worst (highest) rank across metrics. Lowest worst-rank wins. Penalizes being bad at any one metric. | A ranks [2,1,3] → worst=3. B ranks [1,3,1] → worst=3. Tie broken by composite. |
| `all_must_improve` | Accept an attempt only if it improves every metric vs. the current best per-metric. Rejects attempts that trade off one metric for another. | Current best: locomo=83, longmem=80, recall=0.88. New: (84,79,0.89) → REJECTED (longmem regressed). |

## Milestone System

Milestones are tracking markers, not stop conditions. When hit, the manager broadcasts to all agents:

```markdown
## Milestone Reached: target

Score 0.38087 by claude-researcher (attempt #42) beats CORAL's 0.38089.
Session continues — push for stretch goal (0.3808703) and beyond.
Time remaining: 3h 14m.
```

Evolution continues until a hard stop condition is met (max_time, max_attempts, stagnation, or manual stop).

### Stagnation

Stagnation means **no improvement to the global best score for N minutes**. For multi-metric tasks, stagnation means no improvement to the composite score. The stagnation timer resets whenever any attempt improves the best score.

When stagnation is detected, the manager can optionally inject a "shake-up" prompt before stopping:

```yaml
stop:
  stagnation: 30m
  stagnation_action: shake_up  # or: stop (default)
  shake_up_budget: 2           # try shake-up N times before hard stop
```

Shake-up prompt tells all agents: "No improvement for 30 minutes. Try a radically different approach — abandon your current line of work."

## Benchmark Validation

Three tasks ported from CORAL to validate the platform:

### Erdos Minimum Overlap

| Benchmark | Score | Our Target |
|---|---|---|
| OpenEvolve | C₅ = 0.38111 | Must beat |
| CORAL | C₅ = 0.38089 | Match or beat |
| CORAL + web search | C₅ = 0.3808703 | Stretch goal |

### Anthropic Kernel Engineering

| Benchmark | Score | Our Target |
|---|---|---|
| Previous SOTA | 1,363 cycles | Must beat |
| CORAL single-agent | 1,350 cycles | Match or beat |
| CORAL multi-agent (4) | 1,103 cycles | Match or beat |

### Stanford OpenVaccine

| Benchmark | Score | Our Target |
|---|---|---|
| Top human score | 0.34198 MCRMSE | Must beat |
| CORAL | 20.5% improvement over human | Match or beat |

```bash
# Run a specific benchmark with its pre-defined agent config
evolution run --config tasks/erdos_overlap/benchmark.yaml

# Run all three benchmarks sequentially, each with default configs
evolution benchmark --all

# Compare your results against CORAL's published scores
# (reads from tasks/<task>/task.yaml milestones)
evolution benchmark --compare coral
```

## Key Libraries

| Purpose | Library | Why |
|---|---|---|
| Config validation | pydantic | Catches config errors early, typed models |
| YAML | pyyaml | Only YAML lib needed, CORAL-proven |
| LLM grader | openrouter | Multi-model access via single SDK |
| CLI | argparse (stdlib) | Zero dependencies, good enough |
| Git | subprocess → `git` CLI | Simpler than gitpython, fewer bugs, CORAL-proven |
| Process mgmt | subprocess (stdlib) | No extra dependency needed |
| Logging | logging (stdlib) | No extra dependency needed |
| Terminal output | print (stdlib) | No extra dependency needed |

## `evolution eval` Workflow

The most critical command — how agents submit work for grading:

```
Agent runs: evolution eval -m "Switched to simulated annealing"
  │
  ├─ 1. CLI sends request to manager via Unix domain socket (.evolution/manager.sock)
  │     Manager serializes all eval/note/skill requests — no concurrent write races
  │
  ├─ 2. Manager commits current worktree state
  │     git add -A && git commit in the agent's worktree
  │     Commit message = the -m description
  │
  ├─ 3. Manager runs grader(s) against the committed worktree
  │     - Single-metric: run one grader script, get score
  │     - Multi-metric: run all grader scripts, compute composite
  │     - Hybrid: run script grader, then LLM grader on the diff
  │     - If grader fails (script error, LLM timeout): score = None,
  │       feedback = error message, attempt still recorded as failed
  │
  ├─ 4. Manager writes attempt record to .evolution/shared/attempts/
  │     Assigns monotonic attempt ID (manager is sole writer, no races)
  │
  ├─ 5. Manager updates leaderboard
  │     Checks milestones, broadcasts if newly reached
  │
  └─ 6. Manager returns result to agent's stdout
        Score + feedback printed, agent continues
```

Grading is **synchronous from the agent's perspective** — the agent blocks until the result comes back. This keeps the protocol simple: submit, wait, read result, decide next move.

## `evolution spawn` Command

Spawn creates new agent instances mid-session:

```bash
# Clone an existing agent config with auto-suffixed name
evolution spawn --clone claude-researcher
# → creates claude-researcher-2 with identical config

# Create from role + runtime inline
evolution spawn --role researcher --runtime codex --env CODEX_MODEL=o3-pro
# → creates codex-researcher-2 (auto-named from role + runtime)
```

Cloned agents get a fresh worktree with the current best attempt's code as seed, not the original seed code. This lets new agents start from the best known solution.

## Observability

### Logging

All logs go to `.evolution/logs/`:

```
.evolution/logs/
├── manager.log                    # manager lifecycle, heartbeats, milestones
├── agents/
│   ├── claude-researcher.log      # agent stdout/stderr capture
│   ├── codex-researcher.log
│   └── opencode-researcher.log
└── grader.log                     # all grading results and errors
```

Logs use stdlib `logging` with JSON formatting for machine parsing and plain text for human reading. Log level configurable via `evolution.yaml`:

```yaml
session:
  log_level: info   # debug, info, warning, error
```

### Post-Session Analysis

```bash
# Session summary — agents, attempts, best scores, time spent
evolution report

# Export all attempts as CSV for analysis
evolution export --format csv

# View agent timeline — what each agent did and when
evolution timeline
```

## Stop Condition Precedence

Task-level `stop` config is the source of truth. Session-level only defines `name` and `log_level`. If a task doesn't define `stop`, defaults apply:

| Condition | Default |
|---|---|
| `max_time` | 6h |
| `max_attempts` | unlimited |
| `stagnation` | 1h |
| `manual` | true (always available via `evolution stop`) |
