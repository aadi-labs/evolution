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

    @staticmethod
    def clean_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Build a clean env: os.environ + overrides, with VIRTUAL_ENV/PYTHONPATH/PYTHONHOME stripped."""
```

## Example: Claude Code Adapter

```python
class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"
    instruction_file = "CLAUDE.md"
    default_runtime_options = {"permission_mode": "dangerously-skip-permissions"}

    def provision(self, worktree_path, agent_config):
        # Write .claude/settings.json with plugins
        settings = {"enabledPlugins": {...}}
        (worktree_path / ".claude" / "settings.json").write_text(json.dumps(settings))

    def write_instructions(self, worktree_path, prompt, task_description):
        (worktree_path / "CLAUDE.md").write_text(f"# Instructions\n{prompt}\n{task_description}")

    def spawn(self, worktree_path, agent_config):
        env = self.clean_env(agent_config.env)
        opts = {**self.default_runtime_options, **agent_config.runtime_options}
        permission_flag = f"--{opts['permission_mode']}"
        return subprocess.Popen(
            ["claude", permission_flag, "-p", "Read CLAUDE.md and begin."],
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

1. **`spawn()` must return a `subprocess.Popen`**: the manager uses `process.poll()` to check health
2. **`provision()` runs before `write_instructions()`**: config files first, then instructions
3. **Instruction file should tell the agent about the `evolution` CLI**: agents need to know how to submit evals and share notes
4. **Use `self.clean_env(agent_config.env)` for subprocess env**: this merges `agent_config.env` onto `os.environ` and strips `VIRTUAL_ENV`, `PYTHONPATH`, `PYTHONHOME` to prevent venv leakage
5. **Derive permission flags from `runtime_options`**: define `default_runtime_options` on your adapter class and merge with `agent_config.runtime_options` in `spawn()`
6. **Messages are delivered via filesystem**: the base class `deliver_message()` handles this; agents should check `.evolution/inbox/`

## Existing Adapters

| Adapter | Runtime | Instruction File | Spawn Command |
|---------|---------|-----------------|---------------|
| `ClaudeCodeAdapter` | `claude-code` | `CLAUDE.md` | `claude --dangerously-skip-permissions -p` |
| `CodexAdapter` | `codex` | `AGENTS.md` | `codex exec --dangerously-bypass-approvals-and-sandbox` |
| `OpenCodeAdapter` | `opencode` | `AGENTS.md` | `opencode` |
