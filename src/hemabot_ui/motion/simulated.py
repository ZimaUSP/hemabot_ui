"""In-memory backend used for development without a robot and for automated tests."""

from __future__ import annotations

import logging
from collections import deque

from hemabot_ui.motion.backend import BackendStatus, LinkState
from hemabot_ui.motion.velocity import VelocityCommand

logger = logging.getLogger(__name__)


class SimulatedMotionBackend:
    def __init__(self, history_size: int = 1000) -> None:
        self._running = False
        self._history: deque[VelocityCommand] = deque(maxlen=history_size)

    @property
    def name(self) -> str:
        return "simulated"

    @property
    def history(self) -> list[VelocityCommand]:
        """Commands received so far, oldest first."""
        return list(self._history)

    @property
    def last_command(self) -> VelocityCommand | None:
        return self._history[-1] if self._history else None

    def start(self) -> None:
        self._running = True
        logger.info("Simulated motion backend started; no robot will move")

    def shutdown(self) -> None:
        self._running = False

    def send(self, command: VelocityCommand) -> None:
        if not self._running:
            return
        self._history.append(command)
        logger.debug("Simulated command: linear=%.3f angular=%.3f", command.linear, command.angular)

    def status(self) -> BackendStatus:
        if not self._running:
            return BackendStatus(LinkState.OFFLINE, "simulated backend stopped")
        return BackendStatus(LinkState.CONNECTED, "simulated backend (no real robot)")
