import subprocess
from pathlib import Path

from evolution.workspace.discovery import discover_untracked_dirs


class TestDiscoverUntrackedDirs:
    def test_discovers_venv(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, capture_output=True)
        (repo / ".gitignore").write_text(".venv/\nnode_modules/\n")
        (repo / "main.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        (repo / ".venv").mkdir()
        (repo / ".venv" / "bin").mkdir()
        (repo / "node_modules").mkdir()

        dirs = discover_untracked_dirs(repo)
        assert ".venv" in dirs
        assert "node_modules" in dirs

    def test_skips_nested_under_parent(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, capture_output=True)
        (repo / ".gitignore").write_text(".venv/\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
        (repo / ".venv").mkdir()
        (repo / ".venv" / "lib").mkdir()

        dirs = discover_untracked_dirs(repo)
        assert ".venv" in dirs
        assert not any("lib" in d for d in dirs)

    def test_empty_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, capture_output=True)
        (repo / "main.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        dirs = discover_untracked_dirs(repo)
        assert dirs == []
