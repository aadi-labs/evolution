from __future__ import annotations

import json
import logging
import os
import subprocess

from evolution.grader.protocol import GradeResult

logger = logging.getLogger(__name__)

_GRADING_PROMPT_TEMPLATE = """\
You are a code-review grader. Evaluate the following code change against the task description.

## Task Description
{task_description}

## Git Diff
```
{diff}
```

Respond with ONLY a JSON object (no markdown fences, no extra text) containing:
- "score": a float from 0 to 10 (0 = no progress, 10 = perfect solution)
- "feedback": a short paragraph describing strengths and weaknesses

Example: {{"score": 7.5, "feedback": "Good progress but missing edge-case handling."}}
"""


def call_openrouter(prompt: str, model: str) -> dict:
    """Call the OpenRouter API and return a dict with 'score' and 'feedback' keys.

    Tries the ``openrouter`` Python SDK first; falls back to a simple HTTP
    request via ``httpx`` / ``urllib`` if the SDK is not installed.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")

    # --- Attempt 1: openrouter SDK -------------------------------------------
    try:
        import openrouter as _openrouter  # type: ignore[import-untyped]

        response = _openrouter.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
        )
        text = response.choices[0].message.content  # type: ignore[union-attr]
        return _parse_json_response(text)
    except ImportError:
        pass  # SDK not available – fall through to HTTP
    except Exception as exc:
        # SDK available but call failed – still try HTTP fallback
        logger.debug("openrouter SDK call failed (%s), trying HTTP fallback", exc)

    # --- Attempt 2: plain HTTP via httpx / urllib ----------------------------
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload.encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode())

    text = body["choices"][0]["message"]["content"]
    return _parse_json_response(text)


def _parse_json_response(text: str) -> dict:
    """Extract a JSON object with 'score' and 'feedback' from LLM output."""
    # Strip possible markdown fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last fence lines
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)
    if "score" not in data or "feedback" not in data:
        raise ValueError(f"Response missing required keys: {data}")
    return {"score": float(data["score"]), "feedback": str(data["feedback"])}


class LLMGrader:
    """Grades a code attempt by asking an LLM (via OpenRouter) for a score and feedback."""

    def __init__(self, task_description: str, model: str = "openai/gpt-4o") -> None:
        self.task_description = task_description
        self.model = model

    def grade(self, attempt_path: str) -> GradeResult:
        """Get a git diff from *attempt_path*, ask the LLM to grade it, and return a GradeResult."""
        try:
            diff = self._get_diff(attempt_path)
            prompt = _GRADING_PROMPT_TEMPLATE.format(
                task_description=self.task_description,
                diff=diff or "(no changes detected)",
            )
            result = call_openrouter(prompt, self.model)
            return GradeResult(
                score=result["score"],
                feedback=result["feedback"],
                metrics={"llm_score": result["score"]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM grading failed: %s", exc)
            return GradeResult(score=None, feedback=f"LLM grading failed: {exc}")

    @staticmethod
    def _get_diff(attempt_path: str) -> str:
        """Return the git diff for the working tree at *attempt_path*."""
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=attempt_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff = result.stdout.strip()
            if not diff:
                # Try staged changes as well
                result = subprocess.run(
                    ["git", "diff", "--cached"],
                    cwd=attempt_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                diff = result.stdout.strip()
            return diff
        except Exception:
            # Not a git repo or git not available – read all files as fallback
            return "(unable to obtain git diff)"
