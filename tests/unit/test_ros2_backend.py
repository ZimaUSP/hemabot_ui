from __future__ import annotations

import re

import pytest

from hemabot_ui.motion.backend import BackendError, LinkState
from hemabot_ui.motion.ros2 import Ros2MotionBackend
from hemabot_ui.motion.velocity import STOP, VelocityCommand
from tests.fakes.fake_rclpy import FakeRosGraph, SignalHandlerOptions, hide_ros

TOPIC = "/cmd_vel_joy"


@pytest.fixture
def ros_backend(ros_graph: FakeRosGraph) -> Ros2MotionBackend:
    return Ros2MotionBackend(topic=TOPIC, node_name="hemabot_ui")


def published_values(graph: FakeRosGraph) -> list[tuple[str, float, float]]:
    return [(topic, msg.linear.x, msg.angular.z) for topic, msg in graph.published]


def test_publishes_twist_on_configured_topic(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.start()
    ros_backend.send(VelocityCommand(linear=0.2, angular=-0.5))
    assert published_values(ros_graph) == [(TOPIC, 0.2, -0.5)]


def test_integer_velocities_are_converted_to_float(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    # rclpy raises AssertionError when an int is assigned to a float64 field.
    ros_backend.start()
    ros_backend.send(VelocityCommand(linear=1, angular=0))  # type: ignore[arg-type]
    assert published_values(ros_graph) == [(TOPIC, 1.0, 0.0)]


def test_other_twist_fields_stay_zero(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.start()
    ros_backend.send(VelocityCommand(linear=0.3, angular=0.7))
    _, message = ros_graph.published[0]
    assert (message.linear.y, message.linear.z) == (0.0, 0.0)
    assert (message.angular.x, message.angular.y) == (0.0, 0.0)


def test_rclpy_does_not_install_signal_handlers(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.start()
    assert ros_graph.init_calls == [{"args": [], "signal_handler_options": SignalHandlerOptions.NO}]


def test_creates_node_with_configured_name(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.start()
    assert [node.name for node in ros_graph.live_nodes] == ["hemabot_ui"]


def test_start_twice_is_harmless(ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph) -> None:
    ros_backend.start()
    ros_backend.start()
    assert len(ros_graph.init_calls) == 1


def test_send_before_start_is_ignored(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.send(VelocityCommand(0.1, 0.0))
    assert ros_graph.published == []


def test_shutdown_publishes_stop_and_destroys_node(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.start()
    ros_backend.send(VelocityCommand(0.3, 0.0))
    ros_backend.shutdown()
    assert published_values(ros_graph)[-1] == (TOPIC, STOP.linear, STOP.angular)
    assert ros_graph.live_nodes == []
    ros_backend.send(VelocityCommand(0.3, 0.0))  # after shutdown: ignored, no crash
    assert len(ros_graph.published) == 2


def test_shutdown_is_idempotent(ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph) -> None:
    ros_backend.start()
    ros_backend.shutdown()
    ros_backend.shutdown()


def test_can_restart_after_shutdown(
    ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
) -> None:
    ros_backend.start()
    ros_backend.shutdown()
    ros_backend.start()
    ros_backend.send(VelocityCommand(0.1, 0.0))
    assert published_values(ros_graph)[-1] == (TOPIC, 0.1, 0.0)


class TestStatus:
    def test_offline_before_start(self, ros_backend: Ros2MotionBackend) -> None:
        assert ros_backend.status().link is LinkState.OFFLINE

    def test_waiting_without_subscribers(
        self, ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
    ) -> None:
        ros_backend.start()
        status = ros_backend.status()
        assert status.link is LinkState.WAITING
        assert TOPIC in status.detail

    def test_connected_when_twist_mux_subscribes(
        self, ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
    ) -> None:
        ros_backend.start()
        ros_graph.subscribers[TOPIC] = 1
        assert ros_backend.status().link is LinkState.CONNECTED

    def test_offline_after_shutdown(
        self, ros_backend: Ros2MotionBackend, ros_graph: FakeRosGraph
    ) -> None:
        ros_backend.start()
        ros_backend.shutdown()
        assert ros_backend.status().link is LinkState.OFFLINE


def test_missing_ros_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    hide_ros(monkeypatch)
    backend = Ros2MotionBackend(topic=TOPIC, node_name="hemabot_ui")
    with pytest.raises(BackendError, match=re.escape("source /opt/ros/humble/setup.bash")):
        backend.start()
