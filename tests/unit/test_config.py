import pytest
from pydantic import ValidationError

from hemabot_ui.bootstrap import build_backend, build_teleop
from hemabot_ui.config import Settings
from hemabot_ui.motion.ros2 import Ros2MotionBackend
from hemabot_ui.motion.simulated import SimulatedMotionBackend


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in list(os.environ):
        if name.startswith("HEMABOT_UI_"):
            monkeypatch.delenv(name)


def test_defaults_match_the_robot_setup() -> None:
    settings = Settings()
    assert settings.backend == "ros2"
    assert settings.cmd_vel_topic == "/cmd_vel_joy"
    assert settings.max_linear_speed == 0.4
    assert settings.max_angular_speed == 1.0
    assert settings.host == "0.0.0.0"


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEMABOT_UI_PORT", "80")
    monkeypatch.setenv("HEMABOT_UI_BACKEND", "simulated")
    monkeypatch.setenv("HEMABOT_UI_MAX_LINEAR_SPEED", "0.25")
    settings = Settings()
    assert (settings.port, settings.backend, settings.max_linear_speed) == (80, "simulated", 0.25)


def test_ignores_unrelated_variables_in_shared_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEMABOT_UI_SOMETHING_NEW", "x")
    Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HEMABOT_UI_BACKEND", "gazebo"),
        ("HEMABOT_UI_PORT", "70000"),
        ("HEMABOT_UI_MAX_LINEAR_SPEED", "0"),
        ("HEMABOT_UI_MAX_LINEAR_SPEED", "5"),
        ("HEMABOT_UI_PUBLISH_RATE_HZ", "-1"),
    ],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_timeout_must_exceed_publish_period() -> None:
    with pytest.raises(ValidationError, match="command_timeout_s"):
        Settings(publish_rate_hz=2, command_timeout_s=0.4)


def test_build_backend_selects_implementation() -> None:
    assert isinstance(build_backend(Settings(backend="simulated")), SimulatedMotionBackend)
    ros = build_backend(Settings(backend="ros2", cmd_vel_topic="/x"))
    assert isinstance(ros, Ros2MotionBackend)
    assert ros.topic == "/x"


def test_build_teleop_uses_configured_limits() -> None:
    settings = Settings(backend="simulated", max_linear_speed=0.3, max_angular_speed=0.8)
    teleop = build_teleop(settings, build_backend(settings))
    assert (teleop.limits.max_linear, teleop.limits.max_angular) == (0.3, 0.8)
