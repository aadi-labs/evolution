---
name: evolution-agent
description: Run and manage Evolution sessions — multi-agent code optimization. Read this file, then tell Claude Code what to optimize and it handles setup, monitoring, steering, and merging.
---

# Evolution Agent Skill

This skill lets you run Evolution — a multi-agent platform where AI agents collaborate to optimize a codebase against a scoring function.

**How to use:** Tell your coding agent (Claude Code, Codex, etc.):
> "Read skills/evolution-agent.md. Run evolution on this repo to optimize [describe goal]. The eval command is [command]."

The agent handles everything: setup, configuration, launching agents, monitoring, steering, and merging the results.

---

## Part 1: Running Evolution (You Are the Orchestrator)

Use this when you want to SET UP and MANAGE an evolution session.

### Step 1: Install

```bash
cd /path/to/evolution
uv sync
```

The `evolution` CLI should now be available. If not, use the full path: `/path/to/evolution/.venv/bin/evolution`.

### Step 2: Initialize

In the target repo (the codebase to optimize):

```bash
evolution init --eval "pytest tests/ -q" --name my-session --agents claude-code
```

This creates `evolution.yaml` and `evolution_grader.py`. Edit `evolution.yaml` to customize:

- **Agents**: how many, which runtimes
- **Roles**: the system prompt agents receive
- **Milestones**: baseline, target, stretch scores
- **Stop conditions**: max time, stagnation timeout
- **Eval queue**: fairness, rate limiting, concurrency
- **Phases**: optional research phase before coding
- **Heartbeats**: reflect, consolidate, converge frequencies

### Step 3: Write the Grader

The grader script runs in each agent's worktree and outputs a score. Edit `evolution_grader.py`:

```python
#!/usr/bin/env python3
# First line of stdout = numeric score (0.0 - 1.0)
# stderr = feedback text shown to agent
import subprocess, sys

result = subprocess.run(["your", "eval", "command"], capture_output=True, text=True)
# Parse score from output
print(score)
print(feedback, file=sys.stderr)
```

### Step 4: Start

```bash
evolution run --config evolution.yaml
```

This spawns agents, creates workspaces, and enters the manager loop. Leave it running.

### Step 5: Monitor and Steer

While the session runs:

```bash
evolution status                # agents, scores, uptime
evolution attempts list         # leaderboard
evolution notes list            # what agents have discovered
evolution notes list --tag technique  # filter by tag
evolution claims                # who's working on what
evolution hypothesis list       # tracked hypotheses

# Steer agents
evolution msg --all "focus on retrieval quality, not answer prompts"
evolution msg agent-2 "try the batch embedding API"
evolution pause agent-3         # pause underperformer
evolution spawn --clone agent-1 # clone a winner
evolution kill agent-4          # remove an agent
```

**Your job as orchestrator:**
- Watch the leaderboard for stagnation
- Read agent notes for insights
- Course-correct when agents go in the wrong direction
- Nudge agents toward promising approaches
- Pause/kill/spawn to manage the pool

### Step 6: Merge the Winner

When the session ends (or you're satisfied):

```bash
evolution merge --dry-run                        # preview changelog
evolution merge --branch evolution/my-feature    # create branch
evolution merge --agent agent-2 --branch feat/x  # merge specific agent
```

This creates a git branch with the winning agent's changes and a generated changelog (top attempts, key findings, hypothesis resolutions). Open a PR from there.

### Example evolution.yaml

```yaml
session:
  name: optimize-retrieval

task:
  name: retrieval-quality
  path: .
  seed: .
  description: Improve hybrid retrieval to beat 85% accuracy on the eval suite.
  grader:
    type: script
    script: ./evolution_grader.py
  metric:
    name: accuracy
    direction: higher_is_better
  milestones:
    baseline: 0.72
    target: 0.85
    stretch: 0.95
  phases:
    - name: research
      duration: 20m
      eval_blocked: true
      prompt: "Research only. Read the codebase, study the eval, share findings."
    - name: evolve
  eval_queue:
    concurrency: 1
    fairness: round_robin
    max_queued: 8
  stop:
    max_time: 6h
    stagnation: 1h
    stagnation_action: shake_up
    shake_up_budget: 3

roles:
  agent:
    prompt: |
      You are an autonomous research agent optimizing retrieval quality.
      Before every action, read .evolution/inbox/ for messages.
      Check evolution claims before starting new work.
      Use evolution diff and cherry-pick to learn from other agents.
      Post structured notes with --tags (technique, dead-end, finding).
      Test open hypotheses: evolution hypothesis list --status open
    heartbeat:
      - name: reflect
        every: 1
      - name: consolidate
        every: 5
      - name: converge
        every: 10

agents:
  agent-1:
    role: agent
    runtime: claude-code
  agent-2:
    role: agent
    runtime: claude-code
  agent-3:
    role: agent
    runtime: claude-code
  agent-4:
    role: agent
    runtime: claude-code

superagent:
  enabled: true
  runtime: claude-code
  remote_control: true
```

---

## Part 2: Working Inside a Session (You Are a Worker Agent)

Use this when you are ONE OF the agents inside a running evolution session. Your worktree is at `.evolution/worktrees/<your-name>/`.

### Your Loop

Every cycle:

1. **Read inbox**: `ls .evolution/inbox/` — read any `DIGEST-*.md` or individual messages
2. **Check claims**: `evolution claims` — see what others are doing, avoid collisions
3. **Check hypotheses**: `evolution hypothesis list --status open` — find untested ideas
4. **Claim work**: `evolution note add "WORKING ON: X" --tags working-on`
5. **Research**: read code, `evolution diff <agent>`, `evolution cherry-pick <agent> <file>`
6. **Implement**: make targeted changes to improve the score
7. **Test**: run the test suite before submitting
8. **Eval**: `evolution eval -m "what I changed and why"`
9. **Share**: post findings, resolve hypotheses, warn about dead ends
10. **Check inbox again** for eval results and new state
11. **Repeat forever** — there is always more to improve

### Commands You Need

```bash
# Submit work
evolution eval -m "switched to server-side BM25, improved recall 12%"

# Share knowledge
evolution note add "client-side BM25 is 10x slower than server-side" --tags technique
evolution note add "adding Neo4j graph hurt latency with no score gain" --tags dead-end
evolution note add "WORKING ON: temporal reasoning prompts" --tags working-on
evolution note add "DONE: temporal — TR improved 58% to 71%" --tags done

# Learn from others
evolution claims                          # who's doing what
evolution diff agent-2                    # see their changes
evolution cherry-pick agent-1 src/ret.py  # steal a file that works
evolution notes list --tag technique      # what techniques work
evolution attempts list                   # leaderboard

# Track hypotheses
evolution hypothesis add "recency boost > 0.8 hurts KU" --metric ku_score
evolution hypothesis list --status open
evolution hypothesis resolve H-3 --validated --evidence "KU dropped 5%"

# Publish a reusable technique
evolution skill add my-technique.md
```

### When You Get a Heartbeat

Messages arrive in your inbox with prefixes:

- **`[LEADERBOARD]`**: Scores changed. Check if your approach is competitive.
- **`[CLAIM]`**: Another agent claimed work. Adjust if overlapping.
- **`[MILESTONE]`**: A score threshold was hit. Read what worked.
- **`[CONVERGE]`**: Your worktree was rebased to the best agent's code. Your old changes are in git history (`git diff HEAD~1`). Build from the new baseline.
- **`[PHASE]`**: Session phase changed (e.g., research ended, coding begins).
- **`[EVAL RESULT]`**: Your eval was graded. Read the score and feedback.
- **`HEARTBEAT [reflect]`**: Pause. Read the leaderboard and notes. Share what you've learned. Decide: continue or pivot?
- **`HEARTBEAT [consolidate]`**: Summarize your recent work in a note.

### Rules

1. **Read inbox before every action.** Not optional.
2. **Check claims before starting work.** Don't duplicate what someone else is doing.
3. **Diff before rebuilding.** If another agent built it, cherry-pick it.
4. **Always use --tags on notes.** Tags: `technique`, `dead-end`, `paper`, `competitor`, `finding`, `working-on`, `done`.
5. **Resolve hypotheses with evidence.** Don't leave them open.
6. **Share dead ends.** Save others hours of wasted work.
7. **Eval often.** Small changes, fast feedback. Don't build for 2 hours without checking the score.
8. **Never stop.** There is always more to improve. If you run out of ideas, read shared notes, check open hypotheses, or try a radically different approach.
