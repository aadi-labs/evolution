"""Adaptive workspace manager for creating isolated agent workspaces.

Auto-detects filesystem capabilities:
- Path A (reflink): Copy-on-write clone on APFS/btrfs — near-zero disk cost,
  includes all deps and caches.
- Path B (git worktree): Git worktree on ext4/NTFS with auto-discovered
  symlinks for gitignored directories.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from evolution.workspace.discovery import discover_untracked_dirs
from evolution.workspace.reflink import (
    ReflinkCopier,
    detect_reflink_support,
    warm_disk_cache,
)

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Creates isolated workspaces using the best available strategy."""

    def __init__(self, repo_root: Path, strategy: str = "auto") -> None:
        self.repo_root = repo_root
        self.evolution_dir = repo_root / ".evolution"
        self.worktrees_dir = self.evolution_dir / "worktrees"
        self._strategy = self._resolve_strategy(strategy)
        self._copier = ReflinkCopier() if self._strategy == "reflink" else None
        logger.info("Workspace strategy: %s", self._strategy)

    @property
    def strategy(self) -> str:
        return self._strategy

    def _resolve_strategy(self, strategy: str) -> str:
        if strategy != "auto":
            return strategy
        if detect_reflink_support(self.repo_root):
            return "reflink"
        return "git_worktree"

    def create_worktree(self, agent_name: str) -> Path:
        """Create an isolated workspace for an agent."""
        worktree_path = self.worktrees_dir / agent_name

        if worktree_path.exists():
            self.teardown_worktree(agent_name)

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        if self._strategy == "reflink":
            self._create_reflink(agent_name, worktree_path)
        else:
            self._create_git_worktree(agent_name, worktree_path)

        warm_disk_cache(worktree_path)
        return worktree_path

    def _create_reflink(self, agent_name: str, worktree_path: Path) -> None:
        self._copier.copy_repo(self.repo_root, worktree_path)
        logger.info("Created reflink workspace for '%s' at %s", agent_name, worktree_path)

    def _create_git_worktree(self, agent_name: str, worktree_path: Path) -> None:
        branch_name = f"evolution/{agent_name}"
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed for {agent_name}: {result.stderr.strip()}"
            )

        for rel_dir in discover_untracked_dirs(self.repo_root):
            src = self.repo_root / rel_dir
            dst = worktree_path / rel_dir
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.symlink_to(src.resolve())
                logger.debug("  Symlinked %s", rel_dir)

        logger.info(
            "Created git worktree for '%s' at %s (branch %s)",
            agent_name, worktree_path, branch_name,
        )

    def teardown_worktree(self, agent_name: str) -> None:
        worktree_path = self.worktrees_dir / agent_name

        if self._strategy == "git_worktree":
            if worktree_path.exists():
                for item in worktree_path.iterdir():
                    if item.is_symlink():
                        item.unlink()

            branch_name = f"evolution/{agent_name}"
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(self.repo_root),
                capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(self.repo_root),
                capture_output=True,
            )

        if worktree_path.exists():
            shutil.rmtree(worktree_path)

        logger.info("Removed workspace for '%s'", agent_name)

    def create_shared_dir(self) -> Path:
        shared_path = self.evolution_dir / "shared"
        for subdir in ("attempts", "notes", "skills"):
            (shared_path / subdir).mkdir(parents=True, exist_ok=True)
        logger.info("Created shared directory at %s", shared_path)
        return shared_path

    def link_shared(self, worktree_path: Path, shared_path: Path) -> None:
        evolution_in_worktree = worktree_path / ".evolution"
        evolution_in_worktree.mkdir(parents=True, exist_ok=True)
        link_target = evolution_in_worktree / "shared"
        if not link_target.exists():
            link_target.symlink_to(shared_path)
        logger.info("Linked %s -> %s", link_target, shared_path)

    def create_inbox(self, worktree_path: Path) -> Path:
        inbox_path = worktree_path / ".evolution" / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)
        logger.info("Created inbox at %s", inbox_path)
        return inbox_path

    def copy_seed(self, worktree_path: Path, seed_path: Path) -> None:
        logger.info("Copying seed files from %s to %s", seed_path, worktree_path)
        shutil.copytree(seed_path, worktree_path, dirs_exist_ok=True)
