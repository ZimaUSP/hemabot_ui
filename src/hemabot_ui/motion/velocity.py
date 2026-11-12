"""Velocity value objects.

Conventions follow ROS REP 103: positive linear velocity drives forward and positive
angular velocity turns counter-clockwise (to the left), seen from above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _clamp_unit(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"drive intent components must be finite, got {value!r}")
    return max(-1.0, min(1.0, float(value)))


@dataclass(frozen=True)
class DriveIntent:
    """What the operator wants, normalized to [-1, 1] on each axis.

    The intent is independent of the robot's physical limits: 1.0 means "as fast as
    the robot is allowed to go". Out-of-range values are clamped so a misbehaving
    client can never exceed the configured limits.
    """

    linear: float
    angular: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "linear", _clamp_unit(self.linear))
        object.__setattr__(self, "angular", _clamp_unit(self.angular))

    @property
    def is_idle(self) -> bool:
        return self.linear == 0.0 and self.angular == 0.0


@dataclass(frozen=True)
class VelocityCommand:
    """Physical velocity sent to the robot base."""

    linear: float
    """Forward velocity in m/s."""
    angular: float
    """Yaw rate in rad/s."""

    @property
    def is_zero(self) -> bool:
        return self.linear == 0.0 and self.angular == 0.0


STOP = VelocityCommand(linear=0.0, angular=0.0)


@dataclass(frozen=True)
class VelocityLimits:
    """Maximum absolute velocities the operator may command."""

    max_linear: float
    """m/s"""
    max_angular: float
    """rad/s"""

    def __post_init__(self) -> None:
        for name in ("max_linear", "max_angular"):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive finite number, got {value!r}")

    def scale(self, intent: DriveIntent) -> VelocityCommand:
        return VelocityCommand(
            linear=intent.linear * self.max_linear,
            angular=intent.angular * self.max_angular,
        )
