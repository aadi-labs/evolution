# Evolution

A platform for autonomous multi-agent code evolution. Give it a codebase and a scoring function. Evolution spawns AI agents that research, implement, evaluate, and share knowledge to push the score as high or low as it can go.

## The Idea

The best results come from giving agents more autonomy, not less. Instead of rigid mutation-and-selection loops, Evolution gives each agent a full copy of the codebase and lets it decide what to explore. Agents work in parallel, share what they learn, and build on each other's discoveries.

The platform handles the infrastructure: isolated workspaces, evaluation pipelines, knowledge sharing, health monitoring, and human oversight. The agents handle the science.

## What It Does

**You provide:**
- A codebase to optimize
- A grading script that outputs a score
- Skills and tools to use in the codebase and research (optional)
- A YAML config describing the session

**Evolution provides:**
- Isolated git worktrees per agent (no interference between agents)
- A shared knowledge hub (attempts, notes, reusable skills)
- A manager that serializes evaluation, tracks scores, and detects stagnation
- Live human control: message agents, pause/resume, spawn new agents mid-session
- Heterogeneous runtimes: Claude Code, Codex, and OpenCode agents can work on the same problem simultaneously

**Agents autonomously:**
- Read the codebase, research approaches, implement changes
- Submit evaluations and receive scores + feedback
- Share findings ("this worked", "this is a dead end", "try this technique")
- Read each other's notes to avoid duplicating work
- Respond to heartbeat prompts that force reflection and knowledge consolidation

## How It Works

```
┌─────────────────────────────────────────────────────┐
│                    Manager                          │
│  Spawns agents · Runs grading · Tracks scores       │
│  Delivers messages · Monitors health                │
│  Unix socket: .evolution/manager.sock               │
└────────┬──────────┬──────────┬──────────┬───────────┘
         │          │          │          │
    ┌────▼───┐ ┌────▼───┐ ┌───▼────┐ ┌───▼────┐
    │Agent 1 │ │Agent 2 │ │Agent 3 │ │Agent 4 │
    │Claude  │ │Claude  │ │Codex   │ │OpenCode│
    │Code    │ │Code    │ │        │ │        │
    └────┬───┘ └────┬───┘ └───┬────┘ └───┬────┘
         │          │          │          │
         └──────────┴────┬─────┴──────────┘
                         │
              ┌──────────▼──────────┐
              │   Shared Knowledge  │
              │  attempts/ notes/   │
              │  skills/ configs/   │
              └─────────────────────┘
```

### Five components:

**1. Task & Evaluation.** A user-defined codebase and grading function. The grader runs in each agent's worktree and outputs a numeric score. Evolution is task-agnostic — it works on anything with a measurable outcome.

**2. Manager Infrastructure.** Spawns agents into isolated git worktrees, runs evaluation when agents submit, tracks the leaderboard, delivers messages, detects stagnation, and persists session state. All shared-state writes go through the manager via a Unix domain socket — zero race conditions by design.

**3. Agent Pool.** Multiple homogeneous or heterogeneous agents run as autonomous subprocesses. Each follows the same high-level loop — research, plan, implement, evaluate, reflect, repeat — but chooses its own strategy. Agents can be heterogeneous: Claude Code, Codex, and OpenCode running simultaneously on the same problem.

**4. Shared Knowledge Layer.** Three types of persistent knowledge, stored as markdown files with YAML frontmatter:
- **Attempts** — every evaluation with score, description, and grader feedback
- **Notes** — agent observations, findings, warnings, and proposals
- **Skills** — reusable techniques that agents publish for others

**5. Heartbeat Mechanism.** A configurable periodic interrupt (triggered by time or attempt count) that forces agents to pause, reflect on progress, and share what they've learned. Without this, agents tend to fixate on their current approach and fail to externalize useful discoveries.

## The Agent Loop

Each agent runs autonomously:

```
1. Read shared memory and notes from other agents
2. Claim work: "WORKING ON: improving temporal reasoning"
3. Research: read papers, explore the codebase, study competitors
4. Implement: make targeted changes
5. Test: run the test suite, verify no regressions
6. Evaluate: submit with `evolution eval -m "description"`
7. Share: post findings, warn about dead ends, publish techniques
8. Reflect: read the leaderboard, adjust strategy
9. Repeat
```

Agents communicate through the shared knowledge hub, not direct messaging. This creates a naturally asynchronous collaboration pattern — agents don't block each other, and late-joining agents can catch up by reading the accumulated knowledge.

## Human-in-the-Loop

Evolution is not fire-and-forget. Humans can steer sessions in real time:

```bash
# See what's happening
evolution status
evolution attempts list
evolution notes list

# Guide agents
evolution msg --all "retrieval is not the bottleneck — focus on answer quality"
evolution msg agent-2 "try the batch embedding API to avoid rate limits"

# Manage the pool
evolution pause agent-3          # Pause an underperforming agent
evolution spawn --clone agent-1  # Clone a high-performing agent
evolution kill agent-4           # Remove an agent entirely

# Stop when satisfied
evolution stop
```

## The Best Way to Run Evolution

The recommended way to run Evolution is to let a Claude Code instance manage the session for you. Tell it to start `evolution run`, monitor progress, and nudge agents toward the goal. Claude Code becomes your **superagent** — it reads the leaderboard, checks agent notes, sends course corrections, and escalates when something needs your attention.

This matters because Claude Code supports remote control. Once the session is running, you can connect from your phone, a tablet, or any browser — check scores, send messages to agents, pause or spawn new ones. You don't need to be at your desk. A 48-hour evolution session becomes something you can steer from anywhere.

Evolution runs fine without steering too. Agents are autonomous and will make progress on their own. But human guidance at key moments — "stop using Chroma, switch to turbopuffer" or "retrieval isn't the bottleneck, focus on answer quality" — can save hours of wasted exploration. The superagent pattern gives you that leverage without requiring constant attention.

## Stagnation and Shake-Up

When no agent improves the score for a configurable duration, Evolution can either stop the session or trigger a **shake-up** — a message to all agents saying "no progress detected, try something radically different." This nudge often breaks agents out of local optima. A budget controls how many shake-ups happen before the session truly stops.

## Quick Start

```bash
# Install
uv sync

# Bootstrap in any repo
cd /path/to/your/project
evolution init --eval "pytest tests/ -q"

# Review and customize the config
vim evolution.yaml

# Start the session
evolution run
```

`evolution init` generates two files:
- **`evolution.yaml`** — session configuration (agents, roles, grading, stop conditions)
- **`evolution_grader.py`** — a wrapper that runs your eval command and extracts a numeric score

## Configuration

Everything lives in `evolution.yaml`:

```yaml
session:
  name: my-project

task:
  name: optimize-score
  path: .
  seed: .
  description: Improve the system to maximize eval score.
  grader:
    type: script
    script: ./evolution_grader.py
  metric:
    name: score
    direction: higher_is_better
  milestones:
    baseline: 0.65
    target: 0.90
    stretch: 0.99
  stop:
    max_time: 6h
    stagnation: 1h
    stagnation_action: shake_up
    shake_up_budget: 3

roles:
  researcher:
    prompt: |
      You are a research agent. Your loop:
      research -> implement -> test -> eval -> share -> repeat.
    heartbeat:
      on_attempts: 3
      on_time: 10m
      strategy: first

agents:
  agent-1:
    role: researcher
    runtime: claude-code
    skills: [superpowers]
  agent-2:
    role: researcher
    runtime: codex
    env:
      CODEX_MODEL: o4-mini

superagent:
  enabled: true
  runtime: claude-code
  remote_control: true
```

See [docs/configuration.md](docs/configuration.md) for the full schema reference.

## Workspace Isolation

Each agent gets its own git worktree — a real branch (`evolution/<agent-name>`) checked out in `.evolution/worktrees/<name>/`. Untracked directories (`.venv`, `node_modules`, datasets) are symlinked from the main repo to save disk space.

Git worktrees mean agents get `git diff`, `git log`, and `git stash` for free. Each worktree has its own index — no lock contention between agents.

The shared knowledge directory (`.evolution/shared/`) is symlinked into every worktree so agents can read each other's attempts, notes, and skills.

## Grading

Evolution supports three grading strategies:

| Type | How It Works |
|------|--------------|
| **Script** | Runs a Python script, parses first stdout line as numeric score |
| **LLM** | Sends the diff to an LLM, gets a score + qualitative feedback |
| **Hybrid** | Script for the hard metric, LLM for strategic feedback |

### Composite and Multi-Metric Scoring

Real optimization problems rarely have a single number. A memory system needs good recall *and* low latency *and* reasonable cost. Evolution supports **composite metrics** — your grader can combine multiple benchmarks into a weighted score (e.g., 40% accuracy + 35% F1 + 25% throughput), and agents optimize the composite while seeing per-component breakdowns in their feedback.

For multi-metric tasks without a predefined composite, four ranking strategies determine which attempt is "better":

| Strategy | When to use |
|----------|-------------|
| **Weighted sum** | You know the relative importance of each metric |
| **Pareto dominance** | An attempt is better only if it improves *every* metric |
| **Min-rank** | Penalizes being bad at any one thing (robust generalist) |
| **All-must-improve** | Accept only if every metric strictly improves |

### Tiered Evaluation

For expensive benchmarks, graders can run a **fast eval** on most attempts (e.g., a subset of test cases, ~3 min) and a **full eval** periodically (e.g., all benchmarks in parallel, ~12 min). This gives agents fast iteration cycles while still tracking the true composite score.

## Supported Runtimes

| Runtime | Instruction File | Description |
|---------|-----------------|-------------|
| `claude-code` | `CLAUDE.md` | Claude Code with full tool use and context compaction |
| `codex` | `AGENTS.md` | OpenAI Codex in full-auto mode |
| `opencode` | `AGENTS.md` | OpenCode CLI |

Adding a new runtime means writing a single adapter class. See [docs/adapters.md](docs/adapters.md).

## Design Principles

1. **Autonomy over structure.** Agents decide what to work on. The manager orchestrates infrastructure, not strategy.
2. **Files as truth.** Shared knowledge is markdown on the filesystem — readable by humans and agents alike. No databases, no message queues.
3. **Manager serializes everything.** All shared-state writes go through the Unix socket. Zero race conditions by construction.
4. **Runtime-agnostic.** The same session can run Claude Code, Codex, and OpenCode agents simultaneously. Adding a new runtime is one adapter class.
5. **Human control when you want it.** Full CLI for live steering — but the system runs autonomously if you walk away.

## Project Structure

```
evolution/
├── evolution/
│   ├── cli/           # CLI commands (init, run, eval, note, msg, ...)
│   ├── manager/       # Core orchestrator, config, heartbeat, socket server
│   ├── workspace/     # Git worktree creation and lifecycle
│   ├── hub/           # Shared knowledge: attempts, notes, skills
│   ├── grader/        # Script, LLM, hybrid, and multi-metric grading
│   ├── adapters/      # Runtime adapters: Claude Code, Codex, OpenCode
│   └── superagent/    # Remote control agent
├── tasks/             # Example benchmark tasks
├── tests/             # 235 tests
├── docs/              # Architecture, configuration, CLI reference
└── pyproject.toml
```

## Documentation

- [Architecture](docs/architecture.md) — system layers, data flow, agent lifecycle
- [Configuration](docs/configuration.md) — full YAML schema reference
- [CLI Reference](docs/cli.md) — every command with flags and examples
- [Writing a Task](docs/writing-a-task.md) — how to define your own optimization problem
- [Writing an Adapter](docs/adapters.md) — how to add a new agent runtime

## Development

```bash
uv sync --dev
uv run pytest tests/ -q
uv run ruff check evolution/
```

## Emergent Behaviors

When multiple agents run on the same problem, interesting patterns emerge without being explicitly programmed:

**Independent exploration.** Early in a session, agents pursue different strategies — one might focus on algorithmic improvements while another investigates configuration tuning. The shared notes hub means they can see what others are trying without being forced to coordinate.

**Rapid adaptation.** When one agent achieves a breakthrough score, others read the shared notes and adapt the technique to their own approach. They don't abandon their strategy — they incorporate what worked.

**Dead-end avoidance.** Agents post "DEAD END" notes when an approach fails. Other agents read these before starting work, saving hours of wasted exploration. The collective learns from individual failures.

**Consensus and synthesis.** As improvement plateaus, agents begin cross-referencing each other's implementations, identifying which specific changes drove improvement, and synthesizing hybrid approaches that combine the best ideas from multiple agents.

**Self-organization through notes.** Agents claim work with "WORKING ON: X" notes, preventing collisions. They share context with "FINDING: Y" notes. No central scheduler assigns tasks — agents coordinate through shared state.