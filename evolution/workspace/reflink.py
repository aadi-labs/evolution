"""Reflink (copy-on-write) detection and parallel file copying."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Semaphore

logger = logging.getLogger(__name__)

SKIP_DIRS = {".evolution", ".git"}


def reflink_flag() -> str:
    """Return the cp flag for reflink copy on this platform."""
    return "-c" if sys.platform == "darwin" else "--reflink=always"


def detect_reflink_support(repo_root: Path) -> bool:
    """Test whether the filesystem supports reflink by copying a temp file."""
    evo_dir = repo_root / ".evolution"
    evo_dir.mkdir(parents=True, exist_ok=True)
    test_src = evo_dir / ".reflink_test"
    test_dst = evo_dir / ".reflink_test_copy"
    try:
        test_src.write_text("test")
        result = subprocess.run(
            ["cp", reflink_flag(), str(test_src), str(test_dst)],
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False
    finally:
        test_src.unlink(missing_ok=True)
        test_dst.unlink(missing_ok=True)


class ReflinkCopier:
    """Parallel reflink copier with fd throttling."""

    def __init__(self, max_fd: int = 200, max_workers: int = 32) -> None:
        self._fd_sem = Semaphore(max_fd)
        self._max_workers = max_workers
        self._flag = reflink_flag()

    def _copy_file(self, src: Path, dst: Path) -> None:
        with self._fd_sem:
            dst.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["cp", self._flag, str(src), str(dst)],
                capture_output=True,
            )
            if result.returncode != 0:
                shutil.copy2(src, dst)

    def copy_repo(self, repo_root: Path, worktree_path: Path) -> None:
        """Copy entire repo using reflink, skipping .evolution/ and .git/."""
        worktree_path.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = []
            for root, dirs, files in os.walk(repo_root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    src = Path(root) / f
                    rel = src.relative_to(repo_root)
                    dst = worktree_path / rel
                    futures.append(pool.submit(self._copy_file, src, dst))
            for fut in futures:
                fut.result()


def warm_disk_cache(path: Path) -> None:
    """Walk directory tree in background to warm OS page cache."""
    def _walk():
        for _ in os.walk(path):
            pass
    threading.Thread(target=_walk, daemon=True).start()
