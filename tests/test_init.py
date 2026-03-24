"""Tests for ``evolution init`` command."""

import subprocess
from pathlib import Path

import pytest
import yaml

from evolution.cli.main import build_parser
from evolution.cli.init import cmd_init


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "myproject"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, capture_output=True)
    (repo / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


class TestParser:
    def test_init_with_eval(self):
        parser = build_parser()
        args = parser.parse_args(["init", "--eval", "pytest tests/"])
        assert args.command == "init"
        assert args.eval == "pytest tests/"
        assert args.repo == "."

    def test_init_with_repo_and_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "init", "/path/to/repo",
            "--eval", "./run_eval.sh",
            "--name", "my-project",
            "--direction", "lower_is_better",
            "--agents", "claude-code,codex",
        ])
        assert args.repo == "/path/to/repo"
        assert args.name == "my-project"
        assert args.direction == "lower_is_better"
        assert args.agents == "claude-code,codex"


class TestCmdInit:
    def test_creates_evolution_yaml(self, git_repo):
        parser = build_parser()
        args = parser.parse_args(["init", str(git_repo), "--eval", "pytest tests/ -v"])
        cmd_init(args)

        config_path = git_repo / "evolution.yaml"
        assert config_path.exists()
        config = yaml.safe_load(config_path.read_text())
        assert config["session"]["name"] == "myproject"
        assert config["task"]["description"] is not None
        assert "pytest" in config["task"]["description"]

    def test_creates_grader_script(self, git_repo):
        parser = build_parser()
        args = parser.parse_args(["init", str(git_repo), "--eval", "python run_eval.py"])
        cmd_init(args)

        grader = git_repo / "evolution_grader.py"
        assert grader.exists()
        content = grader.read_text()
        assert "python run_eval.py" in content

    def test_grader_is_executable(self, git_repo):
        parser = build_parser()
        args = parser.parse_args(["init", str(git_repo), "--eval", "echo 42"])
        cmd_init(args)

        grader = git_repo / "evolution_grader.py"
        assert grader.stat().st_mode & 0o111  # executable bit set

    def test_custom_agents(self, git_repo):
        parser = build_parser()
        args = parser.parse_args([
            "init", str(git_repo),
            "--eval", "pytest",
            "--agents", "claude-code,codex,opencode",
        ])
        cmd_init(args)

        config = yaml.safe_load((git_repo / "evolution.yaml").read_text())
        agent_names = list(config["agents"].keys())
        assert len(agent_names) == 3
        runtimes = [config["agents"][a]["runtime"] for a in agent_names]
        assert "claude-code" in runtimes
        assert "codex" in runtimes
        assert "opencode" in runtimes

    def test_direction_lower_is_better(self, git_repo):
        parser = build_parser()
        args = parser.parse_args([
            "init", str(git_repo),
            "--eval", "python eval.py",
            "--direction", "lower_is_better",
        ])
        cmd_init(args)

        config = yaml.safe_load((git_repo / "evolution.yaml").read_text())
        assert config["task"]["metric"]["direction"] == "lower_is_better"

    def test_fails_on_non_git_dir(self, tmp_path):
        parser = build_parser()
        args = parser.parse_args(["init", str(tmp_path), "--eval", "pytest"])
        with pytest.raises(SystemExit):
            cmd_init(args)

    def test_superagent_enabled_by_default(self, git_repo):
        parser = build_parser()
        args = parser.parse_args(["init", str(git_repo), "--eval", "pytest"])
        cmd_init(args)

        config = yaml.safe_load((git_repo / "evolution.yaml").read_text())
        assert config["superagent"]["enabled"] is True

    def test_claude_code_gets_superpowers(self, git_repo):
        parser = build_parser()
        args = parser.parse_args(["init", str(git_repo), "--eval", "pytest"])
        cmd_init(args)

        config = yaml.safe_load((git_repo / "evolution.yaml").read_text())
        claude_agents = [
            a for a in config["agents"].values()
            if a["runtime"] == "claude-code"
        ]
        assert len(claude_agents) > 0
        assert "superpowers" in claude_agents[0].get("skills", [])
