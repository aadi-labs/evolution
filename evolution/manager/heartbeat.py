"""Heartbeat tracking for Evolution agents.

Supports multiple named heartbeat actions at different frequencies.
Each heartbeat has a name (e.g., ``reflect``, ``consolidate``) and fires
every N attempts or every N seconds (whichever comes first).
"""

from __future__ import annotations

import re
import time


def parse_duration(s: str) -> float:
    """Parse a duration string like '10m', '1h', '30s' to seconds.

    Parameters
    ----------
    s:
        A string of the form ``<int>(s|m|h)``.

    Returns
    -------
    float
        The equivalent number of seconds.

    Raises
    ------
    ValueError
        If the string does not match the expected format.
    """
    match = re.match(r"^(\d+)(s|m|h)$", s.strip())
    if not match:
        raise ValueError(f"Invalid duration: {s}")
    value, unit = int(match.group(1)), match.group(2)
    return value * {"s": 1, "m": 60, "h": 3600}[unit]


class HeartbeatTracker:
    """Tracks attempts and elapsed time to decide when a heartbeat should fire.

    Supports the legacy single-heartbeat config (on_attempts + on_time) as
    well as the new multi-heartbeat list format.
    """

    def __init__(self, on_attempts: int = 3, on_time_seconds: float = 600.0) -> None:
        self.on_attempts = on_attempts
        self.on_time_seconds = on_time_seconds
        self._attempt_count = 0
        self._last_reset = time.monotonic()

    def record_attempt(self) -> None:
        """Record that an attempt has been made."""
        self._attempt_count += 1

    def should_fire(self) -> bool:
        """Return True if a heartbeat should fire based on attempts or time."""
        return (
            self._attempt_count >= self.on_attempts
            or time.monotonic() - self._last_reset >= self.on_time_seconds
        )

    def reset(self) -> None:
        """Reset the attempt counter and time window."""
        self._attempt_count = 0
        self._last_reset = time.monotonic()


class NamedHeartbeat:
    """A single named heartbeat action (e.g., 'reflect' every 1 attempt)."""

    def __init__(self, name: str, every: int) -> None:
        self.name = name
        self.every = every  # fire every N attempts
        self._attempt_count = 0

    def record_attempt(self) -> None:
        self._attempt_count += 1

    def should_fire(self) -> bool:
        return self._attempt_count >= self.every

    def reset(self) -> None:
        self._attempt_count = 0


class MultiHeartbeatTracker:
    """Tracks multiple named heartbeat actions at different frequencies.

    Example config::

        heartbeat:
          - name: reflect
            every: 1
          - name: consolidate
            every: 10

    ``record_attempt()`` increments all counters.  ``get_pending()`` returns
    the names of heartbeats that should fire, and resets them.
    """

    def __init__(self, heartbeats: list[dict]) -> None:
        self._heartbeats = [
            NamedHeartbeat(name=hb["name"], every=hb["every"])
            for hb in heartbeats
        ]

    def record_attempt(self) -> None:
        """Record an attempt across all heartbeat trackers."""
        for hb in self._heartbeats:
            hb.record_attempt()

    def get_pending(self) -> list[str]:
        """Return names of heartbeats that should fire, and reset them."""
        pending = []
        for hb in self._heartbeats:
            if hb.should_fire():
                pending.append(hb.name)
                hb.reset()
        return pending
