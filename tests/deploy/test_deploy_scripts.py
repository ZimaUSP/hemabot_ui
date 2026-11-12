"""Black-box tests of the shell scripts that install and start the services.

System commands (apt-get, systemctl, runuser, ...) are replaced by stubs placed first
on PATH; each stub logs its invocation so the tests can assert what would have run.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SETUP = REPO / "scripts" / "setup.sh"
UNINSTALL = REPO / "scripts" / "uninstall.sh"
ROS_LAUNCH = REPO / "deploy" / "bin" / "hemabot-ros-launch"
UI_SERVE = REPO / "deploy" / "bin" / "hemabot-ui-serve"
SHELL_SCRIPTS = [
    SETUP,
    UNINSTALL,
    ROS_LAUNCH,
    UI_SERVE,
    REPO / "deploy" / "bin" / "ros-env.sh",
]


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@dataclass
class Sandbox:
    root: Path
    bin: Path
    log: Path
    systemd_dir: Path
    config_dir: Path
    ros_root: Path
    workspace: Path

    def env(self, **extra: str) -> dict[str, str]:
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.root),
            "STUB_LOG": str(self.log),
            "HEMABOT_SYSTEMD_DIR": str(self.systemd_dir),
            "HEMABOT_CONFIG_DIR": str(self.config_dir),
            "HEMABOT_ROS_ROOT": str(self.ros_root),
        }
        env.update(extra)
        return env

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def run(self, script: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script), *args],
            env=self.env(**env),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


STUB = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    box = Sandbox(
        root=tmp_path,
        bin=tmp_path / "bin",
        log=tmp_path / "calls.log",
        systemd_dir=tmp_path / "systemd",
        config_dir=tmp_path / "etc-hemabot",
        ros_root=tmp_path / "opt-ros",
        workspace=tmp_path / "home" / "hemabot" / "hemabot_ros2",
    )
    for command in ("apt-get", "usermod", "runuser", "systemctl"):
        write_executable(box.bin / command, STUB)
    write_executable(box.bin / "id", '#!/usr/bin/env bash\n[[ "$1" == "-u" ]] && echo 0\n')
    write_executable(
        box.bin / "getent",
        f"""#!/usr/bin/env bash
case "$1 $2" in
  "passwd hemabot") echo "hemabot:x:1000:1000::{tmp_path}/home/hemabot:/bin/bash" ;;
  "group dialout"|"group i2c"|"group input") echo "$2:x:20:" ;;
  *) exit 2 ;;
esac
""",
    )
    write_executable(
        box.bin / "ufw",
        STUB + '[[ "$1" == "status" ]] && echo "Status: active"\nexit 0\n',
    )
    write_executable(
        box.bin / "hostname",
        '#!/usr/bin/env bash\n[[ "$1" == "-I" ]] && echo "192.168.1.155 fe80::1" || echo hemabot\n',
    )
    (box.ros_root / "humble").mkdir(parents=True)
    (box.ros_root / "humble" / "setup.bash").write_text("export ROS_DISTRO=humble\n")
    (box.workspace / "install").mkdir(parents=True)
    (box.workspace / "install" / "setup.bash").write_text("export HEMABOT_WS_SOURCED=1\n")
    return box


# --- static checks ----------------------------------------------------------------------


def test_shell_scripts_pass_shellcheck() -> None:
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck not installed (uv sync installs shellcheck-py)")
    result = subprocess.run(
        [shellcheck, "-x", *map(str, SHELL_SCRIPTS)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("script", [SETUP, UNINSTALL, ROS_LAUNCH, UI_SERVE], ids=lambda p: p.name)
def test_scripts_are_executable(script: Path) -> None:
    assert os.access(script, os.X_OK)


def test_systemd_units_pass_systemd_analyze(tmp_path: Path) -> None:
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        pytest.skip("systemd-analyze not available")
    env_file = tmp_path / "hemabot.env"
    env_file.touch()
    units = []
    for template in sorted((REPO / "deploy" / "systemd").glob("*.service.in")):
        unit = tmp_path / template.name.removesuffix(".in")
        unit.write_text(
            template.read_text()
            .replace("@APP_DIR@", str(REPO))
            .replace("@SERVICE_USER@", os.environ.get("USER", "root"))
            .replace("@ENV_FILE@", str(env_file))
        )
        units.append(str(unit))
    result = subprocess.run(
        [analyzer, "verify", "--man=no", *units],
        capture_output=True,
        text=True,
        check=False,
    )
    # systemd only warns (exit code 0) about unknown keys or bad values, so any output fails.
    assert result.returncode == 0
    assert result.stdout + result.stderr == ""


# --- setup.sh -----------------------------------------------------------------------------


def test_setup_installs_everything(sandbox: Sandbox) -> None:
    result = sandbox.run(SETUP, "--user", "hemabot")
    assert result.returncode == 0, result.stderr

    calls = sandbox.calls()
    assert any(c.startswith("apt-get install") and "python3-venv" in c for c in calls)
    assert "usermod -a -G dialout hemabot" in calls
    assert "usermod -a -G i2c hemabot" in calls
    assert not any("-G gpio" in c for c in calls), "groups missing on the system are skipped"
    venv = REPO / ".venv"
    assert f"runuser -u hemabot -- python3 -m venv --system-site-packages {venv}" in calls
    assert (
        f"runuser -u hemabot -- {venv}/bin/python -m pip install --quiet --editable {REPO}" in calls
    )
    assert "systemctl daemon-reload" in calls
    assert "systemctl enable hemabot-ros.service hemabot-ui.service" in calls
    assert "systemctl restart hemabot-ros.service hemabot-ui.service" in calls
    assert "ufw allow 80/tcp" in calls
    assert calls.index("systemctl daemon-reload") < calls.index(
        "systemctl restart hemabot-ros.service hemabot-ui.service"
    )
    assert "http://hemabot.local" in result.stdout
    assert "http://192.168.1.155" in result.stdout
    assert "fe80" not in result.stdout


def test_setup_renders_units_without_placeholders(sandbox: Sandbox) -> None:
    assert sandbox.run(SETUP, "--user", "hemabot").returncode == 0
    for name in ("hemabot-ros.service", "hemabot-ui.service"):
        unit = (sandbox.systemd_dir / name).read_text()
        assert "@" not in unit, f"unrendered placeholder in {name}"
        assert "User=hemabot" in unit
        assert f"EnvironmentFile={sandbox.config_dir}/hemabot.env" in unit
    ui_unit = (sandbox.systemd_dir / "hemabot-ui.service").read_text()
    assert f"ExecStart={REPO}/deploy/bin/hemabot-ui-serve" in ui_unit
    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in ui_unit
    ros_unit = (sandbox.systemd_dir / "hemabot-ros.service").read_text()
    assert f"ExecStart={REPO}/deploy/bin/hemabot-ros-launch" in ros_unit
    assert "KillSignal=SIGINT" in ros_unit


def test_setup_writes_configuration(sandbox: Sandbox) -> None:
    assert sandbox.run(SETUP, "--user", "hemabot", "--port", "8080").returncode == 0
    config = (sandbox.config_dir / "hemabot.env").read_text()
    assert "@" not in config
    assert "HEMABOT_UI_PORT=8080" in config
    assert f"HEMABOT_ROS_WS={sandbox.workspace}" in config  # default: ~user/hemabot_ros2
    assert "HEMABOT_ROS_SETUP=/opt/ros/humble/setup.bash" in config
    assert "HEMABOT_UI_CMD_VEL_TOPIC=/cmd_vel_joy" in config


def test_configuration_is_valid_for_the_app(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hemabot_ui.config import Settings

    assert sandbox.run(SETUP, "--user", "hemabot").returncode == 0
    for line in (sandbox.config_dir / "hemabot.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            monkeypatch.setenv(key, value)
    settings = Settings()
    assert settings.port == 80
    assert settings.backend == "ros2"


def test_rerunning_setup_keeps_user_configuration(sandbox: Sandbox) -> None:
    assert sandbox.run(SETUP, "--user", "hemabot").returncode == 0
    config = sandbox.config_dir / "hemabot.env"
    config.write_text(config.read_text().replace("HEMABOT_UI_PORT=80", "HEMABOT_UI_PORT=8081"))
    result = sandbox.run(SETUP, "--user", "hemabot")
    assert result.returncode == 0
    assert "HEMABOT_UI_PORT=8081" in config.read_text()
    assert "Keeping existing configuration" in result.stdout


def test_setup_options(sandbox: Sandbox) -> None:
    custom_ws = sandbox.root / "elsewhere"
    result = sandbox.run(
        SETUP, "--user", "hemabot", "--ros-ws", str(custom_ws), "--skip-apt", "--no-start"
    )
    assert result.returncode == 0, result.stderr
    calls = sandbox.calls()
    assert not any(c.startswith("apt-get") for c in calls)
    assert not any(c.startswith("systemctl restart") for c in calls)
    assert "systemctl enable hemabot-ros.service hemabot-ui.service" in calls
    assert f"HEMABOT_ROS_WS={custom_ws}" in (sandbox.config_dir / "hemabot.env").read_text()
    assert "workspace not built" in result.stderr


def test_setup_uses_sudo_user_by_default(sandbox: Sandbox) -> None:
    result = sandbox.run(SETUP, "--skip-apt", SUDO_USER="hemabot")
    assert result.returncode == 0, result.stderr
    assert "User=hemabot" in (sandbox.systemd_dir / "hemabot-ui.service").read_text()


@pytest.mark.parametrize(
    ("args", "env", "message"),
    [
        (["--user", "hemabot", "--port", "99999"], {}, "invalid port"),
        (["--user", "hemabot", "--port", "abc"], {}, "invalid port"),
        (["--user", "ghost"], {}, "does not exist"),
        (["--user", "root"], {}, "must not run as root"),
        ([], {}, "pass --user"),
        (["--user", "hemabot", "--ros-distro", "iron"], {}, "ROS 2 iron not found"),
        (["--bogus"], {}, "unknown option"),
    ],
)
def test_setup_rejects_bad_input(
    sandbox: Sandbox, args: list[str], env: dict[str, str], message: str
) -> None:
    result = sandbox.run(SETUP, *args, **env)
    assert result.returncode != 0
    assert message in result.stderr
    assert not (sandbox.systemd_dir / "hemabot-ui.service").exists()


def test_setup_requires_root(sandbox: Sandbox) -> None:
    write_executable(sandbox.bin / "id", "#!/usr/bin/env bash\necho 1000\n")
    result = sandbox.run(SETUP, "--user", "hemabot")
    assert result.returncode != 0
    assert "run as root" in result.stderr
    assert sandbox.calls() == []


def test_setup_help(sandbox: Sandbox) -> None:
    result = sandbox.run(SETUP, "--help")
    assert result.returncode == 0
    assert "--ros-ws" in result.stdout


# --- uninstall.sh -------------------------------------------------------------------------


def test_uninstall_removes_services_and_keeps_config(sandbox: Sandbox) -> None:
    assert sandbox.run(SETUP, "--user", "hemabot").returncode == 0
    result = sandbox.run(UNINSTALL)
    assert result.returncode == 0, result.stderr
    assert not (sandbox.systemd_dir / "hemabot-ui.service").exists()
    assert not (sandbox.systemd_dir / "hemabot-ros.service").exists()
    assert (sandbox.config_dir / "hemabot.env").exists()
    assert "systemctl disable --now hemabot-ui.service" in sandbox.calls()


def test_uninstall_purge_removes_config(sandbox: Sandbox) -> None:
    assert sandbox.run(SETUP, "--user", "hemabot").returncode == 0
    assert sandbox.run(UNINSTALL, "--purge").returncode == 0
    assert not sandbox.config_dir.exists()


# --- service start scripts -------------------------------------------------------------


@pytest.fixture
def fake_ros(sandbox: Sandbox) -> Sandbox:
    """A ROS installation whose setup files behave like the real ones: they reference
    unset variables and run commands that fail, which breaks naive `set -eu` scripts."""
    ros_bin = sandbox.root / "ros-bin"
    write_executable(
        ros_bin / "ros2",
        '#!/usr/bin/env bash\necho "ros2 $* | cwd=$PWD | ws=${HEMABOT_WS_SOURCED:-0}"\n',
    )
    (sandbox.ros_root / "humble" / "setup.bash").write_text(
        f'echo "$AMENT_TRACE_SETUP_FILES" >/dev/null\nfalse\nexport PATH="{ros_bin}:$PATH"\n'
        "export ROS_DISTRO=humble\n"
    )
    (sandbox.workspace / "install" / "setup.bash").write_text(
        'echo "$COLCON_TRACE" >/dev/null\nexport HEMABOT_WS_SOURCED=1\n'
    )
    return sandbox


def ros_env(box: Sandbox, **extra: str) -> dict[str, str]:
    return {
        "HEMABOT_ROS_SETUP": str(box.ros_root / "humble" / "setup.bash"),
        "HEMABOT_ROS_WS": str(box.workspace),
        **extra,
    }


def test_ros_launch_runs_bringup_from_workspace(fake_ros: Sandbox) -> None:
    result = fake_ros.run(ROS_LAUNCH, **ros_env(fake_ros))
    assert result.returncode == 0, result.stderr
    assert f"ros2 launch minihema_launch minihema_launch.py | cwd={fake_ros.workspace} | ws=1" in (
        result.stdout
    )


def test_ros_launch_passes_configured_package_and_arguments(fake_ros: Sandbox) -> None:
    env = ros_env(
        fake_ros,
        HEMABOT_ROS_LAUNCH_PACKAGE="d_hospital_slam",
        HEMABOT_ROS_LAUNCH_FILE="online_async_launch.py",
        HEMABOT_ROS_LAUNCH_ARGS="use_sim_time:=false  foo:=bar",
    )
    result = fake_ros.run(ROS_LAUNCH, **env)
    assert result.returncode == 0, result.stderr
    assert "ros2 launch d_hospital_slam online_async_launch.py use_sim_time:=false foo:=bar |" in (
        result.stdout
    )


def test_ros_launch_fails_without_built_workspace(fake_ros: Sandbox) -> None:
    result = fake_ros.run(ROS_LAUNCH, **ros_env(fake_ros, HEMABOT_ROS_WS="/nonexistent"))
    assert result.returncode != 0
    assert "workspace setup not found" in result.stderr


def test_ros_launch_fails_without_ros(fake_ros: Sandbox) -> None:
    result = fake_ros.run(ROS_LAUNCH, **ros_env(fake_ros, HEMABOT_ROS_SETUP="/nope/setup.bash"))
    assert result.returncode != 0
    assert "ROS 2 setup file not found" in result.stderr


@pytest.fixture
def fake_venv(sandbox: Sandbox) -> Path:
    venv = sandbox.root / "venv"
    write_executable(
        venv / "bin" / "python",
        "#!/usr/bin/env bash\n"
        'echo "python $* | distro=${ROS_DISTRO:-none} | ws=${HEMABOT_WS_SOURCED:-0}"\n',
    )
    return venv


def test_ui_serve_sources_ros_and_runs_app(fake_ros: Sandbox, fake_venv: Path) -> None:
    result = fake_ros.run(UI_SERVE, **ros_env(fake_ros, HEMABOT_UI_VENV=str(fake_venv)))
    assert result.returncode == 0, result.stderr
    assert "python -m hemabot_ui serve | distro=humble | ws=1" in result.stdout


def test_ui_serve_tolerates_missing_workspace(fake_ros: Sandbox, fake_venv: Path) -> None:
    env = ros_env(fake_ros, HEMABOT_UI_VENV=str(fake_venv), HEMABOT_ROS_WS="/nonexistent")
    result = fake_ros.run(UI_SERVE, **env)
    assert result.returncode == 0, result.stderr
    assert "distro=humble | ws=0" in result.stdout


def test_ui_serve_simulated_backend_does_not_need_ros(sandbox: Sandbox, fake_venv: Path) -> None:
    result = sandbox.run(
        UI_SERVE,
        HEMABOT_UI_VENV=str(fake_venv),
        HEMABOT_UI_BACKEND="simulated",
        HEMABOT_ROS_SETUP="/nope/setup.bash",
    )
    assert result.returncode == 0, result.stderr
    assert "distro=none" in result.stdout


def test_ui_serve_reports_missing_virtualenv(fake_ros: Sandbox) -> None:
    result = fake_ros.run(UI_SERVE, **ros_env(fake_ros, HEMABOT_UI_VENV="/nope"))
    assert result.returncode != 0
    assert "run scripts/setup.sh" in result.stderr
