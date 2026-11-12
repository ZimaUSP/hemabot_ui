"""Integration tests against a REAL ROS 2 installation.

They are skipped by default. Run them on the robot with:

    source /opt/ros/humble/setup.bash
    .venv/bin/python -m pytest -m ros

They use a private, randomly named topic, so they do not move the robot and can run
while the bringup is up.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from hemabot_ui.motion.backend import LinkState
from hemabot_ui.motion.ros2 import Ros2MotionBackend
from hemabot_ui.motion.velocity import STOP, VelocityCommand

rclpy = pytest.importorskip("rclpy", reason="ROS 2 is not sourced")
pytestmark = pytest.mark.ros


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


class TwistListener:
    """A separate ROS context subscribing to the topic, spun in a background thread."""

    def __init__(self, topic: str) -> None:
        from geometry_msgs.msg import Twist
        from rclpy.executors import SingleThreadedExecutor

        self.received: list[tuple[float, float]] = []
        self._context = rclpy.Context()
        rclpy.init(args=[], context=self._context)
        self._node = rclpy.create_node(f"listener_{uuid.uuid4().hex[:6]}", context=self._context)
        self._node.create_subscription(Twist, topic, self._on_message, 10)
        self._executor = SingleThreadedExecutor(context=self._context)
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._thread.start()

    def _on_message(self, message: Any) -> None:
        self.received.append((message.linear.x, message.angular.z))

    def close(self) -> None:
        self._executor.shutdown()
        self._node.destroy_node()
        rclpy.shutdown(context=self._context)
        self._thread.join(timeout=5)


@pytest.fixture
def topic() -> str:
    return f"/hemabot_ui_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def backend(topic: str) -> Iterator[Ros2MotionBackend]:
    ros_backend = Ros2MotionBackend(
        topic=topic, node_name=f"hemabot_ui_test_{uuid.uuid4().hex[:6]}"
    )
    ros_backend.start()
    yield ros_backend
    ros_backend.shutdown()


def test_status_follows_subscribers(backend: Ros2MotionBackend, topic: str) -> None:
    assert backend.status().link is LinkState.WAITING
    listener = TwistListener(topic)
    try:
        assert wait_until(lambda: backend.status().link is LinkState.CONNECTED)
    finally:
        listener.close()


def test_commands_reach_a_real_subscriber(backend: Ros2MotionBackend, topic: str) -> None:
    listener = TwistListener(topic)
    try:
        assert wait_until(lambda: backend.status().link is LinkState.CONNECTED)
        command = VelocityCommand(linear=0.25, angular=-0.5)
        assert wait_until(lambda: (backend.send(command), command_received(listener, command))[1])
        backend.send(STOP)
        assert wait_until(lambda: listener.received[-1] == (0.0, 0.0))
    finally:
        listener.close()


def command_received(listener: TwistListener, command: VelocityCommand) -> bool:
    return (command.linear, command.angular) in listener.received


def test_shutdown_and_restart(topic: str) -> None:
    backend = Ros2MotionBackend(topic=topic, node_name=f"hemabot_ui_test_{uuid.uuid4().hex[:6]}")
    backend.start()
    backend.shutdown()
    backend.start()
    backend.send(VelocityCommand(0.1, 0.0))
    backend.shutdown()
