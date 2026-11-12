import math

import pytest

from hemabot_ui.motion.velocity import STOP, DriveIntent, VelocityCommand, VelocityLimits


class TestDriveIntent:
    def test_keeps_values_inside_unit_interval(self) -> None:
        intent = DriveIntent(linear=0.5, angular=-0.25)
        assert (intent.linear, intent.angular) == (0.5, -0.25)

    @pytest.mark.parametrize(("raw", "clamped"), [(1.5, 1.0), (-7.0, -1.0), (1, 1.0)])
    def test_clamps_out_of_range_values(self, raw: float, clamped: float) -> None:
        intent = DriveIntent(linear=raw, angular=raw)
        assert intent.linear == clamped
        assert intent.angular == clamped

    def test_converts_ints_to_floats(self) -> None:
        intent = DriveIntent(linear=1, angular=0)
        assert isinstance(intent.linear, float)
        assert isinstance(intent.angular, float)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_rejects_non_finite_values(self, bad: float) -> None:
        with pytest.raises(ValueError, match="finite"):
            DriveIntent(linear=bad, angular=0.0)

    def test_idle_only_when_both_axes_are_zero(self) -> None:
        assert DriveIntent(0.0, 0.0).is_idle
        assert not DriveIntent(0.0, 0.1).is_idle
        assert not DriveIntent(-0.1, 0.0).is_idle


class TestVelocityLimits:
    def test_scales_intent_to_physical_velocity(self) -> None:
        limits = VelocityLimits(max_linear=0.4, max_angular=1.0)
        assert limits.scale(DriveIntent(0.5, -1.0)) == VelocityCommand(linear=0.2, angular=-1.0)

    def test_scaled_command_never_exceeds_limits(self) -> None:
        limits = VelocityLimits(max_linear=0.4, max_angular=1.0)
        command = limits.scale(DriveIntent(10.0, -10.0))
        assert command.linear == pytest.approx(0.4)
        assert command.angular == pytest.approx(-1.0)

    @pytest.mark.parametrize("bad", [0.0, -0.1, math.inf, math.nan])
    def test_rejects_invalid_limits(self, bad: float) -> None:
        with pytest.raises(ValueError):
            VelocityLimits(max_linear=bad, max_angular=1.0)
        with pytest.raises(ValueError):
            VelocityLimits(max_linear=1.0, max_angular=bad)


def test_stop_is_zero() -> None:
    assert STOP.is_zero
    assert not VelocityCommand(0.1, 0.0).is_zero
