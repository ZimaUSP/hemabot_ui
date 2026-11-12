"""Teleoperation rules: who may drive, how commands are republished and when to stop.

Safety properties enforced here (and covered by tests):

* Only the current pilot can make the robot move.
* An active command is republished at a fixed rate while the pilot keeps sending
  intents. If intents stop arriving for longer than ``command_timeout`` (network
  drop, browser tab suspended, crash), the robot is stopped.
* Stopping publishes a short burst of zero velocities and then goes quiet, so other
  publishers sharing the topic (e.g. the physical joystick) are not overridden.
* Any connected client can trigger an emergency stop; it also revokes pilot control
  so the pilot's next joystick update cannot silently resume motion.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass

from hemabot_ui.clock import Clock
from hemabot_ui.motion.backend import MotionBackend
from hemabot_ui.motion.velocity import STOP, DriveIntent, VelocityCommand, VelocityLimits
from hemabot_ui.teleop.pilot import AcquireOutcome, PilotArbiter

logger = logging.getLogger(__name__)


class NotPilotError(PermissionError):
    """Raised when a client that is not the pilot tries to drive."""


@dataclass(frozen=True)
class TeleopTiming:
    publish_period: float
    """Seconds between republications of the active command."""
    command_timeout: float
    """An active command not refreshed by the pilot for this long is dropped."""
    stop_repeat_count: int
    """Number of zero-velocity messages published when stopping."""

    def __post_init__(self) -> None:
        if not (math.isfinite(self.publish_period) and self.publish_period > 0):
            raise ValueError("publish_period must be positive")
        if self.command_timeout <= self.publish_period:
            raise ValueError("command_timeout must be longer than publish_period")
        if self.stop_repeat_count < 1:
            raise ValueError("stop_repeat_count must be at least 1")

    @property
    def tick_interval(self) -> float:
        """How often ``TeleopService.tick`` should run (twice per publish period)."""
        return self.publish_period / 2


class TeleopService:
    def __init__(
        self,
        backend: MotionBackend,
        limits: VelocityLimits,
        timing: TeleopTiming,
        clock: Clock,
    ) -> None:
        self._backend = backend
        self._limits = limits
        self._timing = timing
        self._clock = clock
        self._arbiter = PilotArbiter()
        self._active_command: VelocityCommand | None = None
        self._last_intent_at = -math.inf
        self._last_publish_at = -math.inf
        self._pending_stops = 0

    @property
    def limits(self) -> VelocityLimits:
        return self._limits

    @property
    def pilot_id(self) -> str | None:
        return self._arbiter.pilot_id

    @property
    def active_command(self) -> VelocityCommand | None:
        return self._active_command

    def acquire(self, client_id: str, *, force: bool = False) -> AcquireOutcome:
        previous_pilot = self._arbiter.pilot_id
        outcome = self._arbiter.acquire(client_id, force=force)
        if outcome is AcquireOutcome.TAKEN_OVER:
            logger.info("Client %s took control from %s", client_id, previous_pilot)
            # The previous pilot's motion must never carry over to the new pilot.
            self._halt()
        elif outcome is AcquireOutcome.GRANTED:
            logger.info("Client %s is now the pilot", client_id)
        return outcome

    def release(self, client_id: str) -> None:
        if self._arbiter.release(client_id):
            logger.info("Client %s released control", client_id)
            self._halt()

    def disconnect(self, client_id: str) -> None:
        self.release(client_id)

    def drive(self, client_id: str, intent: DriveIntent) -> None:
        if not self._arbiter.is_pilot(client_id):
            raise NotPilotError(f"client {client_id} is not the pilot")
        if intent.is_idle:
            if self._active_command is not None:
                self._halt()
            return
        command = self._limits.scale(intent)
        self._active_command = command
        self._last_intent_at = self._clock.now()
        self._pending_stops = 0
        self._publish(command)

    def emergency_stop(self, client_id: str) -> None:
        pilot = self._arbiter.pilot_id
        if pilot is not None:
            self._arbiter.release(pilot)
        logger.warning("Emergency stop requested by client %s (pilot was %s)", client_id, pilot)
        self._halt()

    def tick(self) -> None:
        """Advance the watchdog and republish commands; call every ``tick_interval``."""
        now = self._clock.now()
        if self._active_command is not None:
            if now - self._last_intent_at > self._timing.command_timeout:
                logger.warning(
                    "No drive update from pilot for %.2fs; stopping the robot",
                    now - self._last_intent_at,
                )
                self._halt()
            elif now - self._last_publish_at >= self._timing.publish_period:
                self._publish(self._active_command)
            return
        if self._pending_stops > 0 and now - self._last_publish_at >= self._timing.publish_period:
            self._publish_stop()

    def halt(self) -> None:
        """Stop the robot without changing who is the pilot (used on server shutdown)."""
        self._halt()

    async def run(self) -> None:
        """Run ``tick`` forever at the configured rate."""
        while True:
            try:
                self.tick()
            except Exception:  # keep the watchdog alive whatever the backend does
                logger.exception("Teleop tick failed")
            await asyncio.sleep(self._timing.tick_interval)

    def _halt(self) -> None:
        self._active_command = None
        self._pending_stops = self._timing.stop_repeat_count
        self._publish_stop()

    def _publish_stop(self) -> None:
        self._pending_stops -= 1
        self._publish(STOP)

    def _publish(self, command: VelocityCommand) -> None:
        self._last_publish_at = self._clock.now()
        self._backend.send(command)
