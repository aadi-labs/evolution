# Configuration Reference

Evolution sessions are configured via a single `evolution.yaml` file. Generate one with `evolution init` or write it by hand.

## Full Schema

### session

```yaml
session:
  name: string              # Session identifier (required)
  log_level: string         # debug | info | warning | error (default: info)
  seed_from: string | null  # Previous session name for chaining (default: null)
```

### task

```yaml
task:
  name: string              # Task name (required)
  description: string       # Human-readable description (required)
  path: string              # Path to task root (default: .)
  seed: string              # Seed directory to copy into worktrees (default: .)

  grader:
    type: script            # script | llm | hybrid
    script: ./grader.py     # Path to grader script (for script/hybrid types)

  # Single metric
  metric:
    name: score             # Metric name
    direction: higher_is_better  # higher_is_better | lower_is_better

  # Multi-metric (alternative to metric)
  metrics:
    accuracy:
      direction: higher_is_better
      weight: 0.6
    latency:
      direction: lower_is_better
      weight: 0.4
  ranking: weighted_sum     # weighted_sum | pareto | min_rank | all_must_improve

  milestones:
    baseline: 0.65          # Starting score (optional)
    target: 0.90            # Target to reach (optional)
    stretch: 0.99           # Stretch goal (optional)

  stop:
    max_time: 6h            # Wall-clock limit (required)
    max_attempts: 200       # Max eval submissions (optional)
    stagnation: 1h          # No improvement timeout (default: 1h)
    stagnation_action: stop # stop | shake_up (default: stop)
    shake_up_budget: 2      # Shake-ups before hard stop (default: 2)
    manual: true            # Allow `evolution stop` (default: true)
    milestone_stop: target  # Stop when this milestone is reached (optional)

  # Session phases (optional)
  phases:
    - name: research         # Phase name
      duration: 30m          # Phase duration (optional — runs until next phase if unset)
      eval_blocked: true     # Block eval submissions during this phase (default: false)
      prompt: "..."          # Override role prompt during this phase (optional)
    - name: evolve           # Final phase (no duration = runs until session ends)

  # Eval queue (optional — without this, evals grade synchronously)
  eval_queue:
    concurrency: 1           # Graders running in parallel (default: 1)
    fairness: round_robin    # fifo | round_robin | priority (default: round_robin)
    max_queued: 8            # Max pending evals before rejection (default: 8)
    rate_limit_seconds: 300  # Min seconds between evals per agent (default: 0 = no limit)
    priority_boost: improving # none | improving (default: none)
```

### roles

Roles define the persona and heartbeat config for a class of agents.

```yaml
roles:
  researcher:
    prompt: |
      You are a research agent. Explore, implement, evaluate, share.

    # Legacy format (single heartbeat)
    heartbeat:
      on_attempts: 3
      on_time: 10m
      strategy: first

    # Named list format (multiple heartbeats at different frequencies)
    heartbeat:
      - name: reflect
        every: 1           # after every eval
      - name: consolidate
        every: 5           # consolidate inbox every 5 evals
      - name: converge
        every: 10          # rebase to best agent every 10 evals
```

### agents

Each agent references a role and specifies its runtime.

```yaml
agents:
  agent-1:
    role: researcher         # Must match a key in roles
    runtime: claude-code     # claude-code | codex | opencode
    skills: [superpowers]    # Skills to enable (default: [])
    plugins: []              # Plugins to enable (default: [])
    mcp_servers: []          # MCP servers to configure (default: [])
    env:                     # Extra environment variables (default: {})
      CUSTOM_VAR: value
    restart:
      enabled: false         # Auto-restart on crash (default: false)
      max_restarts: 3        # Max restart attempts (default: 3)
      preserve_worktree: true
```

### superagent

Optional Claude Code instance for live human control.

```yaml
superagent:
  enabled: true              # Enable superagent (default: false)
  runtime: claude-code       # Only claude-code supported
  remote_control: true       # Allow remote sessions (default: true)
  skills: [superpowers]
  prompt: |
    You are the superagent. Monitor agents and steer the session.
```

## Duration Strings

Used for `max_time`, `stagnation`, and `on_time`:

| Format | Example | Meaning |
|--------|---------|---------|
| `Nm` | `30m` | 30 minutes |
| `Nh` | `6h` | 6 hours |
| `Nd` | `2d` | 2 days |
| `N` | `3600` | 3600 seconds |

## Grader Script Protocol

The script grader runs your script as a subprocess and expects:

- **stdout, first line**: A single float (the score)
- **stderr**: Feedback text (passed to the agent)
- **exit code 0**: Success
- **exit code != 0**: Grading failed (score = 0.0)

Example grader:

```python
#!/usr/bin/env python3
import subprocess, json

result = subprocess.run(["pytest", "tests/", "-q", "--tb=no"],
                       capture_output=True, text=True)
passed = result.stdout.count(" passed")
total = passed + result.stdout.count(" failed")
score = passed / total if total > 0 else 0.0

print(score)  # First line = score
print(f"Passed {passed}/{total} tests", file=__import__('sys').stderr)
```

## Multi-Metric Ranking

When using multiple metrics, Evolution supports four ranking strategies:

| Strategy | Behavior |
|----------|----------|
| `weighted_sum` | Normalize each metric 0-1, apply weights, sum |
| `pareto` | A beats B only if A dominates on ALL metrics |
| `min_rank` | Rank per-metric, use worst rank (penalizes weakness) |
| `all_must_improve` | Accept only if every metric improves |

## Environment Variables

Agents inherit the parent process environment. The `env` field in agent config adds or overrides specific variables. Sensitive values (API keys) should be in the parent shell environment or a `.env` file in the repo.

## Workspace Strategy

Evolution auto-detects the best workspace strategy. Override with:

```yaml
task:
  workspace_strategy: auto        # auto | reflink | git_worktree
```

| Strategy | When Used | What Agents Get |
|----------|-----------|-----------------|
| `reflink` | APFS (macOS), btrfs/XFS (Linux) | Full copy-on-write clone — source, deps, caches. Near-zero disk cost. |
| `git_worktree` | ext4 (Linux), NTFS (Windows) | Git worktree + auto-discovered symlinks for gitignored dirs. |
| `auto` | Default | Tries reflink first, falls back to git worktree. |

With `auto`, Evolution probes the filesystem at session start by attempting a reflink copy of a test file. The result is cached for all agents in the session.

**Git worktree symlink discovery:** Instead of a hardcoded list, Evolution runs `git ls-files --others --ignored --exclude-standard --directory` to find all gitignored directories that exist (`.venv`, `node_modules`, `target/`, `.next/`, etc.) and symlinks them automatically.
