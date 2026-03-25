"""Auto-discover gitignored directories for symlinking into worktrees."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def discover_untracked_dirs(repo_root: Path) -> list[str]:
    """Ask git for all ignored directories that exist in the repo.

    Returns relative paths. Deduplicates: if .venv/ is listed,
    .venv/lib/ is not included separately.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored",
             "--exclude-standard", "--directory"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("git ls-files timed out — skipping auto-discovery")
        return []

    if result.returncode != 0:
        logger.warning("git ls-files failed: %s", result.stderr.strip())
        return []

    dirs: list[str] = []
    symlinked_prefixes: set[str] = set()
    for line in sorted(result.stdout.strip().splitlines()):
        rel = line.rstrip("/")
        if not rel:
            continue
        if any(rel.startswith(p + "/") for p in symlinked_prefixes):
            continue
        path = repo_root / rel
        if path.is_dir():
            dirs.append(rel)
            symlinked_prefixes.add(rel)

    return dirs
