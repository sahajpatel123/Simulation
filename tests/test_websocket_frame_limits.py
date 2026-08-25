"""Regression tests for WebSocket pre-auth resource bounds.

The endpoint accepted an anonymous socket and waited up to 20s for an
auth frame read via ``receive_text()`` — unbounded buffering on that
first read meant one anonymous connection could force a huge allocation,
and every idle socket held a TCP slot plus an asyncio task for the full
window. These tests pin: the tightened pre-auth window, the 64KB cap
enforced BEFORE handlers see payload (oversized/binary first frames are
closed without parsing), and post-auth tolerance (an oversized mid-stream
frame draws an error message instead of a disconnect).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

_STUB_MODULES = ("app.core.websocket",)

for _mod in _STUB_MODULES:
    if _mod not in sys.modules:
        stub = MagicMock()
        stub.ws_manager = MagicMock()
        sys.modules[_mod] = stub

_WS_PATH = Path(__file__).resolve().parents[1] / "backend" / "app" / "api" / "v1" / "websocket.py"


def _load_ws_module():
    spec = importlib.util.spec_from_file_location("app_api_v1_websocket_under_test", _WS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ws = _load_ws_module()


@contextmanager
def _wired_backend(user):
    """Patch collaborators so the full handler can run against fakes."""
    harness = types.SimpleNamespace(
        manager=types.SimpleNamespace(connect=AsyncMock(), disconnect=MagicMock()),
        bridge=types.SimpleNamespace(ensure_running=AsyncMock()),
        auth=AsyncMock(return_value=user),
        owns=AsyncMock(return_value=True),
    )
    with (
        patch.object(_ws, "ws_manager", harness.manager),
        patch.object(_ws, "progress_bridge", harness.bridge),
        patch.object(_ws, "_get_user_from_token", harness.auth),
        patch.object(_ws, "_verify_ownership", harness.owns),
        # Origin allowlisting has its own suite (CSWSH tests); flows here
        # just need it open.
        patch.object(_ws, "_origin_allowed", lambda origin: True),
    ):
        yield harness


class _FakeWebSocket:
    def __init__(self, messages):
        self.headers = {"origin": "http://test-frontend"}
        self.accept = AsyncMock()
        self.close = AsyncMock()
        self.send_text = AsyncMock()
        self._messages = list(messages)
        self.receive = AsyncMock(side_effect=self._next)

    async def _next(self):
        if not self._messages:
            raise WebSocketDisconnect(code=1000)
        item = self._messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _user():
    return types.SimpleNamespace(id=42)


async def _run(socket, simulation_id: int = 12):
    return await _ws.websocket_simulation_progress(socket, simulation_id)


def test_pre_auth_window_is_short_and_bounded() -> None:
    assert 0 < _ws.PRE_AUTH_TIMEOUT_SECONDS <= 10
    assert 0 < _ws.MAX_FRAME_CHARS <= 65536


@pytest.mark.asyncio
async def test_oversized_first_frame_closed_without_parsing() -> None:
    user = _user()
    big_text = "x" * (_ws.MAX_FRAME_CHARS + 1)
    socket = _FakeWebSocket([{"type": "websocket.receive", "text": big_text}])
    with _wired_backend(user) as harness:
        await _run(socket)

    socket.close.assert_awaited_once_with(code=4001)
    # The auth path was never reached — payload never parsed.
    harness.auth.assert_not_awaited()
    harness.manager.connect.assert_not_called()


@pytest.mark.asyncio
async def test_binary_first_frame_closed_without_parsing() -> None:
    user = _user()
    socket = _FakeWebSocket([{"type": "websocket.receive", "bytes": b"\x00\xff"}])
    with _wired_backend(user) as harness:
        await _run(socket)

    socket.close.assert_awaited_once_with(code=4001)
    harness.auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_auth_then_ping_flow_still_works() -> None:
    user = _user()
    auth_frame = json.dumps({"type": "auth", "access_token": "tok"})
    socket = _FakeWebSocket(
        [
            {"type": "websocket.receive", "text": auth_frame},
            {"type": "websocket.receive", "text": "ping"},
            WebSocketDisconnect(code=1000),
        ]
    )
    with _wired_backend(user) as harness:
        await _run(socket)

    harness.auth.assert_awaited_once_with("tok")
    harness.owns.assert_awaited_once_with(12, 42)
    socket.accept.assert_awaited_once()
    socket.send_text.assert_any_await('{"type":"pong"}')
    harness.manager.disconnect.assert_called_once_with(12)


@pytest.mark.asyncio
async def test_post_auth_oversized_frame_draws_error_not_disconnect() -> None:
    user = _user()
    auth_frame = json.dumps({"type": "auth", "access_token": "tok"})
    big_text = "y" * (_ws.MAX_FRAME_CHARS * 4)
    socket = _FakeWebSocket(
        [
            {"type": "websocket.receive", "text": auth_frame},
            {"type": "websocket.receive", "text": big_text},
            {"type": "websocket.receive", "text": "ping"},
            WebSocketDisconnect(code=1000),
        ]
    )
    with _wired_backend(user):
        await _run(socket)

    sent = [call.args[0] for call in socket.send_text.await_args_list]
    assert any("Frame too large" in s for s in sent), f"no oversize error sent: {sent}"
    assert '{"type":"pong"}' in sent  # connection survived the oversized frame
