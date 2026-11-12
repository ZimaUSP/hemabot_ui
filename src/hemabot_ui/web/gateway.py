"""Bridges WebSocket clients and the teleoperation service."""

from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from hemabot_ui.motion.backend import MotionBackend
from hemabot_ui.motion.velocity import DriveIntent
from hemabot_ui.teleop.pilot import AcquireOutcome
from hemabot_ui.teleop.service import NotPilotError, TeleopService
from hemabot_ui.web.hub import ClientConnection, ConnectionHub
from hemabot_ui.web.protocol import (
    AcquireMessage,
    ClientMessage,
    DriveMessage,
    ErrorCode,
    ErrorMessage,
    Limits,
    ReleaseMessage,
    RobotState,
    StateMessage,
    StopMessage,
    WelcomeMessage,
    parse_client_message,
)

logger = logging.getLogger(__name__)


class TeleopGateway:
    def __init__(self, teleop: TeleopService, backend: MotionBackend, hub: ConnectionHub) -> None:
        self._teleop = teleop
        self._backend = backend
        self._hub = hub
        self._last_state: StateMessage | None = None

    async def serve(self, websocket: WebSocket) -> None:
        """Run the whole lifecycle of one WebSocket connection."""
        await websocket.accept()
        client = self._hub.register(websocket)
        logger.info("Client %s connected (%d online)", client.id, self._hub.count)
        try:
            await client.send(self._welcome(client.id))
            await self.broadcast_state(force=True)
            await self._receive_loop(websocket, client)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            self._hub.unregister(client)
            self._teleop.disconnect(client.id)
            logger.info("Client %s disconnected (%d online)", client.id, self._hub.count)
            await self.broadcast_state()

    def handle(self, client_id: str, raw: str | bytes) -> ErrorMessage | None:
        """Apply one raw client frame; return the error to reply with, if any."""
        try:
            message = parse_client_message(raw)
        except ValidationError as error:
            return ErrorMessage(code=ErrorCode.INVALID_MESSAGE, message=_summarize(error))
        return self._dispatch(client_id, message)

    def current_state(self) -> StateMessage:
        status = self._backend.status()
        return StateMessage(
            pilot_id=self._teleop.pilot_id,
            clients=self._hub.count,
            robot=RobotState(link=status.link.value, detail=status.detail),
        )

    async def broadcast_state(self, *, force: bool = False) -> None:
        """Send the shared state to every client if it changed (or if ``force``)."""
        state = self.current_state()
        if not force and state == self._last_state:
            return
        self._last_state = state
        await self._hub.broadcast(state)

    async def monitor_robot_status(self, interval_s: float) -> None:
        """Periodically push robot link changes (e.g. bringup started/stopped)."""
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.broadcast_state()
            except Exception:
                logger.exception("Robot status broadcast failed")

    async def _receive_loop(self, websocket: WebSocket, client: ClientConnection) -> None:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                return
            raw = frame.get("text") if frame.get("text") is not None else frame.get("bytes")
            if raw is None:
                continue
            error = self.handle(client.id, raw)
            if error is not None:
                await client.send(error)
            await self.broadcast_state()

    def _dispatch(self, client_id: str, message: ClientMessage) -> ErrorMessage | None:
        if isinstance(message, DriveMessage):
            try:
                self._teleop.drive(client_id, DriveIntent(message.linear, message.angular))
            except NotPilotError:
                return ErrorMessage(code=ErrorCode.NOT_PILOT, message="take control before driving")
        elif isinstance(message, StopMessage):
            self._teleop.emergency_stop(client_id)
        elif isinstance(message, AcquireMessage):
            outcome = self._teleop.acquire(client_id, force=message.force)
            if outcome is AcquireOutcome.BUSY:
                return ErrorMessage(
                    code=ErrorCode.PILOT_BUSY, message="another client is driving the robot"
                )
        elif isinstance(message, ReleaseMessage):
            self._teleop.release(client_id)
        return None

    def _welcome(self, client_id: str) -> WelcomeMessage:
        limits = self._teleop.limits
        return WelcomeMessage(
            client_id=client_id,
            limits=Limits(max_linear=limits.max_linear, max_angular=limits.max_angular),
        )


def _summarize(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    return f"{location}: {first.get('msg')}" if location else str(first.get("msg"))
