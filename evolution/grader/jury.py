"""LLM Jury grader — multiple models grade the same attempt independently."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from evolution.grader.llm import LLMGrader
from evolution.grader.protocol import GradeResult

logger = logging.getLogger(__name__)

DEFAULT_JURY = [
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-flash",
]


class JuryGrader:
    """Multiple LLMs grade the same attempt. Aggregates scores and collects all feedback.

    Each juror grades independently and in parallel. The final score is the
    median of all successful juror scores (robust to outliers). All feedback
    is collected and presented together so agents get diverse perspectives.
    """

    def __init__(
        self,
        task_description: str,
        models: list[str] | None = None,
        timeout: int = 120,
    ) -> None:
        self.models = models or DEFAULT_JURY
        self.graders = [LLMGrader(task_description, model) for model in self.models]
        self.timeout = timeout

    def grade(self, attempt_path: str) -> GradeResult:
        """Grade attempt with all jurors in parallel, aggregate results."""
        results: list[tuple[str, GradeResult]] = []

        with ThreadPoolExecutor(max_workers=len(self.graders)) as pool:
            futures = {
                pool.submit(grader.grade, attempt_path): model
                for grader, model in zip(self.graders, self.models)
            }
            for future in as_completed(futures, timeout=self.timeout):
                model = futures[future]
                try:
                    result = future.result()
                    results.append((model, result))
                except Exception as exc:
                    logger.warning("Juror %s failed: %s", model, exc)
                    results.append((
                        model,
                        GradeResult(score=None, feedback=f"Error: {exc}"),
                    ))

        return self._aggregate(results)

    def _aggregate(self, results: list[tuple[str, GradeResult]]) -> GradeResult:
        """Combine juror results into a single GradeResult."""
        scores = []
        feedback_parts = []
        metrics: dict[str, float] = {}

        for model, result in results:
            short_name = model.split("/")[-1] if "/" in model else model

            if result.score is not None:
                scores.append(result.score)
                metrics[f"jury_{short_name}"] = result.score
                feedback_parts.append(f"**{short_name}** ({result.score}/10): {result.feedback}")
            else:
                feedback_parts.append(f"**{short_name}**: {result.feedback}")

        if not scores:
            return GradeResult(
                score=None,
                feedback="All jurors failed:\n" + "\n".join(feedback_parts),
                metrics=metrics,
            )

        median_score = _median(scores)
        metrics["jury_median"] = median_score
        metrics["jury_count"] = len(scores)
        metrics["jury_spread"] = max(scores) - min(scores)

        feedback = f"## Jury Verdict ({len(scores)}/{len(results)} jurors)\n"
        feedback += f"**Median score: {median_score:.1f}/10** "
        feedback += f"(spread: {min(scores):.1f}–{max(scores):.1f})\n\n"
        feedback += "\n\n".join(feedback_parts)

        return GradeResult(score=median_score, feedback=feedback, metrics=metrics)


def _median(values: list[float]) -> float:
    """Compute median of a non-empty list."""
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2
