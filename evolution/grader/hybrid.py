from __future__ import annotations

import logging

from evolution.grader.llm import LLMGrader
from evolution.grader.protocol import GradeResult
from evolution.grader.script import ScriptGrader

logger = logging.getLogger(__name__)


class HybridGrader:
    """Combines a deterministic script score with qualitative LLM feedback.

    The script score is authoritative; the LLM provides supplementary feedback.
    If the LLM call fails the script score is still returned.
    """

    def __init__(
        self,
        script_path: str,
        task_description: str,
        model: str = "openai/gpt-4o",
    ) -> None:
        self.script_grader = ScriptGrader(script_path)
        self.llm_grader = LLMGrader(task_description, model)

    def grade(self, attempt_path: str) -> GradeResult:
        """Grade an attempt using both the script and the LLM.

        Returns
        -------
        GradeResult
            * ``score`` comes from the script grader (authoritative).
            * ``feedback`` is the LLM feedback when available, otherwise a note
              that LLM feedback was unavailable plus the script feedback.
            * ``metrics`` merges data from both graders.
        """
        script_result = self.script_grader.grade(attempt_path)

        try:
            llm_result = self.llm_grader.grade(attempt_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM grading failed in hybrid grader: %s", exc)
            llm_result = None

        # Build combined metrics
        metrics: dict[str, float] = {}
        if script_result.score is not None:
            metrics["script_score"] = script_result.score
        metrics.update(script_result.metrics)

        if llm_result is not None and llm_result.score is not None:
            # LLM succeeded
            metrics["llm_score"] = llm_result.score
            metrics.update(llm_result.metrics)
            feedback = llm_result.feedback
        elif llm_result is not None and llm_result.score is None:
            # LLM ran but returned an error (score=None)
            feedback_parts = []
            if script_result.feedback:
                feedback_parts.append(script_result.feedback)
            feedback_parts.append(f"LLM feedback unavailable: {llm_result.feedback}")
            feedback = " | ".join(feedback_parts)
        else:
            # LLM raised an exception
            feedback_parts = []
            if script_result.feedback:
                feedback_parts.append(script_result.feedback)
            feedback_parts.append("LLM feedback unavailable due to an error.")
            feedback = " | ".join(feedback_parts)

        return GradeResult(
            score=script_result.score,
            feedback=feedback,
            metrics=metrics,
        )
