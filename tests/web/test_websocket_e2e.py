"""End-to-end tests: real ASGI app, real WebSocket protocol, real clock, simulated robot."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from hemabot_ui.clock import MonotonicClock
from hemabot_ui.motion.backend import BackendError, BackendStatus, LinkState
from hemabot_ui.motion.simulated import SimulatedMotionBackend
from hemabot_ui.motion.velocity import STOP, VelocityCommand, VelocityLimits
from hemabot_ui.teleop.service import TeleopService, TeleopTiming
from hemabot_ui.web.app import create_app

COMMAND_TIMEOUT_S = 0.2
Message = dict[str, Any]


class ControllableBackend(SimulatedMotionBackend):
    """Simulated backend whose robot link state can be changed by the test."""

    def __init__(self) -> None:
        super().__init__()
        self.link = LinkState.CONNECTED
        self.shutdown_calls = 0

    def status(self) -> BackendStatus:
        return BackendStatus(self.link, f"test link {self.link.value}")

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        super().shutdown()


@pytest.fixture
def robot() -> ControllableBackend:
    return ControllableBackend()


@pytest.fixture
def client(robot: ControllableBackend) -> Iterator[TestClient]:
    teleop = TeleopService(
        backend=robot,
        limits=VelocityLimits(max_linear=0.4, max_angular=1.0),
        timing=TeleopTiming(
            publish_period=0.05, command_timeout=COMMAND_TIMEOUT_S, stop_repeat_count=2
        ),
        clock=MonotonicClock(),
    )
    app = create_app(backend=robot, teleop=teleop, status_interval_s=0.05)
    with TestClient(app) as test_client:
        yield test_client


def receive_until(
    ws: WebSocketTestSession, predicate: Callable[[Message], bool], limit: int = 50
) -> Message:
    for _ in range(limit):
        message: Message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message never arrived")


def is_state(**expected: Any) -> Callable[[Message], bool]:
    def check(message: Message) -> bool:
        return message["type"] == "state" and all(
            message.get(key) == value for key, value in expected.items()
        )

    return check


def is_error(code: str) -> Callable[[Message], bool]:
    return lambda message: message["type"] == "error" and message["code"] == code


def join(ws: WebSocketTestSession) -> str:
    welcome: Message = ws.receive_json()
    assert welcome["type"] == "welcome"
    return str(welcome["client_id"])


def wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


def test_welcome_announces_identity_and_limits(client: TestClient) -> None:
    with client.websocket_connect("/ws/teleop") as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["protocol_version"] == 1
        assert welcome["client_id"]
        assert welcome["limits"] == {"max_linear": 0.4, "max_angular": 1.0}
        state = receive_until(ws, is_state())
        assert state["clients"] == 1
        assert state["pilot_id"] is None
        assert state["robot"]["link"] == "connected"


def test_pilot_drives_the_robot(client: TestClient, robot: ControllableBackend) -> None:
    with client.websocket_connect("/ws/teleop") as ws:
        me = join(ws)
        ws.send_json({"type": "acquire"})
        receive_until(ws, is_state(pilot_id=me))
        ws.send_json({"type": "drive", "linear": 0.5, "angular": -0.5})
        wait_for(lambda: robot.last_command == VelocityCommand(linear=0.2, angular=-0.5))


def test_robot_stops_when_pilot_goes_silent(client: TestClient, robot: ControllableBackend) -> None:
    with client.websocket_connect("/ws/teleop") as ws:
        me = join(ws)
        ws.send_json({"type": "acquire"})
        receive_until(ws, is_state(pilot_id=me))
        ws.send_json({"type": "drive", "linear": 1, "angular": 0})
        wait_for(lambda: robot.last_command == VelocityCommand(0.4, 0.0))
        # No more drive messages: the watchdog must stop the robot on its own.
        wait_for(lambda: robot.last_command == STOP, timeout=COMMAND_TIMEOUT_S * 5)
        time.sleep(0.2)
        assert robot.last_command == STOP  # and it stays stopped


def test_continuous_drive_keeps_robot_moving(
    client: TestClient, robot: ControllableBackend
) -> None:
    with client.websocket_connect("/ws/teleop") as ws:
        me = join(ws)
        ws.send_json({"type": "acquire"})
        receive_until(ws, is_state(pilot_id=me))
        for _ in range(8):  # 0.4 s of driving, twice the command timeout
            ws.send_json({"type": "drive", "linear": 1, "angular": 0})
            time.sleep(0.05)
        assert robot.last_command == VelocityCommand(0.4, 0.0)
        assert STOP not in robot.history


def test_second_client_cannot_drive_or_acquire(
    client: TestClient, robot: ControllableBackend
) -> None:
    with (
        client.websocket_connect("/ws/teleop") as pilot,
        client.websocket_connect("/ws/teleop") as observer,
    ):
        pilot_id = join(pilot)
        join(observer)
        pilot.send_json({"type": "acquire"})
        receive_until(observer, is_state(pilot_id=pilot_id))

        observer.send_json({"type": "drive", "linear": 1, "angular": 0})
        receive_until(observer, is_error("not_pilot"))
        observer.send_json({"type": "acquire"})
        receive_until(observer, is_error("pilot_busy"))
        assert robot.history == []


def test_takeover_notifies_previous_pilot(client: TestClient, robot: ControllableBackend) -> None:
    with (
        client.websocket_connect("/ws/teleop") as first,
        client.websocket_connect("/ws/teleop") as second,
    ):
        first_id = join(first)
        second_id = join(second)
        first.send_json({"type": "acquire"})
        receive_until(first, is_state(pilot_id=first_id))
        first.send_json({"type": "drive", "linear": 1, "angular": 0})
        wait_for(lambda: robot.last_command == VelocityCommand(0.4, 0.0))

        second.send_json({"type": "acquire", "force": True})
        receive_until(first, is_state(pilot_id=second_id))
        wait_for(lambda: robot.last_command == STOP)

        first.send_json({"type": "drive", "linear": 1, "angular": 0})
        receive_until(first, is_error("not_pilot"))


def test_emergency_stop_from_observer(client: TestClient, robot: ControllableBackend) -> None:
    with (
        client.websocket_connect("/ws/teleop") as pilot,
        client.websocket_connect("/ws/teleop") as observer,
    ):
        pilot_id = join(pilot)
        join(observer)
        pilot.send_json({"type": "acquire"})
        receive_until(pilot, is_state(pilot_id=pilot_id))
        pilot.send_json({"type": "drive", "linear": 1, "angular": 0})
        wait_for(lambda: robot.last_command == VelocityCommand(0.4, 0.0))

        observer.send_json({"type": "stop"})
        receive_until(pilot, is_state(pilot_id=None))
        assert robot.last_command == STOP


def test_pilot_disconnect_stops_robot_and_frees_control(
    client: TestClient, robot: ControllableBackend
) -> None:
    with client.websocket_connect("/ws/teleop") as observer:
        join(observer)
        with client.websocket_connect("/ws/teleop") as pilot:
            pilot_id = join(pilot)
            pilot.send_json({"type": "acquire"})
            receive_until(observer, is_state(pilot_id=pilot_id))
            pilot.send_json({"type": "drive", "linear": 1, "angular": 0})
            wait_for(lambda: robot.last_command == VelocityCommand(0.4, 0.0))
        state = receive_until(observer, is_state(pilot_id=None))
        assert state["clients"] == 1
        assert robot.last_command == STOP


def test_invalid_messages_do_not_close_the_connection(client: TestClient) -> None:
    with client.websocket_connect("/ws/teleop") as ws:
        me = join(ws)
        ws.send_text("this is not json")
        receive_until(ws, is_error("invalid_message"))
        ws.send_json({"type": "drive", "linear": 99, "angular": 0})
        receive_until(ws, is_error("invalid_message"))
        ws.send_bytes(b'{"type": "acquire"}')
        receive_until(ws, is_state(pilot_id=me))


def test_robot_link_changes_are_pushed(client: TestClient, robot: ControllableBackend) -> None:
    with client.websocket_connect("/ws/teleop") as ws:
        join(ws)
        receive_until(ws, is_state())
        robot.link = LinkState.WAITING
        state = receive_until(
            ws, lambda m: m["type"] == "state" and m["robot"]["link"] == "waiting"
        )
        assert "waiting" in state["robot"]["detail"]


def test_health_endpoint(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["backend"] == "simulated"
    assert health["robot"]["link"] == "connected"
    assert health["pilot_active"] is False
    with client.websocket_connect("/ws/teleop") as ws:
        me = join(ws)
        ws.send_json({"type": "acquire"})
        receive_until(ws, is_state(pilot_id=me))
        health = client.get("/api/health").json()
        assert health["pilot_active"] is True
        assert health["clients"] == 1


def test_server_shutdown_stops_robot_and_releases_backend(robot: ControllableBackend) -> None:
    teleop = TeleopService(
        backend=robot,
        limits=VelocityLimits(0.4, 1.0),
        timing=TeleopTiming(publish_period=0.05, command_timeout=5.0, stop_repeat_count=1),
        clock=MonotonicClock(),
    )
    app = create_app(backend=robot, teleop=teleop, status_interval_s=1.0)
    with TestClient(app) as test_client, test_client.websocket_connect("/ws/teleop") as ws:
        me = join(ws)
        ws.send_json({"type": "acquire"})
        receive_until(ws, is_state(pilot_id=me))
        ws.send_json({"type": "drive", "linear": 1, "angular": 0})
        wait_for(lambda: robot.last_command == VelocityCommand(0.4, 0.0))
    assert robot.shutdown_calls == 1
    assert STOP in robot.history[1:]


def test_startup_fails_loudly_when_backend_cannot_start() -> None:
    class BrokenBackend(SimulatedMotionBackend):
        def start(self) -> None:
            raise BackendError("no ROS here")

    backend = BrokenBackend()
    teleop = TeleopService(
        backend, VelocityLimits(0.4, 1.0), TeleopTiming(0.1, 0.4, 1), MonotonicClock()
    )
    app = create_app(backend=backend, teleop=teleop, status_interval_s=1.0)
    with pytest.raises(BackendError, match="no ROS here"), TestClient(app):
        pass
