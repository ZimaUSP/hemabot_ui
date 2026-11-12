"""Application settings, read from ``HEMABOT_UI_*`` environment variables.

On the robot they come from ``/etc/hemabot/hemabot.env`` (loaded by systemd).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BackendName = Literal["ros2", "simulated"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HEMABOT_UI_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    backend: BackendName = "ros2"
    cmd_vel_topic: str = "/cmd_vel_joy"
    ros_node_name: str = "hemabot_ui"

    # Defaults match the physical joystick scales in d_hospital_teleop/config/joystick.yaml.
    max_linear_speed: float = Field(default=0.4, gt=0, le=2.0, description="m/s")
    max_angular_speed: float = Field(default=1.0, gt=0, le=6.0, description="rad/s")

    publish_rate_hz: float = Field(default=10.0, gt=0, le=100)
    # Must stay below twist_mux's 0.5 s topic timeout so stops are explicit, not implicit.
    command_timeout_s: float = Field(default=0.4, gt=0)
    stop_repeat_count: int = Field(default=3, ge=1, le=50)
    status_interval_s: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _timeout_longer_than_publish_period(self) -> Settings:
        if self.command_timeout_s <= 1.0 / self.publish_rate_hz:
            raise ValueError("command_timeout_s must be longer than 1 / publish_rate_hz")
        return self
