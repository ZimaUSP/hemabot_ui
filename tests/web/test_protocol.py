import json

import pytest
from pydantic import ValidationError

from hemabot_ui.web.protocol import (
    AcquireMessage,
    DriveMessage,
    ErrorCode,
    ErrorMessage,
    ReleaseMessage,
    StopMessage,
    parse_client_message,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"type": "acquire"}', AcquireMessage(type="acquire", force=False)),
        ('{"type": "acquire", "force": true}', AcquireMessage(type="acquire", force=True)),
        ('{"type": "release"}', ReleaseMessage(type="release")),
        ('{"type": "stop"}', StopMessage(type="stop")),
        (
            '{"type": "drive", "linear": 0.5, "angular": -1}',
            DriveMessage(type="drive", linear=0.5, angular=-1.0),
        ),
    ],
)
def test_parses_valid_messages(raw: str, expected: object) -> None:
    assert parse_client_message(raw) == expected


def test_accepts_bytes_frames() -> None:
    assert parse_client_message(b'{"type": "stop"}') == StopMessage(type="stop")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"type": "fly"}',
        '{"type": "drive", "linear": 0.5}',
        '{"type": "drive", "linear": 1.5, "angular": 0}',
        '{"type": "drive", "linear": "fast", "angular": 0}',
        '{"type": "drive", "linear": NaN, "angular": 0}',
        '{"type": "drive", "linear": Infinity, "angular": 0}',
        '{"type": "stop", "extra": 1}',
        '{"type": "acquire", "force": "maybe"}',
        "[]",
    ],
)
def test_rejects_invalid_messages(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse_client_message(raw)


def test_error_message_serializes_code_as_string() -> None:
    payload = json.loads(ErrorMessage(code=ErrorCode.NOT_PILOT, message="x").model_dump_json())
    assert payload == {"type": "error", "code": "not_pilot", "message": "x"}
