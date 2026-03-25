from __future__ import annotations

import os
import stat
import sys
import textwrap

import pytest

from evolution.grader.protocol import GradeResult
from evolution.grader.script import ScriptGrader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dummy_grader_script(tmp_path):
    """A grading script that prints 0.38091 to stdout and 'Good improvement' to stderr."""
    script = tmp_path / "grade.py"
    script.write_text(
        textwrap.dedent("""\
            import sys
            print("0.38091")
            print("Good improvement", file=sys.stderr)
        """)
    )
    return str(script)


@pytest.fixture()
def failing_grader_script(tmp_path):
    """A grading script that raises an exception."""
    script = tmp_path / "grade_fail.py"
    script.write_text('raise Exception("grading exploded")\n')
    return str(script)


@pytest.fixture()
def slow_grader_script(tmp_path):
    """A grading script that sleeps for a long time (used to test timeout)."""
    script = tmp_path / "grade_slow.py"
    script.write_text(
        textwrap.dedent("""\
            import time
            time.sleep(600)
            print("1.0")
        """)
    )
    return str(script)


# ---------------------------------------------------------------------------
# Tests — GradeResult dataclass
# ---------------------------------------------------------------------------


class TestGradeResult:
    def test_basic_construction(self):
        result = GradeResult(score=0.95, feedback="Excellent")
        assert result.score == 0.95
        assert result.feedback == "Excellent"
        assert result.metrics == {}

    def test_defaults_metrics_to_empty_dict(self):
        r1 = GradeResult(score=1.0, feedback="a")
        r2 = GradeResult(score=1.0, feedback="b")
        assert r1.metrics == {}
        assert r2.metrics == {}
        # Ensure each instance gets its own dict (not a shared mutable default).
        r1.metrics["x"] = 1.0
        assert "x" not in r2.metrics

    def test_custom_metrics(self):
        result = GradeResult(score=0.5, feedback="ok", metrics={"acc": 0.9})
        assert result.metrics == {"acc": 0.9}

    def test_score_none(self):
        result = GradeResult(score=None, feedback="failed")
        assert result.score is None


# ---------------------------------------------------------------------------
# Tests — ScriptGrader
# ---------------------------------------------------------------------------


class TestScriptGrader:
    def test_parses_score_correctly(self, dummy_grader_script, tmp_path):
        grader = ScriptGrader(dummy_grader_script)
        result = grader.grade(str(tmp_path))

        assert result.score == pytest.approx(0.38091)
        assert "Good improvement" in result.feedback

    def test_handles_failing_script(self, failing_grader_script, tmp_path):
        grader = ScriptGrader(failing_grader_script)
        result = grader.grade(str(tmp_path))

        assert result.score is None
        assert "error" in result.feedback.lower()

    def test_handles_timeout(self, slow_grader_script, tmp_path):
        grader = ScriptGrader(slow_grader_script)
        result = grader.grade(str(tmp_path), timeout=1)

        assert result.score is None
        assert "timed out" in result.feedback.lower()

    def test_handles_missing_script(self, tmp_path):
        grader = ScriptGrader("/nonexistent/grade.py")
        result = grader.grade(str(tmp_path))

        assert result.score is None
        assert result.feedback  # some descriptive message


class TestScriptGraderEnvCleaning:
    def test_grader_does_not_leak_virtual_env(self, tmp_path):
        """Grader subprocess should not inherit VIRTUAL_ENV."""
        script = tmp_path / "check_env.py"
        script.write_text(textwrap.dedent("""\
            import os, sys
            if "VIRTUAL_ENV" in os.environ:
                print("-1.0")
                print("VIRTUAL_ENV leaked into grader", file=sys.stderr)
            else:
                print("1.0")
                print("Clean environment", file=sys.stderr)
        """))

        # Set VIRTUAL_ENV in current process to simulate leakage
        original = os.environ.get("VIRTUAL_ENV")
        os.environ["VIRTUAL_ENV"] = "/fake/venv"
        try:
            grader = ScriptGrader(str(script))
            result = grader.grade(str(tmp_path))
        finally:
            if original is None:
                os.environ.pop("VIRTUAL_ENV", None)
            else:
                os.environ["VIRTUAL_ENV"] = original

        assert result.score == pytest.approx(1.0)
        assert "Clean environment" in result.feedback
