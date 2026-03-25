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

Submit current worktree state for grading. When an eval queue is configured, returns immediately with a queue position — results arrive in the agent's inbox. Without a queue, grades synchronously.

```bash
evolution note add "text" [--tags tag1,tag2]
```

Share a finding with all agents. Use structured tags: `technique`, `dead-end`, `paper`, `competitor`, `finding`, `working-on`, `done`.

```bash
evolution notes list [--agent NAME] [--tag TAG]
```

List all shared notes, optionally filtered by agent and/or tag.

```bash
evolution claims
```

Show active work claims across all agents. Agents post `WORKING ON:` notes (or `--tags working-on`); `claims` shows which are still active.

```bash
evolution diff AGENT
```

Show another agent's code changes relative to HEAD. Returns `git diff` output from their worktree.

```bash
evolution cherry-pick AGENT FILE
```

Copy a file from another agent's worktree into your own. The calling agent is detected automatically from the working directory. Path traversal is rejected.

```bash
evolution hypothesis add "text" [--metric METRIC]
evolution hypothesis list [--status open|validated|invalidated]
evolution hypothesis resolve ID --validated|--invalidated --evidence "..."
```

Track structured hypotheses. Agents post predictions, test them, and resolve with evidence. Open hypotheses are visible to all agents.

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

```bash
evolution merge [--agent NAME] [--branch BRANCH] [--dry-run]
```

Create a new git branch with the winning agent's changes and a generated changelog. Without `--agent`, picks the best-scoring agent. `--dry-run` shows the changelog and file count without creating the branch. The commit message includes top attempts, key findings, and hypothesis resolutions.

## Agent Name Detection

When running inside a worktree (`.evolution/worktrees/<name>/`), the CLI automatically detects the agent name from the working directory. Agents don't need to pass `--agent` flags.

## Socket Communication

All commands except `init` and `run` send JSON requests to the manager via a Unix domain socket at `.evolution/manager.sock`. If the manager isn't running, commands will fail with "cannot connect to evolution manager."
