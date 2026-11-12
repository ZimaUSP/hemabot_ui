from __future__ import annotations

from typing import Any

import pytest

from hemabot_ui import cli
from hemabot_ui.config import Settings


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(cli, "_serve", lambda settings: calls.setdefault("serve", settings) and 0)
    monkeypatch.setattr(
        "hemabot_ui.doctor.run_doctor", lambda settings: calls.setdefault("doctor", settings) and 7
    )
    return calls


def test_serve_is_the_default_command(captured: dict[str, Any]) -> None:
    assert cli.main([]) == 0
    assert isinstance(captured["serve"], Settings)


def test_command_line_overrides_environment(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEMABOT_UI_PORT", "80")
    cli.main(["serve", "--port", "9000", "--backend", "simulated", "--host", "127.0.0.1"])
    settings = captured["serve"]
    assert (settings.port, settings.backend, settings.host) == (9000, "simulated", "127.0.0.1")


def test_environment_is_used_without_overrides(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEMABOT_UI_PORT", "80")
    cli.main(["serve"])
    assert captured["serve"].port == 80


def test_doctor_returns_its_exit_code(captured: dict[str, Any]) -> None:
    assert cli.main(["doctor"]) == 7


def test_invalid_configuration_exits_with_usage_error(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HEMABOT_UI_MAX_LINEAR_SPEED", "-1")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["serve"])
    assert exit_info.value.code == 2
    assert "max_linear_speed" in capsys.readouterr().err


def test_invalid_backend_choice_is_rejected(captured: dict[str, Any]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["serve", "--backend", "gazebo"])
