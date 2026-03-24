from __future__ import annotations

import textwrap
from unittest.mock import patch, MagicMock

import pytest

from evolution.grader.protocol import GradeResult
from evolution.grader.llm import LLMGrader, call_openrouter
from evolution.grader.hybrid import HybridGrader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dummy_grader_script(tmp_path):
    """A grading script that prints 7.5 to stdout and 'Tests pass' to stderr."""
    script = tmp_path / "grade.py"
    script.write_text(
        textwrap.dedent("""\
            import sys
            print("7.5")
            print("Tests pass", file=sys.stderr)
        """)
    )
    return str(script)


@pytest.fixture()
def failing_grader_script(tmp_path):
    """A grading script that exits with an error."""
    script = tmp_path / "grade_fail.py"
    script.write_text('raise Exception("grading exploded")\n')
    return str(script)


# ---------------------------------------------------------------------------
# Tests — LLMGrader
# ---------------------------------------------------------------------------


class TestLLMGrader:
    @patch("evolution.grader.llm.call_openrouter")
    def test_calls_openrouter_and_parses_response(self, mock_call, tmp_path):
        """LLMGrader calls call_openrouter and returns a GradeResult from the response."""
        mock_call.return_value = {
            "score": 8.5,
            "feedback": "Well-structured implementation with good error handling.",
        }

        grader = LLMGrader(task_description="Implement a sorting algorithm")
        result = grader.grade(str(tmp_path))

        assert mock_call.called
        assert result.score == 8.5
        assert "Well-structured" in result.feedback
        assert result.metrics.get("llm_score") == 8.5

    @patch("evolution.grader.llm.call_openrouter")
    def test_handles_api_error_gracefully(self, mock_call, tmp_path):
        """LLMGrader returns score=None with error description when API fails."""
        mock_call.side_effect = RuntimeError("API connection refused")

        grader = LLMGrader(task_description="Implement a sorting algorithm")
        result = grader.grade(str(tmp_path))

        assert result.score is None
        assert "LLM grading failed" in result.feedback
        assert "API connection refused" in result.feedback

    @patch("evolution.grader.llm.call_openrouter")
    def test_passes_correct_model(self, mock_call, tmp_path):
        """LLMGrader passes the configured model to call_openrouter."""
        mock_call.return_value = {"score": 5.0, "feedback": "Average."}

        grader = LLMGrader(
            task_description="Fix the bug",
            model="anthropic/claude-3.5-sonnet",
        )
        grader.grade(str(tmp_path))

        _, kwargs = mock_call.call_args
        # model is the second positional arg
        args, _ = mock_call.call_args
        assert args[1] == "anthropic/claude-3.5-sonnet"

    @patch("evolution.grader.llm.call_openrouter")
    def test_prompt_includes_task_description(self, mock_call, tmp_path):
        """The prompt sent to call_openrouter includes the task description."""
        mock_call.return_value = {"score": 6.0, "feedback": "Decent."}

        grader = LLMGrader(task_description="Implement binary search")
        grader.grade(str(tmp_path))

        prompt = mock_call.call_args[0][0]
        assert "Implement binary search" in prompt


# ---------------------------------------------------------------------------
# Tests — HybridGrader
# ---------------------------------------------------------------------------


class TestHybridGrader:
    @patch("evolution.grader.llm.call_openrouter")
    def test_uses_script_score_and_llm_feedback(
        self, mock_call, dummy_grader_script, tmp_path
    ):
        """HybridGrader returns the script score with LLM feedback."""
        mock_call.return_value = {
            "score": 9.0,
            "feedback": "Excellent code quality and test coverage.",
        }

        grader = HybridGrader(
            script_path=dummy_grader_script,
            task_description="Build a REST API",
        )
        result = grader.grade(str(tmp_path))

        # Score comes from the script (7.5), not the LLM (9.0)
        assert result.score == pytest.approx(7.5)
        # Feedback comes from the LLM
        assert "Excellent code quality" in result.feedback
        # Metrics should contain both scores
        assert result.metrics.get("script_score") == pytest.approx(7.5)
        assert result.metrics.get("llm_score") == 9.0

    @patch("evolution.grader.llm.call_openrouter")
    def test_works_when_llm_fails(
        self, mock_call, dummy_grader_script, tmp_path
    ):
        """HybridGrader still returns the script score when LLM fails."""
        mock_call.side_effect = RuntimeError("OpenRouter is down")

        grader = HybridGrader(
            script_path=dummy_grader_script,
            task_description="Build a REST API",
        )
        result = grader.grade(str(tmp_path))

        # Script score is still returned
        assert result.score == pytest.approx(7.5)
        # Feedback indicates LLM was unavailable
        assert "unavailable" in result.feedback.lower()
        # Script score in metrics
        assert result.metrics.get("script_score") == pytest.approx(7.5)

    @patch("evolution.grader.llm.call_openrouter")
    def test_works_when_script_fails_and_llm_succeeds(
        self, mock_call, failing_grader_script, tmp_path
    ):
        """When the script fails, score is None but LLM feedback is still included."""
        mock_call.return_value = {
            "score": 6.0,
            "feedback": "Partial implementation.",
        }

        grader = HybridGrader(
            script_path=failing_grader_script,
            task_description="Build a REST API",
        )
        result = grader.grade(str(tmp_path))

        # Script failed so score is None
        assert result.score is None
        # LLM feedback is still present
        assert "Partial implementation" in result.feedback
        assert result.metrics.get("llm_score") == 6.0

    @patch("evolution.grader.llm.call_openrouter")
    def test_works_when_both_fail(
        self, mock_call, failing_grader_script, tmp_path
    ):
        """When both script and LLM fail, score=None and feedback explains."""
        mock_call.side_effect = RuntimeError("API error")

        grader = HybridGrader(
            script_path=failing_grader_script,
            task_description="Build a REST API",
        )
        result = grader.grade(str(tmp_path))

        assert result.score is None
        assert "unavailable" in result.feedback.lower()
