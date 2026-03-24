"""Workspace manager for creating isolated agent workspaces.

Uses ``git worktree add`` to create lightweight, isolated copies of the repo.
Each agent gets its own worktree on a dedicated branch (``evolution/<name>``).
Untracked directories that agents need (e.g., ``.venv``, datasets) are
symlinked from the main repo.
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Untracked directories to symlink into worktrees.
# Git worktree only checks out tracked files — anything in .gitignore that
# agents need must be explicitly symlinked.
SYMLINK_UNTRACKED = [
    ".venv",
    "node_modules",
    # Common data directories (project-specific, may not exist)
    "chroma_data",
    "chroma_eval",
]


class WorkspaceManager:
    """Creates isolated git worktrees for each agent."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.evolution_dir = repo_root / ".evolution"
        self.worktrees_dir = self.evolution_dir / "worktrees"

    def create_worktree(self, agent_name: str) -> Path:
        """Create a git worktree for an agent.

        Runs ``git worktree add`` to create an isolated checkout on a
        new branch ``evolution/<agent_name>``.  Then symlinks untracked
        directories that agents need (virtualenvs, datasets, etc.).
        """
        worktree_path = self.worktrees_dir / agent_name
        branch_name = f"evolution/{agent_name}"

        # Clean up any existing worktree/branch from a prior run
        if worktree_path.exists():
            self._remove_git_worktree(worktree_path, branch_name)

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        # Create worktree on a new branch from HEAD
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

        logger.info(
            "Created git worktree for agent '%s' at %s (branch %s)",
            agent_name,
            worktree_path,
            branch_name,
        )

        # Symlink untracked directories that agents need
        self._symlink_untracked(worktree_path)

        return worktree_path

    def _symlink_untracked(self, worktree_path: Path) -> None:
        """Symlink untracked directories from the main repo into the worktree."""
        for rel_path in SYMLINK_UNTRACKED:
            src = self.repo_root / rel_path
            dest = worktree_path / rel_path
            if src.exists() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(src.resolve())
                logger.debug("  Symlinked %s", rel_path)

    def _remove_git_worktree(self, worktree_path: Path, branch_name: str) -> None:
        """Remove a git worktree and its branch."""
        # git worktree remove --force handles dirty worktrees
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(self.repo_root),
            capture_output=True,
        )
        # If git worktree remove didn't clean up the dir, force it
        if worktree_path.exists():
            shutil.rmtree(worktree_path)

        # Delete the branch
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(self.repo_root),
            capture_output=True,
        )

    def teardown_worktree(self, agent_name: str) -> None:
        """Remove an agent's worktree and branch."""
        worktree_path = self.worktrees_dir / agent_name
        branch_name = f"evolution/{agent_name}"
        self._remove_git_worktree(worktree_path, branch_name)
        logger.info("Removed worktree for agent '%s'", agent_name)

    def create_shared_dir(self) -> Path:
        """Create the shared directory with attempts, notes, and skills subdirs."""
        shared_path = self.evolution_dir / "shared"

        for subdir in ("attempts", "notes", "skills"):
            (shared_path / subdir).mkdir(parents=True, exist_ok=True)

        logger.info("Created shared directory at %s", shared_path)
        return shared_path

    def link_shared(self, worktree_path: Path, shared_path: Path) -> None:
        """Create a symlink inside the worktree pointing to the shared directory."""
        evolution_in_worktree = worktree_path / ".evolution"
        evolution_in_worktree.mkdir(parents=True, exist_ok=True)

        link_target = evolution_in_worktree / "shared"
        if not link_target.exists():
            link_target.symlink_to(shared_path)

        logger.info("Linked %s -> %s", link_target, shared_path)

    def create_inbox(self, worktree_path: Path) -> Path:
        """Create an inbox directory inside the worktree."""
        inbox_path = worktree_path / ".evolution" / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        logger.info("Created inbox at %s", inbox_path)
        return inbox_path

    def copy_seed(self, worktree_path: Path, seed_path: Path) -> None:
        """Copy all files from seed_path into worktree_path."""
        logger.info("Copying seed files from %s to %s", seed_path, worktree_path)
        shutil.copytree(seed_path, worktree_path, dirs_exist_ok=True)
