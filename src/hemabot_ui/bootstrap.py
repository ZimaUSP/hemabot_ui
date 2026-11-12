"""Composition root: turns ``Settings`` into a fully wired application."""

from __future__ import annotations

from fastapi import FastAPI

from hemabot_ui.clock import MonotonicClock
from hemabot_ui.config import Settings
from hemabot_ui.motion.backend import MotionBackend
from hemabot_ui.motion.ros2 import Ros2MotionBackend
from hemabot_ui.motion.simulated import SimulatedMotionBackend
from hemabot_ui.motion.velocity import VelocityLimits
from hemabot_ui.teleop.service import TeleopService, TeleopTiming
from hemabot_ui.web.app import create_app


def build_backend(settings: Settings) -> MotionBackend:
    if settings.backend == "ros2":
        return Ros2MotionBackend(topic=settings.cmd_vel_topic, node_name=settings.ros_node_name)
    return SimulatedMotionBackend()


def build_teleop(settings: Settings, backend: MotionBackend) -> TeleopService:
    return TeleopService(
        backend=backend,
        limits=VelocityLimits(
            max_linear=settings.max_linear_speed, max_angular=settings.max_angular_speed
        ),
        timing=TeleopTiming(
            publish_period=1.0 / settings.publish_rate_hz,
            command_timeout=settings.command_timeout_s,
            stop_repeat_count=settings.stop_repeat_count,
        ),
        clock=MonotonicClock(),
    )


def build_app(settings: Settings) -> FastAPI:
    backend = build_backend(settings)
    return create_app(
        backend=backend,
        teleop=build_teleop(settings, backend),
        status_interval_s=settings.status_interval_s,
    )
