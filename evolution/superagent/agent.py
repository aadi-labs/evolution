"""Superagent spawning logic for the Evolution platform."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from evolution.manager.config import SuperagentConfig
from evolution.superagent.commands import build_superagent_instructions

log = logging.getLogger(__name__)


def spawn_superagent(
    config: SuperagentConfig,
    session_name: str,
    worktree_path: Path,
) -> subprocess.Popen | None:
    """Spawn the superagent as a Claude Code instance.

    Parameters
    ----------
    config:
        Superagent configuration from evolution.yaml.
    session_name:
        Name of the current evolution session.
    worktree_path:
        Path to the worktree where the superagent will operate.

    Returns
    -------
    subprocess.Popen | None
        The spawned process, or None if the superagent is disabled.
    """
    if not config.enabled:
        return None

    # Write CLAUDE.md
    instructions = build_superagent_instructions(session_name)
    (worktree_path / "CLAUDE.md").write_text(instructions)

    log.info(f"Spawning superagent at {worktree_path}")
    return subprocess.Popen(
        ["claude", "--dangerously-skip-permissions"],
        cwd=str(worktree_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
