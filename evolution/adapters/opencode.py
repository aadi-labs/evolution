"""OpenCode adapter for the Evolution platform."""

from __future__ import annotations

import subprocess
from pathlib import Path

from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import INSTRUCTION_TEMPLATE
from evolution.manager.config import AgentConfig


class OpenCodeAdapter(AgentAdapter):
    """Adapter for the OpenCode CLI runtime."""

    name: str = "opencode"
    instruction_file: str = "AGENTS.md"

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """No-op — OpenCode reads AGENTS.md directly."""

    def write_instructions(
        self, worktree_path: Path, prompt: str, task_description: str
    ) -> None:
        """Write ``AGENTS.md`` from the instruction template."""
        instruction_path = worktree_path / self.instruction_file
        instruction_path.write_text(
            INSTRUCTION_TEMPLATE.format(
                prompt=prompt, task_description=task_description
            )
        )

    def spawn(
        self, worktree_path: Path, agent_config: AgentConfig
    ) -> subprocess.Popen:
        """Start ``opencode`` in the worktree."""
        env = self.clean_env(agent_config.env)

        return subprocess.Popen(
            ["opencode"],
            cwd=str(worktree_path),
            env=env,
        )
