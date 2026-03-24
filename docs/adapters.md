# Writing an Adapter

Adapters let Evolution spawn and manage agents on different runtimes. To add a new runtime, create a class that implements the `AgentAdapter` interface.

## Interface

```python
# evolution/adapters/base.py

class AgentAdapter:
    name: str                  # Runtime identifier (e.g., "my-runtime")
    instruction_file: str      # File name for agent instructions (e.g., "AGENT.md")

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """Write runtime-specific config files into the worktree."""

    def write_instructions(self, worktree_path: Path, prompt: str, task_description: str) -> None:
        """Write the instruction file the agent reads on startup."""

    def spawn(self, worktree_path: Path, agent_config: AgentConfig) -> subprocess.Popen:
        """Start the agent process. Return the Popen handle."""

    def deliver_message(self, worktree_path: Path, sender: str, message: str) -> Path:
        """Write a message to the agent's inbox. (Inherited from base class.)"""
```

## Example: Claude Code Adapter

```python
class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"
    instruction_file = "CLAUDE.md"

    def provision(self, worktree_path, agent_config):
        # Write .claude/settings.json with plugins
        settings = {"enabledPlugins": {...}}
        (worktree_path / ".claude" / "settings.json").write_text(json.dumps(settings))

    def write_instructions(self, worktree_path, prompt, task_description):
        (worktree_path / "CLAUDE.md").write_text(f"# Instructions\n{prompt}\n{task_description}")

    def spawn(self, worktree_path, agent_config):
        env = {**os.environ, **(agent_config.env or {})}
        return subprocess.Popen(
            ["claude", "--dangerously-skip-permissions", "-p", "Read CLAUDE.md and begin."],
            cwd=str(worktree_path),
            env=env,
        )
```

## Registering the Adapter

Add it to the `ADAPTERS` dict in `evolution/manager/manager.py`:

```python
from evolution.adapters.my_runtime import MyRuntimeAdapter

ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
    "my-runtime": MyRuntimeAdapter,   # <-- add here
}
```

Then use it in `evolution.yaml`:

```yaml
agents:
  agent-1:
    role: researcher
    runtime: my-runtime
```

## Key Requirements

1. **`spawn()` must return a `subprocess.Popen`** — the manager uses `process.poll()` to check health
2. **`provision()` runs before `write_instructions()`** — config files first, then instructions
3. **Instruction file should tell the agent about the `evolution` CLI** — agents need to know how to submit evals and share notes
4. **Environment variables pass through** — `agent_config.env` merges with `os.environ`
5. **Messages are delivered via filesystem** — the base class `deliver_message()` handles this; agents should check `.evolution/inbox/`

## Existing Adapters

| Adapter | Runtime | Instruction File | Spawn Command |
|---------|---------|-----------------|---------------|
| `ClaudeCodeAdapter` | `claude-code` | `CLAUDE.md` | `claude --dangerously-skip-permissions -p` |
| `CodexAdapter` | `codex` | `AGENTS.md` | `codex --full-auto` |
| `OpenCodeAdapter` | `opencode` | `AGENTS.md` | `opencode` |
