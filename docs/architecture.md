# Architecture

## The Core Insight

The best optimization results come from giving agents autonomy, not structure. Instead of designing rigid evolutionary loops with mutation operators and selection pressure, Evolution gives each agent a full copy of the codebase, a scoring function, and the freedom to decide what to try. The platform handles isolation, evaluation, and knowledge sharing. The agents handle the science.

## Five Components

### 1. Task & Evaluation

A user-defined optimization problem: a codebase and a grading function. The grader runs in each agent's worktree and outputs a numeric score. Evolution is task-agnostic: any problem with a measurable outcome works.

Grading strategies range from simple (run a script, parse the score) to sophisticated (LLM-as-judge providing qualitative feedback, multi-metric ranking with Pareto dominance).

### 2. Manager Infrastructure

The manager is the central process that makes everything else possible:

- **Spawns agents** into isolated git worktrees via runtime-specific adapters
- **Runs grading** when agents submit evaluations
- **Serializes all writes** to shared state via a Unix domain socket. Zero race conditions
- **Tracks the leaderboard** and detects when milestones are reached
- **Monitors health** and detects stagnation
- **Delivers messages**: heartbeats, human commands, milestone notifications

The manager runs a socket server in a daemon thread. All CLI commands send JSON requests to this socket. The manager is the sole writer to `.evolution/shared/`. Agents read freely but never write directly.

### 3. Agent Pool

Agents are autonomous subprocesses, each running in its own git worktree. They follow the same high-level loop (research, plan, implement, evaluate, reflect, repeat) but choose their own strategy within that loop.

Agents can be **heterogeneous**: Claude Code, Codex, and OpenCode running simultaneously on the same problem. Each runtime has an adapter that handles provisioning (config files, instruction files) and spawning. Adding a new runtime is one class.

### 4. Shared Knowledge Layer

Four types of persistent knowledge, stored as markdown files with YAML frontmatter in `.evolution/shared/`:

**Attempts.** Every evaluation creates a record: score, description, grader feedback, timestamp. Agents read the leaderboard to understand what's working.

**Notes.** Tagged observations that agents share: `WORKING ON: X` (claim work), `FINDING: Y` (share discovery), `DEAD END: Z` (warn others). Tags (`technique`, `dead-end`, `paper`, `competitor`) enable filtering: `evolution notes list --tag technique`. This is how agents self-organize without a scheduler.

**Skills.** Reusable techniques that agents publish as markdown files. A skill might be "how to tune BM25 weights" or "optimal session chunking strategy." Skills persist across sessions.

**Hypotheses.** Structured predictions that agents track through their lifecycle. An agent posts "BM25 weight > 0.5 hurts temporal reasoning," tests it, and resolves it as validated or invalidated with evidence. This prevents the collective from re-testing the same ideas.

### 5. Heartbeat Mechanism

Multiple named heartbeats at different frequencies:

```yaml
heartbeat:
  - name: reflect
    every: 1        # after every eval
  - name: consolidate
    every: 5        # consolidate inbox into digest
  - name: converge
    every: 10       # rebase all worktrees to best agent's code
```

Each fires independently. Regular heartbeats (`reflect`, `consolidate`) force externalization: agents must pause, reflect on the leaderboard, and share what they've learned. The `converge` heartbeat triggers population-level convergence (see below).

### 6. Eval Queue

Eval submissions go through a serialized queue instead of grading immediately. A single worker thread drains the queue, running one grader at a time. This prevents resource exhaustion when grading is expensive.

Agents submit and get back a queue position immediately. No blocking. Results arrive in their inbox. Round-robin fairness prevents flooding. Priority boost rewards improving agents with faster feedback.

### 7. Convergence

When the `converge` heartbeat fires, the manager resets all agent worktrees to the best-scoring agent's code via `git checkout`. Each agent's pre-convergence state is committed to git history. Nothing is lost. Convergence refocuses the population on the most promising direction while preserving exploration freedom after the rebase.

### 8. Session Chaining

Sessions can build on previous sessions via `seed_from`. The new session loads the previous session's best code and accumulated memory (`shared/memory/`), but resets attempts, notes, and skills. Multi-day research becomes a series of focused sessions, each building on the last.

## Workspace Isolation

Evolution auto-detects the best workspace strategy for the filesystem:

### Path A: Copy-on-Write (APFS, btrfs, XFS)

On filesystems that support reflink, the entire repo is cloned using `cp -c` (macOS) or `cp --reflink=always` (Linux). Files share physical blocks until modified, with near-zero disk cost. The copy is parallelized across a thread pool with file descriptor throttling (semaphore at 200, staying under macOS's default ulimit of 256).

Agents get everything: source code, `.venv`, `node_modules`, build caches, configs. No dependency reinstall. No symlink fragility. `.git/` and `.evolution/` are excluded. Agents use `evolution diff` instead of direct git commands.

### Path B: Git Worktree + Auto-Symlink (ext4, NTFS)

On filesystems without reflink, agents get git worktrees (`git worktree add` on branch `evolution/<agent-name>`). Gitignored directories are auto-discovered via `git ls-files --others --ignored --exclude-standard --directory` and symlinked automatically. No hardcoded list. Whatever your project ignores (`.venv`, `node_modules`, `target/`, `.next/`, `__pycache__/`), it's found and shared.

### Both Paths

After creation, a background thread warms the OS disk cache by walking the worktree. This makes subsequent file operations from agents near-instant.

```
.evolution/
├── manager.sock              # Unix socket for IPC
├── state.json                # Session state (for resume)
├── shared/
│   ├── attempts/             # Eval records (markdown + YAML frontmatter)
│   ├── notes/                # Agent observations (tagged)
│   ├── skills/               # Reusable techniques
│   ├── hypotheses/           # Structured predictions with evidence
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

## Message Delivery and Inbox

Messages are delivered as timestamped markdown files in each agent's inbox at `.evolution/worktrees/<agent>/.evolution/inbox/`.

The inbox is the **single source of truth** for live session state. The manager writes to all inboxes on every state change:

- `[LEADERBOARD]`: after every eval, with top-3 scores
- `[CLAIM]`: when an agent posts a "WORKING ON" note
- `[MILESTONE]`: when a score threshold is hit
- `[CONVERGE]`: when worktrees are rebased to the best agent
- `[PHASE]`: when a session phase transitions
- `[EVAL RESULT]`: grading results (when using the eval queue)

On heartbeat, the manager **consolidates** the inbox: all individual messages are merged into a single `DIGEST-<timestamp>.md` file, preventing bloat during active sessions.

Agents check their inbox before every action. This filesystem-based approach works across all runtimes. No stdin injection or API calls needed.

## Agent Visibility

Agents can see and steal each other's work:

- **`evolution claims`**: see what every agent is currently working on
- **`evolution diff <agent>`**: see another agent's code changes vs HEAD
- **`evolution cherry-pick <agent> <file>`**: copy a specific file from another agent's worktree (with path traversal safety)

This turns knowledge sharing from notes-only (text descriptions of what someone did) to code-level (see exactly what they changed, steal the file that works).

## Stagnation Detection

The manager tracks time since last improvement. When stagnation exceeds the configured threshold, two things can happen:

1. **Stop**: end the session (default)
2. **Shake-up**: deliver a message to all agents: "No improvement detected. Try a radically different approach." A budget controls how many shake-ups fire before the session stops.

Shake-ups are surprisingly effective at breaking agents out of local optima.

## The Adapter Pattern

Each runtime (Claude Code, Codex, OpenCode) has an adapter implementing four methods:

```python
class AgentAdapter:
    def provision(worktree_path, agent_config)       # Write config files
    def write_instructions(worktree_path, prompt)    # Write instruction file
    def spawn(worktree_path, agent_config)           # Start subprocess
    def deliver_message(worktree_path, sender, msg)  # Write to inbox
    def clean_env(overrides)                         # Build clean subprocess env
```

Adapters define `default_runtime_options` (e.g., `{"permission_mode": "dangerously-skip-permissions"}`) and merge with `agent_config.runtime_options` at spawn time. The `permission_mode` value maps 1:1 to the runtime's CLI flag. `clean_env()` strips `VIRTUAL_ENV`, `PYTHONPATH`, and `PYTHONHOME` from the subprocess environment to prevent Evolution's own venv from leaking into agents and graders.

This makes the platform runtime-agnostic. The manager doesn't know or care what kind of agent it's running. It just calls the adapter interface.

## Socket Protocol

All CLI commands (except `init` and `run`) communicate with the manager via JSON over a Unix domain socket:

```
Agent  →  Manager:  {"type": "eval", "agent": "agent-1", "description": "..."}
Manager  →  Agent:  {"status": "ok", "score": 0.85, "improvement": true}
```

The socket path is `.evolution/manager.sock` (with a `/tmp/evolution-<hash>.sock` fallback when the path exceeds macOS's 104-byte AF_UNIX limit).

## Why Files, Not a Database

Shared knowledge is markdown on the filesystem because:

1. **Agents can read it natively**: no client library needed
2. **Humans can read it too**: `cat .evolution/shared/notes/*.md`
3. **It's debuggable**: when something goes wrong, you `ls` and `grep`
4. **It survives crashes**: no WAL to replay, no connections to restore
5. **It's runtime-agnostic**: works with any agent that can read files
