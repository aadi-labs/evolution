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
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, capture_output=True
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=repo, capture_output=True
    )
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


@pytest.fixture
def manager(git_repo):
    return WorkspaceManager(git_repo)


class TestCreateWorktree:
    def test_worktree_exists(self, manager, git_repo):
        path = manager.create_worktree("alpha")

        assert path.is_dir()
        assert path == git_repo / ".evolution" / "worktrees" / "alpha"

    def test_worktree_has_files(self, manager):
        path = manager.create_worktree("alpha")

        # The worktree should contain the files from the repo
        assert (path / "README.md").exists()
        assert (path / "README.md").read_text() == "# Test"

    def test_worktree_branch_created(self, manager, git_repo):
        manager.create_worktree("alpha")

        result = subprocess.run(
            ["git", "branch", "--list", "evolution/alpha"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert "evolution/alpha" in result.stdout


class TestCreateSharedDir:
    def test_shared_dir_created(self, manager, git_repo):
        shared = manager.create_shared_dir()

        assert shared == git_repo / ".evolution" / "shared"
        assert shared.is_dir()

    def test_subdirs_exist(self, manager):
        shared = manager.create_shared_dir()

        assert (shared / "attempts").is_dir()
        assert (shared / "notes").is_dir()
        assert (shared / "skills").is_dir()


class TestLinkShared:
    def test_symlink_created(self, manager):
        wt = manager.create_worktree("alpha")
        shared = manager.create_shared_dir()

        manager.link_shared(wt, shared)

        link = wt / ".evolution" / "shared"
        assert link.is_symlink()
        assert link.resolve() == shared.resolve()


class TestCreateInbox:
    def test_inbox_created(self, manager):
        wt = manager.create_worktree("alpha")
        inbox = manager.create_inbox(wt)

        assert inbox.is_dir()
        assert inbox == wt / ".evolution" / "inbox"


class TestCopySeed:
    def test_seed_files_copied(self, manager, tmp_path):
        wt = manager.create_worktree("alpha")

        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "config.yaml").write_text("key: value")
        (seed / "data").mkdir()
        (seed / "data" / "input.txt").write_text("hello")

        manager.copy_seed(wt, seed)

        assert (wt / "config.yaml").read_text() == "key: value"
        assert (wt / "data" / "input.txt").read_text() == "hello"


class TestTeardownWorktree:
    def test_worktree_removed(self, manager, git_repo):
        manager.create_worktree("alpha")
        manager.teardown_worktree("alpha")

        wt_path = git_repo / ".evolution" / "worktrees" / "alpha"
        assert not wt_path.exists()

    def test_branch_deleted(self, manager, git_repo):
        manager.create_worktree("alpha")
        manager.teardown_worktree("alpha")

        result = subprocess.run(
            ["git", "branch", "--list", "evolution/alpha"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert "evolution/alpha" not in result.stdout
