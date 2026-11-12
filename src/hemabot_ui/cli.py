"""Command line entry point: ``hemabot-ui [serve|doctor]``."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from hemabot_ui.config import Settings

# Frames are tiny JSON objects; refuse anything big to protect the Raspberry Pi.
_WS_MAX_FRAME_BYTES = 64 * 1024


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hemabot-ui",
        description="Hemabot web interface. Settings come from HEMABOT_UI_* environment "
        "variables; command line options override them.",
    )
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="run the web server (default)")
    serve.add_argument("--host", help="interface to bind (HEMABOT_UI_HOST)")
    serve.add_argument("--port", type=int, help="TCP port (HEMABOT_UI_PORT)")
    serve.add_argument(
        "--backend",
        choices=["ros2", "simulated"],
        help="'simulated' runs without ROS, for development (HEMABOT_UI_BACKEND)",
    )

    commands.add_parser("doctor", help="diagnose the installation on the robot")
    return parser


def _load_settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {
        name: getattr(args, name)
        for name in ("host", "port", "backend")
        if getattr(args, name, None) is not None
    }
    return Settings(**overrides)


def _serve(settings: Settings) -> int:
    import uvicorn

    from hemabot_ui.bootstrap import build_app

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        build_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        ws_max_size=_WS_MAX_FRAME_BYTES,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _load_settings(args)
    except ValidationError as error:
        parser.error(f"invalid configuration:\n{error}")

    if args.command == "doctor":
        from hemabot_ui.doctor import run_doctor

        return run_doctor(settings)
    return _serve(settings)
