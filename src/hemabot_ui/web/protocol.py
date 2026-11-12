"""JSON messages exchanged over the teleoperation WebSocket.

Client -> server
    {"type": "acquire", "force": false}   request pilot control (force = take over)
    {"type": "release"}                   give control back
    {"type": "drive", "linear": 0.5, "angular": -0.2}
                                          normalized intent in [-1, 1]; positive angular
                                          turns left (ROS REP 103). Pilots must resend it
                                          continuously (~10 Hz) while moving.
    {"type": "stop"}                      emergency stop; any client may send it

Server -> client
    welcome  sent once after connecting
    state    broadcast to every client whenever the shared state changes
    error    reply to a message that could not be honored
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 1


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- client -> server -----------------------------------------------------------------

UnitInterval = Annotated[float, Field(ge=-1.0, le=1.0, allow_inf_nan=False)]


class AcquireMessage(_Message):
    type: Literal["acquire"]
    force: bool = False


class ReleaseMessage(_Message):
    type: Literal["release"]


class DriveMessage(_Message):
    type: Literal["drive"]
    linear: UnitInterval
    angular: UnitInterval


class StopMessage(_Message):
    type: Literal["stop"]


ClientMessage = Annotated[
    AcquireMessage | ReleaseMessage | DriveMessage | StopMessage,
    Field(discriminator="type"),
]

_client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def parse_client_message(raw: str | bytes) -> ClientMessage:
    """Parse and validate a raw client frame. Raises ``pydantic.ValidationError``."""
    return _client_message_adapter.validate_json(raw)


# --- server -> client -----------------------------------------------------------------


class ErrorCode(str, Enum):
    INVALID_MESSAGE = "invalid_message"
    NOT_PILOT = "not_pilot"
    PILOT_BUSY = "pilot_busy"


class Limits(_Message):
    max_linear: float
    max_angular: float


class WelcomeMessage(_Message):
    type: Literal["welcome"] = "welcome"
    protocol_version: int = PROTOCOL_VERSION
    client_id: str
    limits: Limits


class RobotState(_Message):
    link: str
    detail: str


class StateMessage(_Message):
    type: Literal["state"] = "state"
    pilot_id: str | None
    clients: int
    robot: RobotState


class ErrorMessage(_Message):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str


ServerMessage = WelcomeMessage | StateMessage | ErrorMessage
