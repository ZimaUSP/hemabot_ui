"""Runs the real CLI (`python -m hemabot_ui serve`) under uvicorn and talks to it over a
real TCP WebSocket, exactly as a phone on the network would."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
import websockets


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def server() -> Iterator[tuple[subprocess.Popen[str], int]]:
    port = free_port()
    env = {
        **os.environ,
        "HEMABOT_UI_BACKEND": "simulated",
        "HEMABOT_UI_HOST": "127.0.0.1",
        "HEMABOT_UI_PORT": str(port),
        "HEMABOT_UI_LOG_LEVEL": "info",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "hemabot_ui", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 15
    while True:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            break
        except OSError:
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                pytest.fail(f"server did not start:\n{process.communicate()[0]}")
            time.sleep(0.1)
    yield process, port
    if process.poll() is None:
        process.kill()
        process.wait()


async def receive_until(ws: Any, message_type: str, **fields: Any) -> dict[str, Any]:
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if message["type"] == message_type and all(message.get(k) == v for k, v in fields.items()):
            return message


def test_page_and_api_are_served(server: tuple[subprocess.Popen[str], int]) -> None:
    _, port = server
    page = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
    assert "<title>Hemabot</title>" in page
    health = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5))
    assert health["backend"] == "simulated"


async def test_drive_over_real_websocket(server: tuple[subprocess.Popen[str], int]) -> None:
    _, port = server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws/teleop") as ws:
        welcome = await receive_until(ws, "welcome")
        me = welcome["client_id"]
        await ws.send(json.dumps({"type": "acquire"}))
        await receive_until(ws, "state", pilot_id=me)
        for _ in range(5):
            await ws.send(json.dumps({"type": "drive", "linear": 0.5, "angular": 0.0}))
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "drive", "linear": 2, "angular": 0.0}))
        error = await receive_until(ws, "error")
        assert error["code"] == "invalid_message"


async def test_oversized_frames_are_rejected(server: tuple[subprocess.Popen[str], int]) -> None:
    process, port = server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws/teleop") as ws:
        await receive_until(ws, "welcome")
        await ws.send("x" * (128 * 1024))
        with pytest.raises(websockets.ConnectionClosed):
            for _ in range(10):
                await asyncio.wait_for(ws.recv(), timeout=5)
    assert process.poll() is None, "server must survive abusive clients"


def test_sigterm_stops_server_cleanly(server: tuple[subprocess.Popen[str], int]) -> None:
    process, _ = server
    process.send_signal(signal.SIGTERM)  # what `systemctl stop` sends
    output, _ = process.communicate(timeout=10)
    # Recent uvicorn versions re-raise the signal after a graceful shutdown; systemd
    # counts termination by SIGTERM as a clean exit.
    assert process.returncode in (0, -signal.SIGTERM), output
    assert "Hemabot UI stopped" in output
    assert "Traceback" not in output
