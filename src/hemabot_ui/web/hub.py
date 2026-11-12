"""Registry of connected WebSocket clients and fan-out of server messages."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from starlette.websockets import WebSocket

from hemabot_ui.web.protocol import ServerMessage

logger = logging.getLogger(__name__)

_SEND_TIMEOUT_S = 2.0


def random_client_id() -> str:
    return uuid.uuid4().hex[:12]


class ClientConnection:
    def __init__(self, client_id: str, websocket: WebSocket) -> None:
        self.id = client_id
        self._websocket = websocket
        # Starlette websockets are not safe for concurrent sends from several tasks.
        self._send_lock = asyncio.Lock()

    async def send(self, message: ServerMessage) -> None:
        payload = message.model_dump_json()
        async with self._send_lock:
            await asyncio.wait_for(self._websocket.send_text(payload), _SEND_TIMEOUT_S)


class ConnectionHub:
    def __init__(self, client_id_factory: Callable[[], str] = random_client_id) -> None:
        self._client_id_factory = client_id_factory
        self._clients: dict[str, ClientConnection] = {}

    @property
    def count(self) -> int:
        return len(self._clients)

    def register(self, websocket: WebSocket) -> ClientConnection:
        client = ClientConnection(self._client_id_factory(), websocket)
        self._clients[client.id] = client
        return client

    def unregister(self, client: ClientConnection) -> None:
        self._clients.pop(client.id, None)

    async def broadcast(self, message: ServerMessage) -> None:
        clients = list(self._clients.values())
        results = await asyncio.gather(
            *(client.send(message) for client in clients), return_exceptions=True
        )
        for client, result in zip(clients, results, strict=True):
            if isinstance(result, Exception):
                # The client's own receive loop notices the broken socket and cleans up.
                logger.debug("Broadcast to client %s failed: %r", client.id, result)
