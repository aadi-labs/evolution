"""Base adapter interface for Evolution agent runtimes."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evolution.manager.config import AgentConfig


def clean_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build a process environment with Evolution's own venv vars stripped.

    Parameters
    ----------
    overrides:
        Extra env vars to merge on top of ``os.environ``.
        Pass ``agent_config.env`` here.
    """
    base = {**os.environ, **(overrides or {})}
    for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        base.pop(key, None)
    return base


class AgentAdapter:
    """Abstract base class that encapsulates runtime-specific details.

    Each concrete adapter (Claude Code, Codex, OpenCode, etc.) implements
    the three abstract methods to provision configuration files, write
    instruction files, and spawn the agent process.
    """

    name: str = ""
    instruction_file: str = ""

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """Write runtime-specific configuration into *worktree_path*.

        Parameters
        ----------
        worktree_path:
            Root of the git worktree the agent will operate in.
        agent_config:
            The agent's declared configuration.
        """
        raise NotImplementedError

    def write_instructions(
        self, worktree_path: Path, prompt: str, task_description: str
    ) -> None:
        """Write the instruction / system-prompt file for the runtime.

        Parameters
        ----------
        worktree_path:
            Root of the git worktree the agent will operate in.
        prompt:
            The role prompt for this agent.
        task_description:
            Human-readable description of the task.
        """
        raise NotImplementedError

    def spawn(
        self, worktree_path: Path, agent_config: AgentConfig
    ) -> subprocess.Popen:
        """Start the agent process inside *worktree_path*.

        Parameters
        ----------
        worktree_path:
            Root of the git worktree the agent will operate in.
        agent_config:
            The agent's declared configuration.

        Returns
        -------
        subprocess.Popen
            The running agent process handle.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def deliver_message(
        self, worktree_path: Path, agent_name: str, message: str
    ) -> Path:
        """Write a message into the agent's inbox as a timestamped .md file.

        Parameters
        ----------
        worktree_path:
            Root of the git worktree the agent operates in.
        agent_name:
            Name of the sending agent (used in the filename).
        message:
            The message body to deliver.

        Returns
        -------
        Path
            The path to the newly created message file.
        """
        inbox = worktree_path / ".evolution" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%f")
        filename = f"{timestamp}-{agent_name}.md"
        msg_path = inbox / filename
        # Atomic write: write to temp file then rename so readers never see partial content
        tmp_path = msg_path.with_suffix(".tmp")
        tmp_path.write_text(message)
        tmp_path.rename(msg_path)
        return msg_path

    def consolidate_inbox(self, worktree_path: Path) -> Path | None:
        """Consolidate all inbox messages into a single digest file.

        Returns the digest path, or None if consolidation wasn't needed.
        """
        inbox = worktree_path / ".evolution" / "inbox"
        if not inbox.exists():
            return None

        messages = sorted(inbox.glob("*.md"))
        if len(messages) <= 1:
            return None

        # Build digest from all messages
        lines = []
        for msg_path in messages:
            lines.append(msg_path.read_text().strip())
            msg_path.unlink()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        digest_path = inbox / f"DIGEST-{timestamp}.md"
        digest_path.write_text("\n\n---\n\n".join(lines))
        return digest_path

    @staticmethod
    def clean_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Delegate to module-level ``clean_env``."""
        return clean_env(overrides)
