"""Message handling of the gateway, without any network involved."""

from __future__ import annotations

import pytest

from hemabot_ui.motion.simulated import SimulatedMotionBackend
from hemabot_ui.motion.velocity import STOP, VelocityCommand
from hemabot_ui.teleop.service import TeleopService
from hemabot_ui.web.gateway import TeleopGateway
from hemabot_ui.web.hub import ConnectionHub
from hemabot_ui.web.protocol import ErrorCode


@pytest.fixture
def gateway(teleop: TeleopService, backend: SimulatedMotionBackend) -> TeleopGateway:
    return TeleopGateway(teleop, backend, ConnectionHub())


def test_invalid_frame_returns_invalid_message_error(gateway: TeleopGateway) -> None:
    error = gateway.handle("a", '{"type": "drive", "linear": 2, "angular": 0}')
    assert error is not None
    assert error.code is ErrorCode.INVALID_MESSAGE
    assert "linear" in error.message


def test_garbage_frame_returns_error(gateway: TeleopGateway) -> None:
    error = gateway.handle("a", "\x00\x01garbage")
    assert error is not None
    assert error.code is ErrorCode.INVALID_MESSAGE


def test_drive_without_control_returns_not_pilot(
    gateway: TeleopGateway, backend: SimulatedMotionBackend
) -> None:
    error = gateway.handle("a", '{"type": "drive", "linear": 1, "angular": 0}')
    assert error is not None
    assert error.code is ErrorCode.NOT_PILOT
    assert backend.history == []


def test_acquire_then_drive(gateway: TeleopGateway, backend: SimulatedMotionBackend) -> None:
    assert gateway.handle("a", '{"type": "acquire"}') is None
    assert gateway.handle("a", '{"type": "drive", "linear": 1, "angular": 0.5}') is None
    assert backend.last_command == VelocityCommand(linear=0.4, angular=0.5)


def test_second_acquire_reports_busy(gateway: TeleopGateway) -> None:
    gateway.handle("a", '{"type": "acquire"}')
    error = gateway.handle("b", '{"type": "acquire"}')
    assert error is not None
    assert error.code is ErrorCode.PILOT_BUSY


def test_forced_acquire_takes_over(gateway: TeleopGateway, teleop: TeleopService) -> None:
    gateway.handle("a", '{"type": "acquire"}')
    assert gateway.handle("b", '{"type": "acquire", "force": true}') is None
    assert teleop.pilot_id == "b"


def test_stop_from_anyone(gateway: TeleopGateway, backend: SimulatedMotionBackend) -> None:
    gateway.handle("a", '{"type": "acquire"}')
    gateway.handle("a", '{"type": "drive", "linear": 1, "angular": 0}')
    assert gateway.handle("b", '{"type": "stop"}') is None
    assert backend.last_command == STOP


def test_release(gateway: TeleopGateway, teleop: TeleopService) -> None:
    gateway.handle("a", '{"type": "acquire"}')
    assert gateway.handle("a", '{"type": "release"}') is None
    assert teleop.pilot_id is None


def test_current_state_reflects_pilot_and_robot(
    gateway: TeleopGateway, teleop: TeleopService
) -> None:
    teleop.acquire("a")
    state = gateway.current_state()
    assert state.pilot_id == "a"
    assert state.robot.link == "connected"
    assert state.clients == 0
