from __future__ import annotations

import io
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hemabot_ui import doctor
from hemabot_ui.config import Settings
from hemabot_ui.doctor import CheckResult, Severity, run_doctor
from tests.fakes.fake_rclpy import FakeRosGraph, hide_ros


@pytest.fixture(autouse=True)
def _fast_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "ROS_DISCOVERY_TIMEOUT_S", 0.3)


def severities(results: list[CheckResult]) -> dict[str, Severity]:
    return {result.name: result.severity for result in results}


class TestRosEnvironment:
    def test_fails_without_ros_distro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ROS_DISTRO", raising=False)
        [result] = doctor.check_ros_environment(Settings())
        assert result.severity is Severity.FAIL

    def test_warns_on_other_distro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROS_DISTRO", "jazzy")
        [result] = doctor.check_ros_environment(Settings())
        assert result.severity is Severity.WARN

    def test_ok_on_humble(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROS_DISTRO", "humble")
        [result] = doctor.check_ros_environment(Settings())
        assert result.severity is Severity.OK


class TestRosGraph:
    def test_all_ok_when_bringup_is_running(self, ros_graph: FakeRosGraph) -> None:
        ros_graph.subscribers["/cmd_vel_joy"] = 1
        ros_graph.external_nodes.extend(["twist_mux", "controller_manager"])
        results = list(doctor.check_ros_graph(Settings()))
        assert set(severities(results).values()) == {Severity.OK}
        assert ros_graph.live_nodes == []  # doctor cleans up its node

    def test_fails_when_nobody_subscribes(self, ros_graph: FakeRosGraph) -> None:
        results = severities(list(doctor.check_ros_graph(Settings())))
        assert results["velocity topic"] is Severity.FAIL
        assert results["node twist_mux"] is Severity.WARN

    def test_fails_when_rclpy_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hide_ros(monkeypatch)
        [result] = doctor.check_ros_graph(Settings())
        assert (result.name, result.severity) == ("rclpy", Severity.FAIL)

    def test_skipped_for_simulated_backend(self) -> None:
        [result] = doctor.check_ros_graph(Settings(backend="simulated"))
        assert result.severity is Severity.WARN


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'{"status": "ok", "backend": "ros2", "robot": {"link": "connected"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def health_server() -> Iterator[int]:
    server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


class TestWebServer:
    def test_ok_when_health_endpoint_answers(self, health_server: int) -> None:
        [result] = doctor.check_web_server(Settings(port=health_server))
        assert result.severity is Severity.OK
        assert "robot link=connected" in result.detail

    def test_warns_when_server_is_down(self, unused_tcp_port: int) -> None:
        [result] = doctor.check_web_server(Settings(port=unused_tcp_port))
        assert result.severity is Severity.WARN


class TestReport:
    def test_exit_code_reflects_failures(self) -> None:
        def ok(_: Settings) -> list[CheckResult]:
            return [CheckResult("a", Severity.OK, "fine")]

        def warn(_: Settings) -> list[CheckResult]:
            return [CheckResult("b", Severity.WARN, "hmm")]

        def fail(_: Settings) -> list[CheckResult]:
            return [CheckResult("c", Severity.FAIL, "broken")]

        out = io.StringIO()
        assert run_doctor(Settings(), [ok, warn], out) == 0
        assert run_doctor(Settings(), [ok, fail], out) == 1
        assert "[FAIL] c: broken" in out.getvalue()

    def test_crashing_check_is_reported_as_failure(self) -> None:
        def crash(_: Settings) -> list[CheckResult]:
            raise RuntimeError("kaboom")

        out = io.StringIO()
        assert run_doctor(Settings(), [crash], out) == 1
        assert "kaboom" in out.getvalue()
