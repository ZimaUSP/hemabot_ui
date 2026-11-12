"""ROS 2 backend: publishes ``geometry_msgs/Twist`` messages on a velocity topic.

On the Hemabot the default topic is ``/cmd_vel_joy``, one of the inputs of the
``twist_mux`` started by ``minihema_launch``, which forwards it to
``/diff_controller/cmd_vel_unstamped``.

``rclpy`` is imported lazily so the rest of the application (and its tests) works on
machines without ROS installed.
"""

from __future__ import annotations

import logging
from typing import Any

from hemabot_ui.motion.backend import BackendError, BackendStatus, LinkState
from hemabot_ui.motion.velocity import STOP, VelocityCommand

logger = logging.getLogger(__name__)

_QOS_DEPTH = 10


class Ros2MotionBackend:
    def __init__(self, topic: str, node_name: str) -> None:
        self._topic = topic
        self._node_name = node_name
        self._rclpy: Any = None
        self._twist_type: Any = None
        self._context: Any = None
        self._node: Any = None
        self._publisher: Any = None

    @property
    def name(self) -> str:
        return "ros2"

    @property
    def topic(self) -> str:
        return self._topic

    def start(self) -> None:
        if self._node is not None:
            return
        try:
            import rclpy
            from geometry_msgs.msg import Twist
        except ImportError as error:
            raise BackendError(
                "rclpy is not importable. Source ROS 2 before starting "
                "(source /opt/ros/humble/setup.bash) and make sure the virtualenv was "
                f"created with --system-site-packages. Original error: {error}"
            ) from error

        self._rclpy = rclpy
        self._twist_type = Twist
        self._context = rclpy.Context()
        _init_without_signal_handlers(rclpy, self._context)
        self._node = rclpy.create_node(self._node_name, context=self._context)
        self._publisher = self._node.create_publisher(Twist, self._topic, _QOS_DEPTH)
        # A publisher-only node needs no executor: publishing and graph queries do not
        # require spinning. Add one here when subscriptions/services are introduced.
        logger.info("ROS 2 node '%s' publishing on %s", self._node_name, self._topic)

    def shutdown(self) -> None:
        if self._node is None:
            return
        try:
            self.send(STOP)
            self._node.destroy_node()
        finally:
            if self._context.ok():
                self._rclpy.shutdown(context=self._context)
            self._node = None
            self._publisher = None
            logger.info("ROS 2 node '%s' shut down", self._node_name)

    def send(self, command: VelocityCommand) -> None:
        if self._publisher is None:
            return
        message = self._twist_type()
        # rclpy rejects ints in float fields, hence the explicit conversions.
        message.linear.x = float(command.linear)
        message.angular.z = float(command.angular)
        self._publisher.publish(message)

    def status(self) -> BackendStatus:
        if self._publisher is None:
            return BackendStatus(LinkState.OFFLINE, "ROS 2 node not started")
        subscribers = self._publisher.get_subscription_count()
        if subscribers == 0:
            return BackendStatus(
                LinkState.WAITING,
                f"no subscribers on {self._topic}; is the robot bringup (twist_mux) running?",
            )
        return BackendStatus(LinkState.CONNECTED, f"{subscribers} subscriber(s) on {self._topic}")


def _init_without_signal_handlers(rclpy: Any, context: Any) -> None:
    """Initialize rclpy without letting it take over SIGINT/SIGTERM.

    The web server owns process signals and shuts the node down itself; rclpy's
    handlers would otherwise intercept Ctrl+C / systemd stop requests.
    """
    try:
        from rclpy.signals import SignalHandlerOptions
    except ImportError:  # pragma: no cover - only very old distros lack it
        rclpy.init(args=[], context=context)
        return
    rclpy.init(args=[], context=context, signal_handler_options=SignalHandlerOptions.NO)
