from __future__ import annotations

import logging
import subprocess

from evolution.grader.protocol import GradeResult

logger = logging.getLogger(__name__)


class ScriptGrader:
    """Runs an external Python grading script and parses its output."""

    def __init__(self, script_path: str) -> None:
        self.script_path = script_path

    def grade(self, attempt_path: str, timeout: float = 1800) -> GradeResult:
        """Run the grading script inside *attempt_path* and return a GradeResult.

        Protocol
        --------
        * The script is executed as ``python3 <script_path>`` with *attempt_path*
          as the working directory.
        * The **first line** of stdout is parsed as a float score.
        * stderr is captured as feedback text.
        * On any failure (non-zero exit, parse error, timeout, other exception)
          the method returns a GradeResult with ``score=None`` and a descriptive
          feedback string.
        """
        try:
            result = subprocess.run(
                ["python3", self.script_path],
                cwd=attempt_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                feedback = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                logger.warning(
                    "Grading script %s exited with code %d: %s",
                    self.script_path,
                    result.returncode,
                    feedback,
                )
                return GradeResult(
                    score=None,
                    feedback=f"Grading script error (exit code {result.returncode}): {feedback}",
                )

            stdout_lines = result.stdout.strip().splitlines()
            if not stdout_lines:
                return GradeResult(
                    score=None,
                    feedback="Grading script produced no stdout output",
                )

            try:
                score = float(stdout_lines[0].strip())
            except ValueError:
                return GradeResult(
                    score=None,
                    feedback=f"Could not parse score from grading script output: {stdout_lines[0]!r}",
                )

            feedback = result.stderr.strip()
            return GradeResult(score=score, feedback=feedback)

        except subprocess.TimeoutExpired:
            logger.warning(
                "Grading script %s timed out after %s seconds",
                self.script_path,
                timeout,
            )
            return GradeResult(
                score=None,
                feedback=f"Grading script timed out after {timeout} seconds",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error running grading script %s", self.script_path)
            return GradeResult(
                score=None,
                feedback=f"Unexpected grading error: {exc}",
            )
