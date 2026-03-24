"""Tests for the LLM Jury grader."""

import pytest
from unittest.mock import patch, MagicMock

from evolution.grader.jury import JuryGrader, _median
from evolution.grader.protocol import GradeResult


class TestMedian:
    def test_odd_count(self):
        assert _median([1, 3, 5]) == 3

    def test_even_count(self):
        assert _median([1, 3, 5, 7]) == 4.0

    def test_single_value(self):
        assert _median([42]) == 42

    def test_unsorted_input(self):
        assert _median([5, 1, 3]) == 3


class TestJuryGrader:
    @patch("evolution.grader.llm.call_openrouter")
    def test_aggregates_multiple_jurors(self, mock_call, tmp_path):
        # Each model returns a different score
        mock_call.side_effect = [
            {"score": 7.0, "feedback": "Good approach"},
            {"score": 8.0, "feedback": "Excellent work"},
            {"score": 6.0, "feedback": "Needs improvement"},
        ]
        grader = JuryGrader(
            task_description="Optimize code",
            models=["model-a", "model-b", "model-c"],
        )
        result = grader.grade(str(tmp_path))

        assert result.score == pytest.approx(7.0)  # median of 6, 7, 8
        assert result.metrics["jury_median"] == pytest.approx(7.0)
        assert result.metrics["jury_count"] == 3
        assert result.metrics["jury_spread"] == pytest.approx(2.0)

    @patch("evolution.grader.llm.call_openrouter")
    def test_handles_partial_failure(self, mock_call, tmp_path):
        mock_call.side_effect = [
            {"score": 8.0, "feedback": "Great"},
            Exception("API timeout"),
            {"score": 6.0, "feedback": "OK"},
        ]
        grader = JuryGrader(
            task_description="test",
            models=["model-a", "model-b", "model-c"],
        )
        result = grader.grade(str(tmp_path))

        # Median of 6, 8 = 7.0 (model-b failed)
        assert result.score == pytest.approx(7.0)
        assert result.metrics["jury_count"] == 2

    @patch("evolution.grader.llm.call_openrouter")
    def test_all_jurors_fail(self, mock_call, tmp_path):
        mock_call.side_effect = Exception("API down")
        grader = JuryGrader(
            task_description="test",
            models=["model-a", "model-b"],
        )
        result = grader.grade(str(tmp_path))

        assert result.score is None
        assert "All jurors failed" in result.feedback

    @patch("evolution.grader.llm.call_openrouter")
    def test_feedback_includes_all_jurors(self, mock_call, tmp_path):
        mock_call.side_effect = [
            {"score": 7.0, "feedback": "Alpha insight"},
            {"score": 8.0, "feedback": "Beta insight"},
        ]
        grader = JuryGrader(
            task_description="test",
            models=["provider/alpha-model", "provider/beta-model"],
        )
        result = grader.grade(str(tmp_path))

        assert "alpha-model" in result.feedback
        assert "beta-model" in result.feedback
        assert "Alpha insight" in result.feedback
        assert "Beta insight" in result.feedback

    @patch("evolution.grader.llm.call_openrouter")
    def test_metrics_per_juror(self, mock_call, tmp_path):
        mock_call.side_effect = [
            {"score": 7.0, "feedback": "ok"},
            {"score": 9.0, "feedback": "great"},
        ]
        grader = JuryGrader(
            task_description="test",
            models=["x/alpha", "x/beta"],
        )
        result = grader.grade(str(tmp_path))

        # Thread ordering is non-deterministic, so check both scores exist
        assert "jury_alpha" in result.metrics
        assert "jury_beta" in result.metrics
        assert sorted([result.metrics["jury_alpha"], result.metrics["jury_beta"]]) == [7.0, 9.0]

    @patch("evolution.grader.llm.call_openrouter")
    def test_single_juror(self, mock_call, tmp_path):
        mock_call.return_value = {"score": 5.0, "feedback": "Mediocre"}
        grader = JuryGrader(
            task_description="test",
            models=["solo-model"],
        )
        result = grader.grade(str(tmp_path))

        assert result.score == pytest.approx(5.0)
        assert result.metrics["jury_count"] == 1
        assert result.metrics["jury_spread"] == pytest.approx(0.0)

    def test_default_jury_models(self):
        grader = JuryGrader(task_description="test")
        assert len(grader.models) == 3
        assert any("gpt" in m for m in grader.models)
        assert any("claude" in m for m in grader.models)
        assert any("gemini" in m for m in grader.models)
