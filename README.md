# Evolution

A platform for autonomous multi-agent code evolution. Give it a codebase and a scoring function. Evolution spawns AI agents that research, implement, evaluate, and share knowledge to push the score as high or low as it can go.

## Why Evolution

Most multi-agent systems are either too simple or too rigid. A single agent editing one file in a loop can't handle real codebases. A fixed mutation-and-selection pipeline can't adapt when the problem requires research, hypothesis testing, or coordinated exploration. And systems that treat agents as independent optimizers waste cycles. Agents diverge into separate lineages, most of them improving fundamentally worse code.

Evolution is different in a few ways that matter:

- **Collective intelligence, not independent optimization.** Agents share a structured knowledge graph (not just notes, but hypotheses with evidence tracking, reusable skills, and tagged observations). The collective learns from individual failures. Dead ends posted by one agent save hours for others.
- **Periodic convergence to the best-known baseline.** Heartbeat-triggered convergence rebases all agents to the highest-scoring code at regular intervals. Agents explore freely between convergence points, but the population never drifts too far from what's actually working.
- **Metacognitive self-improvement through reflection.** Agents don't just optimize the code; they improve how they optimize. Heartbeat prompts force reflection on what's working. Published skills change future agent behavior. The improvement process improves itself, expressed through natural language rather than source-code edits.
- **Multi-metric and composite scoring.** Real problems have trade-offs. Evolution supports weighted sums, Pareto dominance, min-rank, and all-must-improve ranking. Agents see per-component breakdowns, not just a single scalar.
- **Research phases before implementation.** Sessions can block eval submissions during an initial exploration phase, forcing agents to study the problem, read papers, and share findings before anyone starts coding.
- **Human steering without hand-holding.** Live message injection, agent pause/resume/spawn/kill, and a superagent pattern for remote monitoring. The system runs autonomously but is built for human guidance at key moments.
- **Heterogeneous runtimes.** Claude Code, Codex, and OpenCode agents work the same problem simultaneously. Runtime-specific options (permission modes, model settings) are configurable per-agent without polluting the shared schema.
- **Full-codebase, not single-file.** Agents get a complete copy of the repo with shared dependencies (symlinked venvs at zero disk cost), not a sandboxed single file. They can modify anything, run the full test suite, and use any tool available in the project.

## What It Does

**You provide:**

- A codebase to optimize
- A grading script that outputs a score
- Skills and tools to use in the codebase and research (optional)
- A YAML config describing the session

**Evolution provides:**

- Isolated git worktrees per agent (no interference between agents)
- A shared knowledge hub (attempts, notes, reusable skills, hypotheses)
- A manager that serializes evaluation, tracks scores, and detects stagnation
- Periodic convergence: all agents rebase to the best-scoring code
- Live human control: message agents, pause/resume, spawn new agents mid-session
- Heterogeneous runtimes: Claude Code, Codex, and OpenCode agents can work on the same problem simultaneously
- Multi-metric ranking: weighted sum, Pareto, min-rank, all-must-improve
- Research phases that block eval during exploration
- Session chaining for multi-day research

**Agents autonomously:**

- Read the codebase, research approaches, implement changes
- Submit evaluations and receive scores + feedback
- Share findings ("this worked", "this is a dead end", "try this technique")
- Read each other's notes to avoid duplicating work
- Diff and cherry-pick files from each other's worktrees
- Track and test hypotheses with structured evidence
- Reflect during heartbeats, publish reusable skills, adjust strategy

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
         │          │         │          │
         └──────────┴────┬────┴──────────┘
                         │
              ┌──────────▼──────────┐
              │   Shared Knowledge  │
              │  attempts/ notes/   │
              │  skills/ configs/   │
              └─────────────────────┘
```

### Five components:

**1. Task & Evaluation.** A user-defined codebase and grading function. The grader runs in each agent's worktree and outputs a numeric score. Evolution is task-agnostic: it works on anything with a measurable outcome.

**2. Manager Infrastructure.** Spawns agents into isolated git worktrees, runs evaluation when agents submit, tracks the leaderboard, delivers messages, detects stagnation, and persists session state. All shared-state writes go through the manager via a Unix domain socket. Zero race conditions by design.

**3. Agent Pool.** Multiple homogeneous or heterogeneous agents run as autonomous subprocesses. Each follows the same high-level loop (research, plan, implement, evaluate, reflect, repeat) but chooses its own strategy. Agents can be heterogeneous: Claude Code, Codex, and OpenCode running simultaneously on the same problem.

**4. Shared Knowledge Layer.** Four types of persistent knowledge, stored as markdown files with YAML frontmatter:

- **Attempts**: every evaluation with score, description, and grader feedback
- **Notes**: agent observations, findings, warnings, and proposals (with structured tags: `technique`, `dead-end`, `paper`, `competitor`)
- **Skills**: reusable techniques that agents publish for others
- **Hypotheses**: structured predictions that agents track, test, and resolve with evidence

**5. Heartbeat Mechanism.** Multiple named heartbeats at different frequencies: `reflect` after every eval, `consolidate` every 5, `converge` every 10. Each fires independently. The `converge` heartbeat triggers population-level convergence: all agents rebase to the best-scoring agent's code. Regular heartbeats force reflection and knowledge sharing.

## The Agent Loop

Each agent runs autonomously:

```
1. Check inbox for leaderboard updates, claims, and directives
2. Check open hypotheses: evolution hypothesis list --status open
3. Check claims: evolution claims (see what others are working on)
4. Claim work: evolution note add "WORKING ON: X" --tags working-on
5. Research: read papers, diff other agents, cherry-pick good files
6. Implement: make targeted changes
7. Test: run the test suite, verify no regressions
8. Evaluate: evolution eval -m "description" (queued, non-blocking)
9. Share: post findings, resolve hypotheses, warn about dead ends
10. Repeat
```

Agents communicate through the shared knowledge hub, not direct messaging. This creates a naturally asynchronous collaboration pattern. Agents don't block each other, and late-joining agents can catch up by reading the accumulated knowledge.

## Cross-Pollination

Agents can see and steal each other's work:

```bash
evolution claims                              # who's working on what?
evolution diff agent-2                        # what did agent-2 change?
evolution cherry-pick agent-1 src/retriever.py  # copy agent-1's file into my worktree
```

This solves the biggest problem in multi-agent sessions: agents rebuilding what someone else already built. With `diff` and `cherry-pick`, good implementations propagate across the pool without requiring agents to read each other's notes.

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

## Merging the Winner

When the session ends, merge the best agent's work into a branch:

```bash
# Preview what would be merged
evolution merge --dry-run

# Create a branch with the winning agent's changes + changelog
evolution merge --branch evolution/my-feature

# Merge a specific agent (not just the best)
evolution merge --agent agent-3 --branch evolution/agent-3-approach
```

The merge command creates a new branch from HEAD, copies the winning agent's changed files, and commits with a **generated changelog**: top attempts, key findings from notes, and hypothesis resolutions. You can then review the branch and open a PR.

## The Best Way to Run Evolution

The recommended way to run Evolution is to let a Claude Code instance manage the session for you. Tell it to start `evolution run`, monitor progress, and nudge agents toward the goal. Claude Code becomes your **superagent**. It reads the leaderboard, checks agent notes, sends course corrections, and escalates when something needs your attention.

This matters because Claude Code supports remote control. Once the session is running, you can connect from your phone, a tablet, or any browser to check scores, send messages to agents, pause or spawn new ones. You don't need to be at your desk. A 48-hour evolution session becomes something you can steer from anywhere.

Evolution runs fine without steering too. Agents are autonomous and will make progress on their own. But human guidance at key moments ("stop using Chroma, switch to turbopuffer" or "retrieval isn't the bottleneck, focus on answer quality") can save hours of wasted exploration. The superagent pattern gives you that leverage without requiring constant attention.

## Convergence

Every N evals, the `converge` heartbeat fires. The manager identifies the best-scoring agent and resets all other worktrees to that agent's code. Agents keep their git history. They can `git diff HEAD~1` to see what changed. But they're now all building from the best-known baseline.

Without convergence, agents diverge indefinitely. One agent might spend 20 attempts improving fundamentally worse code. Convergence refocuses the population on the most promising direction while preserving exploration freedom after the rebase.

## Research Phases

Sessions can define a **research phase** where eval submissions are blocked:

```yaml
task:
  phases:
    - name: research
      duration: 30m
      eval_blocked: true
      prompt: "Research only. Read papers, study competitors. Share findings."
    - name: evolve
```

During the research phase, agents explore the problem space and share structured notes (`--tags paper,technique,competitor`). When the phase ends, they transition to implementation with a shared understanding of the landscape. This prevents the "everyone jumps to coding" problem.

## Hypothesis Tracking

Agents can post structured hypotheses and resolve them with evidence:

```bash
evolution hypothesis add "Higher BM25 weight improves KU recall" --metric ku_score
evolution hypothesis list --status open
evolution hypothesis resolve H-1 --validated --evidence "Attempt #12: KU 71% → 78%"
```

This prevents agents from re-testing the same ideas. Open hypotheses are visible to all agents. "H-3 is untested, let me try it" instead of independently discovering the same question.

## Eval Queue

Eval submissions go through a **serialized queue** instead of running graders immediately. This prevents resource exhaustion when grading is expensive (GPU, API calls, large datasets).

```yaml
task:
  eval_queue:
    concurrency: 1
    fairness: round_robin
    max_queued: 8
    rate_limit_seconds: 300
    priority_boost: improving
```

Agents submit and get back a queue position immediately, no blocking. Results arrive in their inbox when grading completes. Round-robin fairness prevents any single agent from flooding the queue. Priority boost rewards agents on an improvement streak with faster feedback.

## Session Chaining

Multi-day research becomes a series of focused sessions, each building on the last:

```yaml
session:
  name: lattice-v5
  seed_from: lattice-v4
```

When `seed_from` is set, the new session loads the previous session's best code and accumulated memory (`.evolution/shared/memory/`). Attempts, notes, and skills reset fresh, no stale context. The knowledge graph grows across sessions while the agent pool starts clean.

## Stagnation and Shake-Up

When no agent improves the score for a configurable duration, Evolution can either stop the session or trigger a **shake-up**, a message to all agents saying "no progress detected, try something radically different." This nudge often breaks agents out of local optima. A budget controls how many shake-ups happen before the session truly stops.

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

- `**evolution.yaml**`: session configuration (agents, roles, grading, stop conditions)
- `**evolution_grader.py**`: a wrapper that runs your eval command and extracts a numeric score

## Configuration

Everything lives in `evolution.yaml`:

```yaml
session:
  name: my-project
  seed_from: my-project-v1   # optional: build on previous session

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

  phases:                      # optional: structured research before coding
    - name: research
      duration: 30m
      eval_blocked: true
      prompt: "Research only. Share findings with evolution note add --tags technique."
    - name: evolve

  eval_queue:                  # optional: queued evaluation
    concurrency: 1
    fairness: round_robin
    max_queued: 8
    rate_limit_seconds: 300
    priority_boost: improving

  stop:
    max_time: 6h
    stagnation: 1h
    stagnation_action: shake_up
    shake_up_budget: 3

roles:
  researcher:
    prompt: |
      You are a research agent. Check inbox before every action.
      Use evolution claims, diff, cherry-pick to learn from others.
      Track hypotheses. Share findings with structured tags.
    heartbeat:
      - name: reflect
        every: 1
      - name: consolidate
        every: 5
      - name: converge
        every: 10

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

Each agent gets its own isolated copy of the repo at `.evolution/worktrees/<name>/`. Evolution auto-detects the best strategy for your filesystem:

**On macOS (APFS) and Linux (btrfs/XFS):** Copy-on-write cloning via `cp -c` / `cp --reflink=always`. The entire repo (source code, `.venv`, `node_modules`, build caches, configs) is cloned at near-zero disk cost. Files share physical blocks until an agent modifies them. Agents start working immediately with all dependencies in place.

**On Linux (ext4) and Windows (NTFS):** Git worktrees with auto-discovered symlinks. Git-tracked files are checked out on a new branch. Gitignored directories (`.venv`, `node_modules`, `target/`, `.next/`, etc.) are discovered automatically via `git ls-files --ignored` and symlinked, no hardcoded list.

Both paths warm the OS disk cache in a background thread after creation, so `grep`, `find`, and file reads from agents are fast from the start.

```yaml
task:
  workspace_strategy: auto   # auto | reflink | git_worktree (default: auto)
```

The shared knowledge directory (`.evolution/shared/`) is symlinked into every worktree so agents can read each other's attempts, notes, and skills.

## Grading

Evolution supports three grading strategies:


| Type       | How It Works                                                    |
| ---------- | --------------------------------------------------------------- |
| **Script** | Runs a Python script, parses first stdout line as numeric score |
| **LLM**    | Sends the diff to an LLM, gets a score + qualitative feedback   |
| **Hybrid** | Script for the hard metric, LLM for strategic feedback          |


### Composite and Multi-Metric Scoring

Real optimization problems rarely have a single number. A memory system needs good recall *and* low latency *and* reasonable cost. Evolution supports **composite metrics**: your grader can combine multiple benchmarks into a weighted score (e.g., 40% accuracy + 35% F1 + 25% throughput), and agents optimize the composite while seeing per-component breakdowns in their feedback.

For multi-metric tasks without a predefined composite, four ranking strategies determine which attempt is "better":


| Strategy             | When to use                                              |
| -------------------- | -------------------------------------------------------- |
| **Weighted sum**     | You know the relative importance of each metric          |
| **Pareto dominance** | An attempt is better only if it improves *every* metric  |
| **Min-rank**         | Penalizes being bad at any one thing (robust generalist) |
| **All-must-improve** | Accept only if every metric strictly improves            |


### Tiered Evaluation

For expensive benchmarks, graders can run a **fast eval** on most attempts (e.g., a subset of test cases, ~3 min) and a **full eval** periodically (e.g., all benchmarks in parallel, ~12 min). This gives agents fast iteration cycles while still tracking the true composite score.

## Supported Runtimes


| Runtime       | Instruction File | Description                                           |
| ------------- | ---------------- | ----------------------------------------------------- |
| `claude-code` | `CLAUDE.md`      | Claude Code with full tool use and context compaction |
| `codex`       | `AGENTS.md`      | OpenAI Codex with approval bypass                     |
| `opencode`    | `AGENTS.md`      | OpenCode CLI                                          |


Adding a new runtime means writing a single adapter class. See [docs/adapters.md](docs/adapters.md).

## Design Principles

1. **Autonomy over structure.** Agents decide what to work on. The manager orchestrates infrastructure, not strategy.
2. **Files as truth.** Shared knowledge is markdown on the filesystem, readable by humans and agents alike. No databases, no message queues.
3. **Manager serializes everything.** All shared-state writes go through the Unix socket. Zero race conditions by construction.
4. **Runtime-agnostic.** The same session can run Claude Code, Codex, and OpenCode agents simultaneously. Adding a new runtime is one adapter class.
5. **Human control when you want it.** Full CLI for live steering, but the system runs autonomously if you walk away.

## Project Structure

```
evolution/
├── evolution/
│   ├── cli/           # CLI commands (init, run, eval, note, msg, ...)
│   ├── manager/       # Core orchestrator, config, heartbeat, socket server
│   ├── workspace/     # Adaptive workspace: reflink CoW or git worktree
│   ├── hub/           # Shared knowledge: attempts, notes, skills
│   ├── grader/        # Script, LLM, hybrid, and multi-metric grading
│   ├── adapters/      # Runtime adapters: Claude Code, Codex, OpenCode
│   └── superagent/    # Remote control agent
├── tasks/             # Example benchmark tasks
├── tests/             # 328 tests
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

**Independent exploration.** Early in a session, agents pursue different strategies. One might focus on algorithmic improvements while another investigates configuration tuning. The shared notes hub means they can see what others are trying without being forced to coordinate.

**Rapid adaptation.** When one agent achieves a breakthrough score, others read the shared notes and adapt the technique to their own approach. They don't abandon their strategy; they incorporate what worked.

**Dead-end avoidance.** Agents post "DEAD END" notes when an approach fails. Other agents read these before starting work, saving hours of wasted exploration. The collective learns from individual failures.

**Consensus and synthesis.** As improvement plateaus, agents begin cross-referencing each other's implementations, identifying which specific changes drove improvement, and synthesizing hybrid approaches that combine the best ideas from multiple agents.

**Self-organization through notes.** Agents claim work with "WORKING ON: X" notes, preventing collisions. They share context with "FINDING: Y" notes. No central scheduler assigns tasks. Agents coordinate through shared state.

## Prior Work

Evolution is inspired by [autoresearch](https://github.com/karpathy/autoresearch), [CORAL](https://github.com/Human-Agent-Society/CORAL), and [Hyperagents](https://arxiv.org/abs/2603.19461). We extend the single-agent eval loop (autoresearch) to multi-agent collective intelligence with structured knowledge sharing. We share CORAL's core architecture (worktrees, symlinked state, runtime adapters) but add heartbeat-triggered convergence, hypothesis tracking, multi-metric ranking, research phases, and live human steering. We achieve Hyperagents' metacognitive self-modification through natural-language reflection and shared skills rather than source-code edits, and favor parallel collective exploration over single-lineage evolution.

## Citation

If you find Evolution useful, please consider citing it:

```bibtex
@misc{evolution2026,
  title = {Evolution: Multi-Agent Code Evolution Platform},
  author = {Sayan Chakraborty},
  year = {2026},
  url = {https://github.com/aadi-labs/evolution}
}
```

## License

This project is licensed under the [MIT License](LICENSE).