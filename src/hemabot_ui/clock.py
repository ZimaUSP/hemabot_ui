"""Time source abstraction so time-dependent logic can be tested deterministically."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Return a monotonic timestamp in seconds."""
        ...


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()
