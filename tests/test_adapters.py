"""Tests for the Evolution adapter layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from evolution.adapters.base import AgentAdapter
from evolution.adapters.claude_code import ClaudeCodeAdapter
from evolution.manager.config import AgentConfig, RestartConfig

import json


def _make_agent_config(**overrides) -> AgentConfig:
    """Helper to create an AgentConfig with sensible defaults."""
    defaults = dict(
        role="explorer",
        runtime="claude-code",
        skills=["skill-a"],
        plugins=["plugin-b"],
        mcp_servers=["server-c"],
        env={"FOO": "bar"},
        restart=RestartConfig(),
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestClaudeCodeAdapterAttributes:
    def test_instruction_file(self):
        adapter = ClaudeCodeAdapter()
        assert adapter.instruction_file == "CLAUDE.md"

    def test_name(self):
        adapter = ClaudeCodeAdapter()
        assert adapter.name == "claude-code"


class TestWriteInstructions:
    def test_creates_claude_md_with_content(self, tmp_path: Path):
        adapter = ClaudeCodeAdapter()
        adapter.write_instructions(
            tmp_path,
            prompt="You are a bold explorer.",
            task_description="Improve test coverage to 90%.",
        )

        md_path = tmp_path / "CLAUDE.md"
        assert md_path.exists()

        content = md_path.read_text()
        assert "You are a bold explorer." in content
        assert "Improve test coverage to 90%." in content
        assert "evolution eval" in content


class TestProvision:
    def test_writes_settings_json(self, tmp_path: Path):
        adapter = ClaudeCodeAdapter()
        config = _make_agent_config()

        adapter.provision(tmp_path, config)

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()

        data = json.loads(settings_path.read_text())
        # Plugins use "name@registry" format
        assert "plugin-b@claude-plugins-official" in data["enabledPlugins"]
        # Skills map to their parent plugins
        assert "skill-a@claude-plugins-official" in data["enabledPlugins"]
        # MCP servers go to .mcp.json
        mcp_path = tmp_path / ".mcp.json"
        assert mcp_path.exists()
        mcp_data = json.loads(mcp_path.read_text())
        assert "server-c" in mcp_data["mcpServers"]


class TestDeliverMessage:
    def test_creates_timestamped_md_in_inbox(self, tmp_path: Path):
        adapter = ClaudeCodeAdapter()
        msg_path = adapter.deliver_message(
            tmp_path, agent_name="alice", message="Hello from alice"
        )

        assert msg_path.exists()
        assert msg_path.suffix == ".md"
        assert msg_path.parent == tmp_path / ".evolution" / "inbox"
        assert "alice" in msg_path.name

    def test_message_content(self, tmp_path: Path):
        adapter = ClaudeCodeAdapter()
        msg_path = adapter.deliver_message(
            tmp_path, agent_name="bob", message="Important update"
        )

        content = msg_path.read_text()
        assert "Important update" in content


class TestSpawn:
    def test_spawn_calls_claude_cli(self, tmp_path: Path):
        adapter = ClaudeCodeAdapter()
        config = _make_agent_config(env={"CUSTOM": "val"})

        with patch("evolution.adapters.claude_code.subprocess.Popen") as mock_popen:
            adapter.spawn(tmp_path, config)

            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd = args[0]
            assert cmd[0] == "claude"
            assert "--dangerously-skip-permissions" in cmd
            assert "-p" in cmd
            assert kwargs["cwd"] == str(tmp_path)
            assert kwargs["env"]["CUSTOM"] == "val"

    def test_spawn_empty_env_inherits_os_environ(self, tmp_path: Path):
        adapter = ClaudeCodeAdapter()
        config = _make_agent_config(env={})

        with patch("evolution.adapters.claude_code.subprocess.Popen") as mock_popen:
            adapter.spawn(tmp_path, config)

            _, kwargs = mock_popen.call_args
            # Empty env still merges with os.environ (agents inherit parent env)
            assert isinstance(kwargs["env"], dict)


class TestBaseAdapterRaisesNotImplemented:
    def test_provision(self, tmp_path: Path):
        adapter = AgentAdapter()
        config = _make_agent_config()
        try:
            adapter.provision(tmp_path, config)
            assert False, "Should have raised NotImplementedError"
        except NotImplementedError:
            pass

    def test_write_instructions(self, tmp_path: Path):
        adapter = AgentAdapter()
        try:
            adapter.write_instructions(tmp_path, "prompt", "desc")
            assert False, "Should have raised NotImplementedError"
        except NotImplementedError:
            pass

    def test_spawn(self, tmp_path: Path):
        adapter = AgentAdapter()
        config = _make_agent_config()
        try:
            adapter.spawn(tmp_path, config)
            assert False, "Should have raised NotImplementedError"
        except NotImplementedError:
            pass
