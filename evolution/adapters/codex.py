"""Codex adapter for the Evolution platform."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import INSTRUCTION_TEMPLATE
from evolution.manager.config import AgentConfig


class CodexAdapter(AgentAdapter):
    """Adapter for the Codex CLI runtime."""

    name: str = "codex"
    instruction_file: str = "AGENTS.md"

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """No-op — Codex reads AGENTS.md directly."""

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
        """Start ``codex exec`` (non-interactive) in the worktree."""
        env = {**os.environ, **agent_config.env} if agent_config.env else None

        # Read the instruction file as the initial prompt
        instruction_path = worktree_path / self.instruction_file
        prompt = instruction_path.read_text() if instruction_path.exists() else "Start working."

        return subprocess.Popen(
            ["codex", "exec", prompt],
            cwd=str(worktree_path),
            env=env,
        )
