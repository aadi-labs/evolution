"""Thread-safe eval submission queue with fairness and rate limiting."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class EvalQueue:
    """Manages eval submissions with backpressure, rate limiting, and fairness."""

    def __init__(
        self,
        max_queued: int = 8,
        fairness: str = "fifo",
        rate_limit_seconds: int = 0,
    ) -> None:
        self._max_queued = max_queued
        self._fairness = fairness
        self._rate_limit_seconds = rate_limit_seconds

        self._lock = threading.Lock()
        self._queue: deque[dict[str, Any]] = deque()
        self._last_submit: dict[str, float] = {}
        self._improving_agents: set[str] = set()
        self._last_served_agent: str | None = None

    def submit(self, agent: str, description: str) -> dict[str, Any]:
        """Submit an eval request. Returns status dict immediately."""
        with self._lock:
            # Rate limit check
            if self._rate_limit_seconds > 0:
                last = self._last_submit.get(agent, 0)
                elapsed = time.monotonic() - last
                if last > 0 and elapsed < self._rate_limit_seconds:
                    remaining = int(self._rate_limit_seconds - elapsed)
                    return {
                        "status": "rejected",
                        "reason": f"Rate limited. Next eval allowed in {remaining}s.",
                        "retry_after_seconds": remaining,
                    }

            # Backpressure check
            if len(self._queue) >= self._max_queued:
                return {
                    "status": "rejected",
                    "reason": f"Eval queue full ({len(self._queue)}/{self._max_queued}). Try again later.",
                    "retry_after_seconds": 120,
                }

            entry = {
                "agent": agent,
                "description": description,
                "timestamp": time.monotonic(),
            }
            self._queue.append(entry)
            self._last_submit[agent] = time.monotonic()

            return {"status": "queued", "position": len(self._queue)}

    def get(self) -> dict[str, Any] | None:
        """Get the next eval to run based on fairness policy."""
        with self._lock:
            if not self._queue:
                return None
            if self._fairness == "fifo":
                return self._queue.popleft()
            elif self._fairness in ("round_robin", "priority"):
                return self._get_round_robin()
            return self._queue.popleft()

    def _get_round_robin(self) -> dict[str, Any] | None:
        """Pick next eval using round-robin across agents."""
        if not self._queue:
            return None

        # Priority boost: prefer improving agents
        if self._fairness == "priority" and self._improving_agents:
            for i, entry in enumerate(self._queue):
                if entry["agent"] in self._improving_agents:
                    self._last_served_agent = entry["agent"]
                    return self._remove_at(i)

        # Round robin: pick the first entry whose agent differs from last served
        if self._last_served_agent is not None:
            for i, entry in enumerate(self._queue):
                if entry["agent"] != self._last_served_agent:
                    self._last_served_agent = entry["agent"]
                    return self._remove_at(i)

        # Fallback: take the first entry (all same agent, or no last served)
        entry = self._queue.popleft()
        self._last_served_agent = entry["agent"]
        return entry

    def _remove_at(self, index: int) -> dict[str, Any]:
        item = self._queue[index]
        del self._queue[index]
        return item

    def mark_improving(self, agent: str) -> None:
        """Mark an agent as improving, giving it priority in 'priority' fairness mode."""
        with self._lock:
            self._improving_agents.add(agent)

    def clear_improving(self, agent: str) -> None:
        """Remove improving status from an agent."""
        with self._lock:
            self._improving_agents.discard(agent)

    @property
    def pending_count(self) -> int:
        """Number of evals currently waiting in the queue."""
        with self._lock:
            return len(self._queue)
