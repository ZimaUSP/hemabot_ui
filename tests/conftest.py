from __future__ import annotations

import pytest

from hemabot_ui.motion.simulated import SimulatedMotionBackend
from hemabot_ui.motion.velocity import VelocityLimits
from hemabot_ui.teleop.service import TeleopService, TeleopTiming
from tests.fakes.fake_rclpy import FakeRosGraph, install


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.time = start

    def now(self) -> float:
        return self.time

    def advance(self, seconds: float) -> None:
        self.time += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def backend() -> SimulatedMotionBackend:
    simulated = SimulatedMotionBackend()
    simulated.start()
    return simulated


@pytest.fixture
def limits() -> VelocityLimits:
    return VelocityLimits(max_linear=0.4, max_angular=1.0)


@pytest.fixture
def timing() -> TeleopTiming:
    return TeleopTiming(publish_period=0.1, command_timeout=0.4, stop_repeat_count=3)


@pytest.fixture
def teleop(
    backend: SimulatedMotionBackend,
    limits: VelocityLimits,
    timing: TeleopTiming,
    clock: FakeClock,
) -> TeleopService:
    return TeleopService(backend=backend, limits=limits, timing=timing, clock=clock)


@pytest.fixture
def ros_graph(monkeypatch: pytest.MonkeyPatch) -> FakeRosGraph:
    graph = FakeRosGraph()
    install(monkeypatch, graph)
    return graph
