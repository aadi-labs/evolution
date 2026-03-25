"""Hypothesis tracking hub for Evolution agents."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Hypothesis:
    id: str
    agent: str
    hypothesis: str
    metric: str
    status: str = "open"  # open | validated | invalidated
    created: str = ""
    resolved_by: str | None = None
    evidence: str | None = None


class HypothesisHub:
    """Stores and retrieves hypotheses as markdown files with YAML frontmatter."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def add(self, agent: str, hypothesis: str, metric: str) -> Hypothesis:
        next_id = self._next_id()
        h = Hypothesis(
            id=f"H-{next_id}",
            agent=agent,
            hypothesis=hypothesis,
            metric=metric,
            status="open",
            created=datetime.now(timezone.utc).isoformat(),
        )
        self._write(h)
        return h

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        for h in self._read_all():
            if h.id == hypothesis_id:
                return h
        return None

    def list(self, status: str | None = None) -> list[Hypothesis]:
        all_h = self._read_all()
        if status:
            return [h for h in all_h if h.status == status]
        return all_h

    def resolve(self, hypothesis_id: str, status: str, resolved_by: str, evidence: str) -> Hypothesis | None:
        h = self.get(hypothesis_id)
        if h is None:
            return None
        h.status = status
        h.resolved_by = resolved_by
        h.evidence = evidence
        self._write(h)
        return h

    def _next_id(self) -> int:
        existing = self._read_all()
        if not existing:
            return 1
        max_id = max(int(h.id.split("-")[1]) for h in existing)
        return max_id + 1

    def _write(self, h: Hypothesis) -> None:
        slug = re.sub(r"[^a-z0-9]+", "-", h.hypothesis[:40].lower()).strip("-")
        filename = f"{h.id}-{slug}.md"
        path = self._dir / filename
        # Check if file with this ID already exists (for updates)
        for existing in self._dir.glob(f"{h.id}-*.md"):
            existing.unlink()

        frontmatter = {
            "id": h.id,
            "agent": h.agent,
            "status": h.status,
            "hypothesis": h.hypothesis,
            "metric": h.metric,
            "created": h.created,
            "resolved_by": h.resolved_by,
            "evidence": h.evidence,
        }
        content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n"
        path.write_text(content)

    def _read_all(self) -> list[Hypothesis]:
        results = []
        for path in sorted(self._dir.glob("H-*.md")):
            try:
                text = path.read_text()
                if text.startswith("---"):
                    end = text.index("---", 3)
                    fm = yaml.safe_load(text[3:end])
                    results.append(Hypothesis(
                        id=fm["id"],
                        agent=fm.get("agent", ""),
                        hypothesis=fm.get("hypothesis", ""),
                        metric=fm.get("metric", ""),
                        status=fm.get("status", "open"),
                        created=fm.get("created", ""),
                        resolved_by=fm.get("resolved_by"),
                        evidence=fm.get("evidence"),
                    ))
            except Exception as exc:
                logger.warning("Failed to read hypothesis %s: %s", path.name, exc)
        return results
