"""Claude Code adapter for the Evolution platform."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from evolution.adapters.base import AgentAdapter
from evolution.manager.config import AgentConfig

INSTRUCTION_TEMPLATE = """\
# Agent Instructions

## Your Role
{prompt}

## Task
{task_description}

## How to Work
- Make changes to the code in this directory
- Submit with: `evolution eval -m "description of what you changed"`
- Read others' work: `evolution attempts list`, `evolution notes list`
- Share insights: `evolution note add "your insight"`
- Publish reusable techniques: `evolution skill add skill-name.md`
- Check your inbox before each new approach: `.evolution/inbox/`
- Check your inbox after each eval submission

## Constraints
- You will receive heartbeat prompts — reflect and share when asked
- Prioritize messages from the user over your current work
"""


class ClaudeCodeAdapter(AgentAdapter):
    """Adapter for the Claude Code CLI runtime."""

    name: str = "claude-code"
    instruction_file: str = "CLAUDE.md"

    def provision(self, worktree_path: Path, agent_config: AgentConfig) -> None:
        """Write ``.claude/settings.json`` with plugins and ``.mcp.json`` with MCP servers.

        Claude Code settings format:
        - Plugins: ``{"enabledPlugins": {"name@registry": true}}``
        - MCP servers: ``.mcp.json`` at worktree root
        - Skills: provisioned via enabled plugins (skills belong to plugins)
        """
        settings_dir = worktree_path / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)

        # Enable plugins — combine explicit plugins + skill-bearing plugins
        enabled_plugins = {}
        for plugin in agent_config.plugins:
            # If already in "name@registry" format, use as-is
            if "@" in plugin:
                enabled_plugins[plugin] = True
            else:
                # Default to claude-plugins-official registry
                enabled_plugins[f"{plugin}@claude-plugins-official"] = True

        # Skills are provided by plugins — enable their parent plugins too
        # Common skill-to-plugin mappings
        skill_plugin_map = {
            "superpowers": "superpowers@claude-plugins-official",
            "alphaxiv-paper-lookup": "alphaxiv-paper-lookup@claude-plugins-official",
            "feature-dev": "feature-dev@claude-plugins-official",
        }
        for skill in agent_config.skills:
            plugin_id = skill_plugin_map.get(skill, f"{skill}@claude-plugins-official")
            enabled_plugins[plugin_id] = True

        settings = {}
        if enabled_plugins:
            settings["enabledPlugins"] = enabled_plugins

        settings_path = settings_dir / "settings.json"
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

        # MCP servers — write .mcp.json at worktree root
        if agent_config.mcp_servers:
            mcp_config = {"mcpServers": {}}
            for server in agent_config.mcp_servers:
                # Placeholder config — users should customize per server
                mcp_config["mcpServers"][server] = {
                    "command": server,
                    "args": [],
                }
            mcp_path = worktree_path / ".mcp.json"
            mcp_path.write_text(json.dumps(mcp_config, indent=2) + "\n")

    def write_instructions(
        self, worktree_path: Path, prompt: str, task_description: str
    ) -> None:
        """Write ``CLAUDE.md`` from the instruction template."""
        instruction_path = worktree_path / self.instruction_file
        instruction_path.write_text(
            INSTRUCTION_TEMPLATE.format(
                prompt=prompt, task_description=task_description
            )
        )

    def spawn(
        self, worktree_path: Path, agent_config: AgentConfig
    ) -> subprocess.Popen:
        """Start ``claude`` in print mode in the worktree.

        Claude Code runs a full agentic loop in ``--print`` mode (tool
        calls, file edits, bash commands) and handles context compaction
        internally.  The agent should keep working autonomously for the
        entire evolution session without needing restarts.
        """
        env = {**os.environ, **(agent_config.env or {})}

        prompt = (
            "You are an autonomous evolution agent. Read CLAUDE.md for your full instructions.\n\n"
            "This is a LONG-RUNNING session. You must keep working continuously:\n"
            "1. Read CLAUDE.md and .evolution/shared/memory/ for context\n"
            "2. Check evolution notes list and .evolution/inbox/ for messages\n"
            "3. Research, implement, test, evaluate, share findings\n"
            "4. After each eval, start the next improvement immediately\n"
            "5. NEVER stop working. There is always more to improve.\n"
            "6. If you run out of ideas, read shared notes and try a different approach.\n\n"
            "Your loop: research → plan → implement → test → eval → share → repeat. Forever."
        )

        return subprocess.Popen(
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
            cwd=str(worktree_path),
            env=env,
        )
