"""Tests for the Codex and OpenCode adapters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from evolution.adapters.codex import CodexAdapter
from evolution.adapters.opencode import OpenCodeAdapter
from evolution.manager.config import AgentConfig, RestartConfig


def _make_agent_config(**overrides) -> AgentConfig:
    """Helper to create an AgentConfig with sensible defaults."""
    defaults = dict(
        role="explorer",
        runtime="codex",
        skills=[],
        plugins=[],
        mcp_servers=[],
        env={"CUSTOM": "val"},
        restart=RestartConfig(),
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


class TestCodexAdapterAttributes:
    def test_instruction_file(self):
        adapter = CodexAdapter()
        assert adapter.instruction_file == "AGENTS.md"

    def test_name(self):
        adapter = CodexAdapter()
        assert adapter.name == "codex"


class TestCodexWriteInstructions:
    def test_creates_agents_md_with_content(self, tmp_path: Path):
        adapter = CodexAdapter()
        adapter.write_instructions(
            tmp_path,
            prompt="You are a bold explorer.",
            task_description="Improve test coverage to 90%.",
        )

        md_path = tmp_path / "AGENTS.md"
        assert md_path.exists()

        content = md_path.read_text()
        assert "You are a bold explorer." in content
        assert "Improve test coverage to 90%." in content
        assert "evolution eval" in content


class TestCodexProvision:
    def test_provision_is_noop(self, tmp_path: Path):
        adapter = CodexAdapter()
        config = _make_agent_config()
        # Should not raise and should not create any files
        adapter.provision(tmp_path, config)
        # No .claude directory or settings should be created
        assert not (tmp_path / ".claude").exists()


class TestCodexSpawn:
    def test_spawn_calls_codex_cli(self, tmp_path: Path):
        adapter = CodexAdapter()
        config = _make_agent_config(env={"CUSTOM": "val"})

        with patch("evolution.adapters.codex.subprocess.Popen") as mock_popen:
            adapter.spawn(tmp_path, config)

            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            cmd = args[0]
            assert cmd[0] == "codex"
            assert cmd[1] == "exec"
            assert kwargs["cwd"] == str(tmp_path)
            assert kwargs["env"]["CUSTOM"] == "val"

    def test_spawn_no_env_passes_none(self, tmp_path: Path):
        adapter = CodexAdapter()
        config = _make_agent_config(env={})

        with patch("evolution.adapters.codex.subprocess.Popen") as mock_popen:
            adapter.spawn(tmp_path, config)

            _, kwargs = mock_popen.call_args
            assert kwargs["env"] is None


class TestOpenCodeAdapterAttributes:
    def test_instruction_file(self):
        adapter = OpenCodeAdapter()
        assert adapter.instruction_file == "AGENTS.md"

    def test_name(self):
        adapter = OpenCodeAdapter()
        assert adapter.name == "opencode"


class TestOpenCodeWriteInstructions:
    def test_creates_agents_md_with_content(self, tmp_path: Path):
        adapter = OpenCodeAdapter()
        adapter.write_instructions(
            tmp_path,
            prompt="You are a careful analyst.",
            task_description="Reduce latency by 50%.",
        )

        md_path = tmp_path / "AGENTS.md"
        assert md_path.exists()

        content = md_path.read_text()
        assert "You are a careful analyst." in content
        assert "Reduce latency by 50%." in content
        assert "evolution eval" in content


class TestOpenCodeProvision:
    def test_provision_is_noop(self, tmp_path: Path):
        adapter = OpenCodeAdapter()
        config = _make_agent_config(runtime="opencode")
        adapter.provision(tmp_path, config)
        assert not (tmp_path / ".claude").exists()


class TestOpenCodeSpawn:
    def test_spawn_calls_opencode_cli(self, tmp_path: Path):
        adapter = OpenCodeAdapter()
        config = _make_agent_config(runtime="opencode", env={"KEY": "value"})

        with patch("evolution.adapters.opencode.subprocess.Popen") as mock_popen:
            adapter.spawn(tmp_path, config)

            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            assert args[0] == ["opencode"]
            assert kwargs["cwd"] == str(tmp_path)
            assert kwargs["env"]["KEY"] == "value"

    def test_spawn_no_env_passes_none(self, tmp_path: Path):
        adapter = OpenCodeAdapter()
        config = _make_agent_config(runtime="opencode", env={})

        with patch("evolution.adapters.opencode.subprocess.Popen") as mock_popen:
            adapter.spawn(tmp_path, config)

            _, kwargs = mock_popen.call_args
            assert kwargs["env"] is None
