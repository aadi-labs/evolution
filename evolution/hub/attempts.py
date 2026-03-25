"""Attempts hub — file-based storage for evolution attempts."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Attempt:
    id: int
    agent: str
    score: float | None
    description: str
    commit: str
    feedback: str
    timestamp: str
    previous_best: float | None = None
    improvement: bool = False
    metrics: dict[str, float] = field(default_factory=dict)


class AttemptsHub:
    """Manages attempt records stored as markdown files with YAML frontmatter."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._next_id = self._compute_next_id()

    def _compute_next_id(self) -> int:
        ids = []
        for f in self.path.glob("*.md"):
            match = re.match(r"(\d+)-", f.name)
            if match:
                ids.append(int(match.group(1)))
        return max(ids, default=0) + 1

    def record(
        self,
        agent: str,
        score: float | None,
        description: str,
        commit: str,
        feedback: str,
        metrics: dict[str, float] | None = None,
    ) -> Attempt:
        """Record a new attempt and write it to a markdown file."""
        with self._lock:
            attempt_id = self._next_id
            self._next_id += 1
        timestamp = datetime.now(timezone.utc).isoformat()

        # Determine previous best and improvement
        existing = [a for a in self.list() if a.score is not None]
        previous_best: float | None = None
        improvement = False
        if existing and score is not None:
            best_scores = [a.score for a in existing if a.score is not None]
            if best_scores:
                previous_best = min(best_scores)
                improvement = score < previous_best

        attempt = Attempt(
            id=attempt_id,
            agent=agent,
            score=score,
            description=description,
            commit=commit,
            feedback=feedback,
            timestamp=timestamp,
            previous_best=previous_best,
            improvement=improvement,
            metrics=metrics or {},
        )

        self._write(attempt)
        return attempt

    def list(self) -> list[Attempt]:
        """Read all attempt files, sorted by filename."""
        attempts = []
        for f in sorted(self.path.glob("*.md"), reverse=True):
            attempt = self._read(f)
            if attempt is not None:
                attempts.append(attempt)
        return attempts

    def get(self, attempt_id: int) -> Attempt | None:
        """Find an attempt by its ID."""
        for f in self.path.glob("*.md"):
            match = re.match(r"(\d+)-", f.name)
            if match and int(match.group(1)) == attempt_id:
                return self._read(f)
        return None

    def leaderboard(self, direction: str = "lower_is_better") -> list[Attempt]:
        """Return attempts sorted by score."""
        scored = [a for a in self.list() if a.score is not None]
        reverse = direction != "lower_is_better"
        return sorted(scored, key=lambda a: a.score, reverse=reverse)  # type: ignore[arg-type]

    def best(self, direction: str = "lower_is_better") -> Attempt | None:
        """Return the best attempt by score."""
        board = self.leaderboard(direction)
        return board[0] if board else None

    def _write(self, attempt: Attempt) -> None:
        score_str = f"{attempt.score:.4f}" if attempt.score is not None else "none"
        filename = f"{attempt.id:03d}-{attempt.agent}-score-{score_str}.md"

        frontmatter: dict[str, Any] = {
            "id": attempt.id,
            "agent": attempt.agent,
            "score": attempt.score,
            "timestamp": attempt.timestamp,
            "commit": attempt.commit,
            "improvement": attempt.improvement,
        }
        if attempt.metrics:
            frontmatter["metrics"] = attempt.metrics

        body = f"## Description\n{attempt.description}\n\n## Grader Feedback\n{attempt.feedback}"

        content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n" + body + "\n"
        (self.path / filename).write_text(content)

    def _read(self, filepath: Path) -> Attempt | None:
        """Parse a markdown attempt file with YAML frontmatter."""
        text = filepath.read_text()
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        fm = yaml.safe_load(parts[1])
        if fm is None:
            return None

        body = parts[2].strip()

        # Parse description and feedback from body
        description = ""
        feedback = ""

        desc_match = re.search(r"## Description\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
        if desc_match:
            description = desc_match.group(1).strip()

        fb_match = re.search(r"## Grader Feedback\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
        if fb_match:
            feedback = fb_match.group(1).strip()

        return Attempt(
            id=fm.get("id", 0),
            agent=fm.get("agent", ""),
            score=fm.get("score"),
            description=description,
            commit=fm.get("commit", ""),
            feedback=feedback,
            timestamp=fm.get("timestamp", ""),
            previous_best=fm.get("previous_best"),
            improvement=fm.get("improvement", False),
            metrics=fm.get("metrics", {}),
        )
