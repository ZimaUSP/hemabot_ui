"""Port between the teleoperation logic and whatever actually moves the robot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from hemabot_ui.motion.velocity import VelocityCommand


class BackendError(RuntimeError):
    """Raised when a motion backend cannot be started."""


class LinkState(str, Enum):
    """How far commands are known to travel towards the robot base."""

    CONNECTED = "connected"
    """Commands have a consumer (e.g. twist_mux is subscribed)."""
    WAITING = "waiting"
    """The backend is up but nothing consumes the commands yet (robot stack not running)."""
    OFFLINE = "offline"
    """The backend itself is not running."""


@dataclass(frozen=True)
class BackendStatus:
    link: LinkState
    detail: str
    """Technical, human readable explanation meant for logs and diagnostics."""


class MotionBackend(Protocol):
    """Delivers velocity commands to the robot.

    Implementations must make ``send`` cheap and non-blocking: it is called from the
    asyncio event loop at the teleoperation publish rate.
    """

    @property
    def name(self) -> str: ...

    def start(self) -> None:
        """Acquire resources. Raises ``BackendError`` when the backend cannot run."""
        ...

    def shutdown(self) -> None:
        """Release resources. Must be safe to call more than once."""
        ...

    def send(self, command: VelocityCommand) -> None: ...

    def status(self) -> BackendStatus: ...
