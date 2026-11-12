"""Single-pilot arbitration: at most one client drives the robot at a time."""

from __future__ import annotations

from enum import Enum


class AcquireOutcome(str, Enum):
    GRANTED = "granted"
    ALREADY_PILOT = "already_pilot"
    TAKEN_OVER = "taken_over"
    """Control was forcibly taken from another client."""
    BUSY = "busy"
    """Another client is the pilot and ``force`` was not requested."""

    @property
    def is_pilot(self) -> bool:
        return self is not AcquireOutcome.BUSY


class PilotArbiter:
    def __init__(self) -> None:
        self._pilot_id: str | None = None

    @property
    def pilot_id(self) -> str | None:
        return self._pilot_id

    def is_pilot(self, client_id: str) -> bool:
        return self._pilot_id == client_id

    def acquire(self, client_id: str, *, force: bool = False) -> AcquireOutcome:
        if self._pilot_id == client_id:
            return AcquireOutcome.ALREADY_PILOT
        if self._pilot_id is None:
            self._pilot_id = client_id
            return AcquireOutcome.GRANTED
        if not force:
            return AcquireOutcome.BUSY
        self._pilot_id = client_id
        return AcquireOutcome.TAKEN_OVER

    def release(self, client_id: str) -> bool:
        """Release control if ``client_id`` holds it. Returns whether it did."""
        if self._pilot_id != client_id:
            return False
        self._pilot_id = None
        return True
