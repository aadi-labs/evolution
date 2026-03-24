"""Tests for evolution.superagent — instructions builder and agent spawning."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from evolution.manager.config import SuperagentConfig
from evolution.superagent.commands import build_superagent_instructions
from evolution.superagent.agent import spawn_superagent


# =========================================================================
# build_superagent_instructions
# =========================================================================


def test_superagent_instructions_include_cli_commands():
    """Instructions must mention all key CLI commands."""
    instructions = build_superagent_instructions(session_name="test-run")
    assert "evolution status" in instructions
    assert "evolution msg" in instructions
    assert "evolution attempts" in instructions
    assert "evolution pause" in instructions
    assert "evolution spawn" in instructions
    assert "evolution kill" in instructions


def test_superagent_instructions_contain_session_name():
    """The session name must appear in the generated instructions."""
    instructions = build_superagent_instructions(session_name="my-session-42")
    assert "my-session-42" in instructions


# =========================================================================
# spawn_superagent
# =========================================================================


def test_spawn_superagent_returns_none_when_disabled():
    """When config.enabled is False, spawn_superagent returns None."""
    config = SuperagentConfig(enabled=False)
    result = spawn_superagent(config, session_name="s", worktree_path=Path("/tmp"))
    assert result is None


@patch("evolution.superagent.agent.subprocess.Popen")
def test_spawn_superagent_writes_claude_md(mock_popen: MagicMock, tmp_path: Path):
    """When enabled, spawn_superagent writes CLAUDE.md and spawns a process."""
    mock_popen.return_value = MagicMock()
    config = SuperagentConfig(enabled=True)

    proc = spawn_superagent(config, session_name="test-run", worktree_path=tmp_path)

    # CLAUDE.md was written
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert "test-run" in content
    assert "evolution status" in content

    # Popen was called correctly
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args
    assert call_args[0][0] == ["claude", "--dangerously-skip-permissions"]
    assert call_args[1]["cwd"] == str(tmp_path)
    assert call_args[1]["stdin"] is not None
    assert call_args[1]["stdout"] is not None
    assert call_args[1]["stderr"] is not None

    # Return value is the mock Popen instance
    assert proc is mock_popen.return_value
