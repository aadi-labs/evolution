from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GradeResult:
    score: float | None
    feedback: str
    metrics: dict[str, float] = field(default_factory=dict)
