"""``hemabot-ui doctor``: diagnose the installation on the robot.

Each check is independent and reports OK / WARN / FAIL with an actionable detail, so
problems on the real robot can be pinpointed without reading the code.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TextIO

from hemabot_ui.config import Settings

EXPECTED_ROS_DISTRO = "humble"
# Nodes started by minihema_launch that the web UI depends on to move the robot.
EXPECTED_BRINGUP_NODES = ("twist_mux", "controller_manager")
ROS_DISCOVERY_TIMEOUT_S = 5.0


class Severity(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: Severity
    detail: str


Check = Callable[[Settings], Iterable[CheckResult]]


def check_python(_: Settings) -> Iterable[CheckResult]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    yield CheckResult("python", Severity.OK, f"Python {version} at {sys.executable}")


def check_ros_environment(_: Settings) -> Iterable[CheckResult]:
    distro = os.environ.get("ROS_DISTRO")
    if not distro:
        yield CheckResult(
            "ros environment",
            Severity.FAIL,
            "ROS_DISTRO is not set; run `source /opt/ros/humble/setup.bash` first",
        )
    elif distro != EXPECTED_ROS_DISTRO:
        yield CheckResult(
            "ros environment",
            Severity.WARN,
            f"ROS_DISTRO={distro}, the robot is expected to run {EXPECTED_ROS_DISTRO}",
        )
    else:
        domain = os.environ.get("ROS_DOMAIN_ID", "0 (default)")
        yield CheckResult("ros environment", Severity.OK, f"ROS {distro}, ROS_DOMAIN_ID={domain}")


def check_ros_graph(settings: Settings) -> Iterable[CheckResult]:
    if settings.backend != "ros2":
        yield CheckResult("ros graph", Severity.WARN, f"skipped: backend is {settings.backend}")
        return
    try:
        import rclpy
    except ImportError as error:
        yield CheckResult(
            "rclpy",
            Severity.FAIL,
            f"cannot import rclpy ({error}); was the virtualenv created with "
            "--system-site-packages and ROS sourced?",
        )
        return
    yield CheckResult("rclpy", Severity.OK, f"imported from {rclpy.__file__}")

    context = rclpy.Context()
    rclpy.init(args=[], context=context)
    node = rclpy.create_node("hemabot_ui_doctor", context=context)
    try:
        subscribers, node_names = _wait_for_discovery(node, settings.cmd_vel_topic)
    finally:
        node.destroy_node()
        rclpy.shutdown(context=context)

    if subscribers > 0:
        yield CheckResult(
            "velocity topic",
            Severity.OK,
            f"{subscribers} subscriber(s) on {settings.cmd_vel_topic}",
        )
    else:
        yield CheckResult(
            "velocity topic",
            Severity.FAIL,
            f"nobody subscribes to {settings.cmd_vel_topic}; the robot will not move. "
            "Check `systemctl status hemabot-ros` and `journalctl -u hemabot-ros`",
        )
    for expected in EXPECTED_BRINGUP_NODES:
        if expected in node_names:
            yield CheckResult(f"node {expected}", Severity.OK, "running")
        else:
            yield CheckResult(f"node {expected}", Severity.WARN, "not found in the ROS graph")


def _wait_for_discovery(node: Any, topic: str) -> tuple[int, set[str]]:
    """Give DDS discovery some time: the graph is empty right after node creation."""
    deadline = time.monotonic() + ROS_DISCOVERY_TIMEOUT_S
    while True:
        subscribers = node.count_subscribers(topic)
        node_names = set(node.get_node_names())
        found_all = all(name in node_names for name in EXPECTED_BRINGUP_NODES)
        if (subscribers > 0 and found_all) or time.monotonic() >= deadline:
            return subscribers, node_names
        time.sleep(0.2)


def check_web_server(settings: Settings) -> Iterable[CheckResult]:
    url = f"http://127.0.0.1:{settings.port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            health = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as error:
        yield CheckResult(
            "web server",
            Severity.WARN,
            f"{url} not reachable ({error}); is hemabot-ui.service running?",
        )
        return
    robot = health.get("robot", {})
    yield CheckResult(
        "web server",
        Severity.OK,
        f"{url} answered: backend={health.get('backend')}, robot link={robot.get('link')}",
    )


DEFAULT_CHECKS: tuple[Check, ...] = (
    check_python,
    check_ros_environment,
    check_ros_graph,
    check_web_server,
)


def run_doctor(
    settings: Settings,
    checks: Iterable[Check] = DEFAULT_CHECKS,
    out: TextIO = sys.stdout,
) -> int:
    """Run all checks, print a report and return the process exit code."""
    failed = False
    for check in checks:
        try:
            results = list(check(settings))
        except Exception as error:
            results = [CheckResult(check.__name__, Severity.FAIL, f"check crashed: {error!r}")]
        for result in results:
            failed = failed or result.severity is Severity.FAIL
            out.write(f"[{result.severity.value:>4}] {result.name}: {result.detail}\n")
    out.write("Some checks failed.\n" if failed else "All required checks passed.\n")
    return 1 if failed else 0
