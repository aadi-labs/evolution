# Architecture

## The Core Insight

The best optimization results come from giving agents autonomy, not structure. Instead of designing rigid evolutionary loops with mutation operators and selection pressure, Evolution gives each agent a full copy of the codebase, a scoring function, and the freedom to decide what to try. The platform handles isolation, evaluation, and knowledge sharing. The agents handle the science.

## Five Components

### 1. Task & Evaluation

A user-defined optimization problem: a codebase and a grading function. The grader runs in each agent's worktree and outputs a numeric score. Evolution is task-agnostic — any problem with a measurable outcome works.

Grading strategies range from simple (run a script, parse the score) to sophisticated (LLM-as-judge providing qualitative feedback, multi-metric ranking with Pareto dominance).

### 2. Manager Infrastructure

The manager is the central process that makes everything else possible:

- **Spawns agents** into isolated git worktrees via runtime-specific adapters
- **Runs grading** when agents submit evaluations
- **Serializes all writes** to shared state via a Unix domain socket — zero race conditions
- **Tracks the leaderboard** and detects when milestones are reached
- **Monitors health** and detects stagnation
- **Delivers messages** — heartbeats, human commands, milestone notifications

The manager runs a socket server in a daemon thread. All CLI commands send JSON requests to this socket. The manager is the sole writer to `.evolution/shared/` — agents read freely but never write directly.

### 3. Agent Pool

Agents are autonomous subprocesses, each running in its own git worktree. They follow the same high-level loop — research, plan, implement, evaluate, reflect, repeat — but choose their own strategy within that loop.

Agents can be **heterogeneous**: Claude Code, Codex, and OpenCode running simultaneously on the same problem. Each runtime has an adapter that handles provisioning (config files, instruction files) and spawning. Adding a new runtime is one class.

### 4. Shared Knowledge Layer

Three types of persistent knowledge, stored as markdown files with YAML frontmatter in `.evolution/shared/`:

**Attempts.** Every evaluation creates a record: score, description, grader feedback, timestamp. Agents read the leaderboard to understand what's working.

**Notes.** Free-form observations that agents share: "WORKING ON: X" (claim work), "FINDING: Y" (share discovery), "DEAD END: Z" (warn others). This is how agents self-organize without a scheduler.

**Skills.** Reusable techniques that agents publish as markdown files. A skill might be "how to tune BM25 weights" or "optimal session chunking strategy." Skills persist across sessions.

### 5. Heartbeat Mechanism

A configurable periodic interrupt, triggered by whichever comes first: N eval submissions or elapsed time. When fired, the manager delivers a reflection prompt to the agent's inbox.

This mechanism is critical. Without it, agents tend to fixate on their current approach, failing to step back and share what they've learned. The heartbeat forces externalization — agents must pause, reflect on the leaderboard, and decide whether to continue or pivot.

## Workspace Isolation

Each agent gets a **git worktree** — a real branch (`evolution/<agent-name>`) checked out at `.evolution/worktrees/<name>/`. This provides:

- Full file isolation (agents can't interfere with each other)
- Git history per agent (`git diff`, `git log`, `git stash`)
- Per-worktree index (no lock contention)
- Disk efficiency (git worktrees share the object store)

Untracked directories agents need (`.venv`, `node_modules`, datasets) are symlinked from the main repo. The shared knowledge directory is symlinked into every worktree.

```
.evolution/
├── manager.sock              # Unix socket for IPC
├── state.json                # Session state (for resume)
├── shared/
│   ├── attempts/             # Eval records (markdown + YAML frontmatter)
│   ├── notes/                # Agent observations
│   ├── skills/               # Reusable techniques
│   ├── configs/              # Config snapshots per attempt
│   └── memory/               # Persistent cross-session insights
└── worktrees/
    ├── agent-1/              # Git worktree (branch: evolution/agent-1)
    │   ├── <repo files>      # Checked out from HEAD
    │   ├── CLAUDE.md         # Agent instructions (written by adapter)
    │   ├── .venv → ...       # Symlinked from main repo
    │   └── .evolution/
    │       ├── shared → ..   # Symlink to shared knowledge
    │       └── inbox/        # Message inbox
    └── agent-2/
        └── ...
```

## Message Delivery

Messages (heartbeats, human commands, milestone notifications) are delivered as timestamped markdown files in each agent's inbox at `.evolution/worktrees/<agent>/.evolution/inbox/`.

Agents check their inbox before starting new work and after each eval submission. This filesystem-based approach works across all runtimes — no stdin injection or API calls needed.

## Stagnation Detection

The manager tracks time since last improvement. When stagnation exceeds the configured threshold, two things can happen:

1. **Stop** — end the session (default)
2. **Shake-up** — deliver a message to all agents: "No improvement detected. Try a radically different approach." A budget controls how many shake-ups fire before the session stops.

Shake-ups are surprisingly effective at breaking agents out of local optima.

## The Adapter Pattern

Each runtime (Claude Code, Codex, OpenCode) has an adapter implementing four methods:

```python
class AgentAdapter:
    def provision(worktree_path, agent_config)       # Write config files
    def write_instructions(worktree_path, prompt)    # Write instruction file
    def spawn(worktree_path, agent_config)           # Start subprocess
    def deliver_message(worktree_path, sender, msg)  # Write to inbox
```

This makes the platform runtime-agnostic. The manager doesn't know or care what kind of agent it's running — it just calls the adapter interface.

## Socket Protocol

All CLI commands (except `init` and `run`) communicate with the manager via JSON over a Unix domain socket:

```
Agent  →  Manager:  {"type": "eval", "agent": "agent-1", "description": "..."}
Manager  →  Agent:  {"status": "ok", "score": 0.85, "improvement": true}
```

The socket path is `.evolution/manager.sock` (with a `/tmp/evolution-<hash>.sock` fallback when the path exceeds macOS's 104-byte AF_UNIX limit).

## Why Files, Not a Database

Shared knowledge is markdown on the filesystem because:

1. **Agents can read it natively** — no client library needed
2. **Humans can read it too** — `cat .evolution/shared/notes/*.md`
3. **It's debuggable** — when something goes wrong, you `ls` and `grep`
4. **It survives crashes** — no WAL to replay, no connections to restore
5. **It's runtime-agnostic** — works with any agent that can read files
