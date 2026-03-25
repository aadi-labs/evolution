"""Tests for evolution.workspace.setup.WorkspaceManager."""

import subprocess
from pathlib import Path

import pytest

from evolution.workspace.setup import WorkspaceManager


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# Test")
    (repo / ".gitignore").write_text(".venv/\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    (repo / ".venv").mkdir()
    (repo / ".venv" / "bin").mkdir()
    (repo / ".venv" / "bin" / "python").write_text("#!/usr/bin/env python3")
    return repo


class TestCreateWorktreeGitWorktree:
    @pytest.fixture
    def manager(self, git_repo):
        return WorkspaceManager(git_repo, strategy="git_worktree")

    def test_worktree_exists(self, manager, git_repo):
        path = manager.create_worktree("alpha")
        assert path.is_dir()
        assert path == git_repo / ".evolution" / "worktrees" / "alpha"

    def test_worktree_has_files(self, manager):
        path = manager.create_worktree("alpha")
        assert (path / "README.md").exists()
        assert (path / "README.md").read_text() == "# Test"

    def test_branch_created(self, manager, git_repo):
        manager.create_worktree("alpha")
        result = subprocess.run(
            ["git", "branch", "--list", "evolution/alpha"],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert "evolution/alpha" in result.stdout

    def test_deps_symlinked(self, manager):
        path = manager.create_worktree("alpha")
        assert (path / ".venv").exists()
        assert (path / ".venv").is_symlink()

    def test_teardown_removes_branch(self, manager, git_repo):
        manager.create_worktree("alpha")
        manager.teardown_worktree("alpha")
        result = subprocess.run(
            ["git", "branch", "--list", "evolution/alpha"],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert "evolution/alpha" not in result.stdout

    def test_teardown_removes_dir(self, manager, git_repo):
        manager.create_worktree("alpha")
        manager.teardown_worktree("alpha")
        assert not (git_repo / ".evolution" / "worktrees" / "alpha").exists()


class TestCreateWorktreeReflink:
    @pytest.fixture
    def manager(self, git_repo):
        return WorkspaceManager(git_repo, strategy="reflink")

    def test_worktree_exists(self, manager, git_repo):
        path = manager.create_worktree("alpha")
        assert path.is_dir()

    def test_worktree_has_files(self, manager):
        path = manager.create_worktree("alpha")
        assert (path / "README.md").exists()
        assert (path / "README.md").read_text() == "# Test"

    def test_deps_copied(self, manager):
        path = manager.create_worktree("alpha")
        assert (path / ".venv").exists()
        assert (path / ".venv" / "bin" / "python").exists()
        assert not (path / ".venv").is_symlink()  # reflink, not symlink

    def test_no_git_dir(self, manager):
        path = manager.create_worktree("alpha")
        assert not (path / ".git").exists()

    def test_no_evolution_dir(self, git_repo):
        (git_repo / ".evolution").mkdir(exist_ok=True)
        (git_repo / ".evolution" / "state.json").write_text("{}")
        mgr = WorkspaceManager(git_repo, strategy="reflink")
        path = mgr.create_worktree("alpha")
        assert not (path / ".evolution" / "state.json").exists()

    def test_teardown_removes_dir(self, manager, git_repo):
        manager.create_worktree("alpha")
        manager.teardown_worktree("alpha")
        assert not (git_repo / ".evolution" / "worktrees" / "alpha").exists()


class TestSharedDir:
    def test_shared_dir_created(self, git_repo):
        mgr = WorkspaceManager(git_repo, strategy="git_worktree")
        shared = mgr.create_shared_dir()
        assert shared == git_repo / ".evolution" / "shared"
        assert (shared / "attempts").is_dir()
        assert (shared / "notes").is_dir()
        assert (shared / "skills").is_dir()


class TestLinkShared:
    def test_symlink_created(self, git_repo):
        mgr = WorkspaceManager(git_repo, strategy="git_worktree")
        wt = mgr.create_worktree("alpha")
        shared = mgr.create_shared_dir()
        mgr.link_shared(wt, shared)
        link = wt / ".evolution" / "shared"
        assert link.is_symlink()
        assert link.resolve() == shared.resolve()


class TestCreateInbox:
    def test_inbox_created(self, git_repo):
        mgr = WorkspaceManager(git_repo, strategy="git_worktree")
        wt = mgr.create_worktree("alpha")
        inbox = mgr.create_inbox(wt)
        assert inbox.is_dir()
        assert inbox == wt / ".evolution" / "inbox"


class TestCopySeed:
    def test_seed_files_copied(self, git_repo, tmp_path):
        mgr = WorkspaceManager(git_repo, strategy="git_worktree")
        wt = mgr.create_worktree("alpha")
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "config.yaml").write_text("key: value")
        mgr.copy_seed(wt, seed)
        assert (wt / "config.yaml").read_text() == "key: value"
