"""Minimal, strict stand-in for the parts of rclpy / geometry_msgs the app uses.

It mirrors the real ROS 2 Humble API signatures and, importantly, the behaviour that
bites in production: generated message setters reject non-float values for float64
fields, ``rclpy.init`` only accepts keyword arguments and a context cannot be
initialized twice.
"""

from __future__ import annotations

import enum
import sys
import types
from dataclasses import dataclass, field
from typing import Any


class _Vector3:
    __slots__ = ("_x", "_y", "_z")

    def __init__(self) -> None:
        self._x = 0.0
        self._y = 0.0
        self._z = 0.0

    def _check(self, value: Any) -> float:
        # Same assertion rclpy's generated code makes for float64 fields.
        assert isinstance(value, float), "The field must be of type 'float'"
        return value

    x = property(lambda self: self._x, lambda self, v: setattr(self, "_x", self._check(v)))
    y = property(lambda self: self._y, lambda self, v: setattr(self, "_y", self._check(v)))
    z = property(lambda self: self._z, lambda self, v: setattr(self, "_z", self._check(v)))


class Twist:
    def __init__(self) -> None:
        self.linear = _Vector3()
        self.angular = _Vector3()


@dataclass
class FakeRosGraph:
    """Shared state of the fake ROS world, inspected by tests."""

    subscribers: dict[str, int] = field(default_factory=dict)
    external_nodes: list[str] = field(default_factory=list)
    published: list[tuple[str, Any]] = field(default_factory=list)
    init_calls: list[dict[str, Any]] = field(default_factory=list)
    live_nodes: list[FakeNode] = field(default_factory=list)


class SignalHandlerOptions(enum.Enum):
    NO = 0
    SIGINT = 1
    SIGTERM = 2
    ALL = 3


class FakeContext:
    def __init__(self) -> None:
        self._ok = False

    def ok(self) -> bool:
        return self._ok


class FakePublisher:
    def __init__(self, graph: FakeRosGraph, msg_type: type, topic: str) -> None:
        self._graph = graph
        self._msg_type = msg_type
        self.topic = topic
        self.destroyed = False

    def publish(self, message: Any) -> None:
        assert not self.destroyed, "publishing on a destroyed publisher"
        assert isinstance(message, self._msg_type), "message type mismatch"
        self._graph.published.append((self.topic, message))

    def get_subscription_count(self) -> int:
        return self._graph.subscribers.get(self.topic, 0)


class FakeNode:
    def __init__(self, graph: FakeRosGraph, name: str, context: FakeContext) -> None:
        assert context.ok(), "node created on a context that is not initialized"
        self._graph = graph
        self.name = name
        self.destroyed = False
        self.publishers: list[FakePublisher] = []

    def create_publisher(self, msg_type: type, topic: str, qos_profile: Any) -> FakePublisher:
        assert isinstance(qos_profile, int) or qos_profile is not None
        publisher = FakePublisher(self._graph, msg_type, topic)
        self.publishers.append(publisher)
        return publisher

    def count_subscribers(self, topic: str) -> int:
        return self._graph.subscribers.get(topic, 0)

    def get_node_names(self) -> list[str]:
        return [*self._graph.external_nodes, *(n.name for n in self._graph.live_nodes)]

    def destroy_node(self) -> None:
        for publisher in self.publishers:
            publisher.destroyed = True
        self.destroyed = True
        self._graph.live_nodes.remove(self)


def install(monkeypatch: Any, graph: FakeRosGraph) -> None:
    """Register fake ``rclpy``, ``rclpy.signals`` and ``geometry_msgs.msg`` modules."""
    rclpy = types.ModuleType("rclpy")
    rclpy.__file__ = "/fake/rclpy/__init__.py"
    rclpy.Context = FakeContext  # type: ignore[attr-defined]

    def init(
        *,
        args: list[str] | None = None,
        context: FakeContext | None = None,
        domain_id: int | None = None,
        signal_handler_options: SignalHandlerOptions | None = None,
    ) -> None:
        assert context is not None, "the app must use its own context"
        if context.ok():
            raise RuntimeError("Context.init() must only be called once")
        graph.init_calls.append({"args": args, "signal_handler_options": signal_handler_options})
        context._ok = True

    def create_node(node_name: str, *, context: FakeContext | None = None) -> FakeNode:
        assert context is not None
        node = FakeNode(graph, node_name, context)
        graph.live_nodes.append(node)
        return node

    def shutdown(*, context: FakeContext | None = None) -> None:
        assert context is not None
        if not context.ok():
            raise RuntimeError("Context must be initialized before it can be shutdown")
        context._ok = False

    rclpy.init = init  # type: ignore[attr-defined]
    rclpy.create_node = create_node  # type: ignore[attr-defined]
    rclpy.shutdown = shutdown  # type: ignore[attr-defined]

    signals = types.ModuleType("rclpy.signals")
    signals.SignalHandlerOptions = SignalHandlerOptions  # type: ignore[attr-defined]
    rclpy.signals = signals  # type: ignore[attr-defined]

    geometry_msgs = types.ModuleType("geometry_msgs")
    geometry_msgs_msg = types.ModuleType("geometry_msgs.msg")
    geometry_msgs_msg.Twist = Twist  # type: ignore[attr-defined]
    geometry_msgs.msg = geometry_msgs_msg  # type: ignore[attr-defined]

    for name, module in {
        "rclpy": rclpy,
        "rclpy.signals": signals,
        "geometry_msgs": geometry_msgs,
        "geometry_msgs.msg": geometry_msgs_msg,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def hide_ros(monkeypatch: Any) -> None:
    """Make ``import rclpy`` fail, as on a machine without ROS sourced."""
    for name in ("rclpy", "rclpy.signals", "geometry_msgs", "geometry_msgs.msg"):
        monkeypatch.setitem(sys.modules, name, None)
