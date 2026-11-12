"""FastAPI application: HTTP API, teleoperation WebSocket and the static web client."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from hemabot_ui import __version__
from hemabot_ui.motion.backend import MotionBackend
from hemabot_ui.teleop.service import TeleopService
from hemabot_ui.web.gateway import TeleopGateway
from hemabot_ui.web.hub import ConnectionHub

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers must revalidate before reuse.

    Without an explicit Cache-Control, browsers cache heuristically and phones keep
    running an old web client after the robot is updated. Revalidation is a cheap
    conditional request (ETag) on the local network.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    *,
    backend: MotionBackend,
    teleop: TeleopService,
    status_interval_s: float,
    hub: ConnectionHub | None = None,
) -> FastAPI:
    gateway = TeleopGateway(teleop, backend, hub or ConnectionHub())

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        backend.start()
        tasks = [
            asyncio.create_task(teleop.run(), name="teleop-watchdog"),
            asyncio.create_task(
                gateway.monitor_robot_status(status_interval_s), name="robot-status"
            ),
        ]
        logger.info("Hemabot UI %s started with the '%s' backend", __version__, backend.name)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            teleop.halt()
            backend.shutdown()
            logger.info("Hemabot UI stopped")

    app = FastAPI(title="Hemabot UI", version=__version__, lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        state = gateway.current_state()
        return {
            "status": "ok",
            "version": __version__,
            "backend": backend.name,
            "robot": state.robot.model_dump(),
            "pilot_active": state.pilot_id is not None,
            "clients": state.clients,
        }

    @app.websocket("/ws/teleop")
    async def teleop_socket(websocket: WebSocket) -> None:
        await gateway.serve(websocket)

    # Mounted last so it does not shadow the API routes above.
    app.mount("/", RevalidatingStaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
