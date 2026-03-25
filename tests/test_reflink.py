import sys
from pathlib import Path
from unittest.mock import patch

from evolution.workspace.reflink import detect_reflink_support, reflink_flag, ReflinkCopier


class TestReflinkFlag:
    def test_macos_flag(self):
        with patch.object(sys, "platform", "darwin"):
            assert reflink_flag() == "-c"

    def test_linux_flag(self):
        with patch.object(sys, "platform", "linux"):
            assert reflink_flag() == "--reflink=always"


class TestDetectReflinkSupport:
    def test_detection_runs_without_error(self, tmp_path):
        evo_dir = tmp_path / ".evolution"
        evo_dir.mkdir()
        result = detect_reflink_support(tmp_path)
        assert isinstance(result, bool)
        assert not (evo_dir / ".reflink_test").exists()
        assert not (evo_dir / ".reflink_test_copy").exists()


class TestReflinkCopier:
    def test_copies_files(self, tmp_path):
        src = tmp_path / "repo"
        src.mkdir()
        (src / "main.py").write_text("print('hello')")
        (src / "lib").mkdir()
        (src / "lib" / "utils.py").write_text("x = 1")

        dst = tmp_path / "worktree"
        copier = ReflinkCopier(max_fd=50, max_workers=4)
        copier.copy_repo(src, dst)

        assert (dst / "main.py").read_text() == "print('hello')"
        assert (dst / "lib" / "utils.py").read_text() == "x = 1"

    def test_skips_evolution_and_git(self, tmp_path):
        src = tmp_path / "repo"
        src.mkdir()
        (src / "main.py").write_text("code")
        (src / ".evolution").mkdir()
        (src / ".evolution" / "state.json").write_text("{}")
        (src / ".git").mkdir()
        (src / ".git" / "HEAD").write_text("ref: refs/heads/main")

        dst = tmp_path / "worktree"
        copier = ReflinkCopier(max_fd=50, max_workers=4)
        copier.copy_repo(src, dst)

        assert (dst / "main.py").exists()
        assert not (dst / ".evolution").exists()
        assert not (dst / ".git").exists()

    def test_preserves_directory_structure(self, tmp_path):
        src = tmp_path / "repo"
        (src / "a" / "b" / "c").mkdir(parents=True)
        (src / "a" / "b" / "c" / "deep.txt").write_text("deep")

        dst = tmp_path / "worktree"
        copier = ReflinkCopier(max_fd=50, max_workers=4)
        copier.copy_repo(src, dst)

        assert (dst / "a" / "b" / "c" / "deep.txt").read_text() == "deep"
