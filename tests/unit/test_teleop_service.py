from __future__ import annotations

import asyncio
import itertools

import pytest

from hemabot_ui.motion.simulated import SimulatedMotionBackend
from hemabot_ui.motion.velocity import STOP, DriveIntent, VelocityCommand
from hemabot_ui.teleop.pilot import AcquireOutcome
from hemabot_ui.teleop.service import NotPilotError, TeleopService, TeleopTiming
from tests.conftest import FakeClock

FORWARD = DriveIntent(linear=1.0, angular=0.0)
FULL_FORWARD = VelocityCommand(linear=0.4, angular=0.0)


def run_ticks(teleop: TeleopService, clock: FakeClock, seconds: float, step: float = 0.05) -> None:
    for _ in range(round(seconds / step)):
        clock.advance(step)
        teleop.tick()


class TestDriving:
    def test_non_pilot_cannot_drive(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        with pytest.raises(NotPilotError):
            teleop.drive("intruder", FORWARD)
        assert backend.history == []

    def test_drive_publishes_scaled_command_immediately(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", DriveIntent(linear=0.5, angular=-0.5))
        assert backend.history == [VelocityCommand(linear=0.2, angular=-0.5)]

    def test_active_command_is_republished_at_publish_rate(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        # Keep the command fresh while ticking for 0.3 s (publish period 0.1 s).
        for _ in range(3):
            run_ticks(teleop, clock, 0.1)
            teleop.drive("pilot", FORWARD)
        assert all(command == FULL_FORWARD for command in backend.history)
        # 1 initial + 3 refreshes + republishes from ticks; at least the 10 Hz floor.
        assert len(backend.history) >= 4

    def test_republish_happens_without_new_intents_until_timeout(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        publish_times = [clock.now()]
        for _ in range(7):  # 0.35 s, still inside the 0.4 s command timeout
            clock.advance(0.05)
            before = len(backend.history)
            teleop.tick()
            if len(backend.history) > before:
                publish_times.append(clock.now())
        assert set(backend.history) == {FULL_FORWARD}
        gaps = [later - earlier for earlier, later in itertools.pairwise(publish_times)]
        # Ticks run twice per publish period, so the worst gap is 1.5 periods.
        assert max(gaps) <= 0.15 + 1e-9
        assert len(publish_times) >= 3

    def test_idle_intent_halts_but_keeps_control(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.drive("pilot", DriveIntent(0.0, 0.0))
        assert backend.last_command == STOP
        assert teleop.active_command is None
        assert teleop.pilot_id == "pilot"

    def test_idle_intent_while_already_idle_publishes_nothing(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", DriveIntent(0.0, 0.0))
        assert backend.history == []


class TestWatchdog:
    def test_stale_command_stops_the_robot(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        run_ticks(teleop, clock, 0.5)
        assert teleop.active_command is None
        assert backend.last_command == STOP

    def test_robot_never_moves_longer_than_timeout_without_intents(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        moving_publications_times = []
        for _ in range(40):
            clock.advance(0.05)
            before = len(backend.history)
            teleop.tick()
            if len(backend.history) > before and backend.last_command != STOP:
                moving_publications_times.append(clock.now())
        start = 1000.0
        assert max(moving_publications_times) - start <= 0.4 + 1e-9

    def test_stop_burst_then_silence(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.drive("pilot", DriveIntent(0.0, 0.0))
        run_ticks(teleop, clock, 2.0)
        stops = [command for command in backend.history if command == STOP]
        assert len(stops) == 3  # stop_repeat_count
        assert backend.history[-3:] == [STOP] * 3

    def test_new_intent_cancels_pending_stop_burst(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.drive("pilot", DriveIntent(0.0, 0.0))
        teleop.drive("pilot", FORWARD)
        run_ticks(teleop, clock, 0.2)
        assert backend.last_command == FULL_FORWARD

    def test_tick_without_activity_publishes_nothing(
        self, teleop: TeleopService, backend: SimulatedMotionBackend, clock: FakeClock
    ) -> None:
        run_ticks(teleop, clock, 1.0)
        assert backend.history == []


class TestPilotChanges:
    def test_release_stops_the_robot(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.release("pilot")
        assert backend.last_command == STOP
        assert teleop.pilot_id is None

    def test_release_by_non_pilot_is_ignored(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.release("someone-else")
        assert teleop.pilot_id == "pilot"
        assert backend.last_command == FULL_FORWARD

    def test_pilot_disconnect_stops_the_robot(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.disconnect("pilot")
        assert backend.last_command == STOP
        assert teleop.pilot_id is None

    def test_observer_disconnect_does_not_affect_pilot(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.disconnect("observer")
        assert backend.last_command == FULL_FORWARD
        assert teleop.pilot_id == "pilot"

    def test_takeover_stops_previous_motion(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("first")
        teleop.drive("first", FORWARD)
        assert teleop.acquire("second", force=True) is AcquireOutcome.TAKEN_OVER
        assert backend.last_command == STOP
        assert teleop.active_command is None
        with pytest.raises(NotPilotError):
            teleop.drive("first", FORWARD)

    def test_busy_acquire_does_not_disturb_motion(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("first")
        teleop.drive("first", FORWARD)
        assert teleop.acquire("second") is AcquireOutcome.BUSY
        assert backend.last_command == FULL_FORWARD


class TestEmergencyStop:
    def test_any_client_can_stop_and_control_is_revoked(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.emergency_stop("observer")
        assert backend.last_command == STOP
        assert teleop.pilot_id is None
        with pytest.raises(NotPilotError):
            teleop.drive("pilot", FORWARD)

    def test_stop_without_pilot_still_publishes_zero(
        self, teleop: TeleopService, backend: SimulatedMotionBackend
    ) -> None:
        teleop.emergency_stop("anyone")
        assert backend.history == [STOP]

    def test_halt_keeps_pilot(self, teleop: TeleopService, backend: SimulatedMotionBackend) -> None:
        teleop.acquire("pilot")
        teleop.drive("pilot", FORWARD)
        teleop.halt()
        assert backend.last_command == STOP
        assert teleop.pilot_id == "pilot"


class TestRunLoop:
    async def test_run_loop_survives_backend_errors(self, limits: object, clock: FakeClock) -> None:
        class ExplodingBackend(SimulatedMotionBackend):
            calls = 0

            def send(self, command: VelocityCommand) -> None:
                self.calls += 1
                raise RuntimeError("boom")

        backend = ExplodingBackend()
        timing = TeleopTiming(publish_period=0.01, command_timeout=0.05, stop_repeat_count=1)
        teleop = TeleopService(backend, limits, timing, clock)  # type: ignore[arg-type]
        teleop.acquire("pilot")
        with pytest.raises(RuntimeError):
            teleop.drive("pilot", FORWARD)
        task = asyncio.create_task(teleop.run())
        for _ in range(3):
            clock.advance(0.02)
            await asyncio.sleep(0.01)
        assert not task.done()
        task.cancel()
        assert backend.calls > 1


class TestTiming:
    def test_timeout_must_exceed_publish_period(self) -> None:
        with pytest.raises(ValueError):
            TeleopTiming(publish_period=0.1, command_timeout=0.1, stop_repeat_count=1)

    def test_stop_repeat_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            TeleopTiming(publish_period=0.1, command_timeout=0.5, stop_repeat_count=0)

    def test_tick_interval_is_half_the_period(self, timing: TeleopTiming) -> None:
        assert timing.tick_interval == pytest.approx(0.05)
