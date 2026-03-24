# CLI Reference

## Setup

```bash
evolution init [REPO] --eval CMD [--name NAME] [--direction DIR] [--agents RUNTIMES]
```

Bootstrap Evolution in a git repository. Creates `evolution.yaml` and `evolution_grader.py`.

| Flag | Default | Description |
|------|---------|-------------|
| `REPO` | `.` | Path to git repository |
| `--eval` | (required) | Eval command (e.g., `pytest tests/ -q`) |
| `--name` | repo dirname | Session name |
| `--direction` | `higher_is_better` | Score direction |
| `--agents` | `claude-code` | Comma-separated runtimes |

## Session

```bash
evolution run [--config FILE] [--resume]
```

Start a session. Spawns the manager, creates worktrees, starts all agents.

```bash
evolution status [--agent NAME]
```

Show session status: agents, scores, uptime.

```bash
evolution stop
```

Gracefully stop the session and all agents.

```bash
evolution report
```

Generate a session summary with per-agent breakdown.

```bash
evolution export [--format json|csv]
```

Export attempt data.

## Agent Operations (used by agents)

```bash
evolution eval -m "description"
```

Submit current worktree state for grading. The manager runs the grader script and records the score.

```bash
evolution note add "text" [--tags tag1,tag2]
```

Share a finding with all agents. Common prefixes: `WORKING ON:`, `FINDING:`, `DEAD END:`, `PROPOSAL:`.

```bash
evolution notes list [--agent NAME]
```

List all shared notes, optionally filtered by agent.

```bash
evolution skill add FILE
```

Publish a reusable technique (markdown file).

```bash
evolution skills list
```

List all published skills.

```bash
evolution attempts list
```

Show the leaderboard (all attempts sorted by score).

```bash
evolution attempts show ID
```

Show full details for a specific attempt.

## Human Control

```bash
evolution msg TARGET MESSAGE
evolution msg --all "message to all agents"
evolution msg --role researcher "message to all researchers"
evolution msg agent-1 "focus on temporal reasoning"
```

Send a message to agents. Delivered as a file in their inbox.

```bash
evolution pause AGENT
evolution resume AGENT
```

Pause/resume an agent. Paused agents cannot submit evals.

```bash
evolution kill AGENT
```

Terminate an agent and remove its worktree.

```bash
evolution spawn [--clone AGENT] [--role ROLE] [--runtime RUNTIME]
```

Spawn a new agent mid-session. Use `--clone` to copy config from an existing agent, or `--role` + `--runtime` to create from scratch.

## Agent Name Detection

When running inside a worktree (`.evolution/worktrees/<name>/`), the CLI automatically detects the agent name from the working directory. Agents don't need to pass `--agent` flags.

## Socket Communication

All commands except `init` and `run` send JSON requests to the manager via a Unix domain socket at `.evolution/manager.sock`. If the manager isn't running, commands will fail with "cannot connect to evolution manager."
