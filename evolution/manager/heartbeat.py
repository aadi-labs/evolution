"""Heartbeat tracking for Evolution agents."""

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
    """Tracks attempts and elapsed time to decide when a heartbeat should fire."""

    def __init__(self, on_attempts: int, on_time_seconds: float) -> None:
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
