"""Regression tests for WebSocket Origin validation (CSWSH defence).

The websocket endpoint previously accepted any handshake regardless of
the ``Origin`` header, which left it open to Cross-Site WebSocket
Hijacking: a malicious page running in the user's browser could open a
socket to ``wss://api.thecee.ai/ws/simulation/{id}`` and (combined with
any XSS or token-exfiltration) ride the user's auth context.

These tests pin the Origin allowlist contract so the defence cannot
silently regress.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Stub out the optional heavy imports that websocket.py's module body
# triggers when imported normally — we only need the helpers and the
# handler signature, not the runtime routing tree.
_STUB_MODULES = ("app.core.websocket",)

for _mod in _STUB_MODULES:
    if _mod not in sys.modules:
        stub = MagicMock()
        stub.ws_manager = MagicMock()
        sys.modules[_mod] = stub

_WS_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "v1"
    / "websocket.py"
)


def _load_ws_module():
    spec = importlib.util.spec_from_file_location(
        "app_api_v1_websocket_under_test", _WS_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ws = _load_ws_module()


def _production_settings():
    from app.core.config import Settings

    return Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
        ENVIRONMENT="production",
        FRONTEND_URL="https://app.thecee.ai",
        SECRET_KEY="production-test-secret-with-32-plus-chars",
    )


def _development_settings():
    from app.core.config import Settings

    return Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
        ENVIRONMENT="development",
        FRONTEND_URL="https://app.thecee.ai",
    )


class TestOriginAllowed:
    """Patch the ``settings`` symbol in the websocket module itself,
    since the helper binds to ``settings`` at import time."""

    def test_dev_allowlist_includes_localhost(self) -> None:
        with patch.object(_ws, "settings", _development_settings()):
            assert _ws._origin_allowed("http://localhost:3000") is True
            assert _ws._origin_allowed("http://localhost:3001") is True
            assert _ws._origin_allowed("https://app.thecee.ai") is True

    def test_production_rejects_unknown_origin(self) -> None:
        with patch.object(_ws, "settings", _production_settings()):
            assert _ws._origin_allowed("https://app.thecee.ai") is True
            assert _ws._origin_allowed("http://localhost:3000") is False
            assert _ws._origin_allowed("https://evil.example") is False
            assert _ws._origin_allowed("null") is False

    def test_production_rejects_missing_origin(self) -> None:
        with patch.object(_ws, "settings", _production_settings()):
            assert _ws._origin_allowed(None) is False
            assert _ws._origin_allowed("") is False

    def test_dev_tolerates_missing_origin(self) -> None:
        with patch.object(_ws, "settings", _development_settings()):
            assert _ws._origin_allowed(None) is True
            assert _ws._origin_allowed("") is True


class TestHandlerInvokesOriginCheckFirst:
    """The Origin check must run BEFORE ``websocket.accept()`` so a
    hostile origin never establishes a protocol upgrade."""

    def test_handler_closes_before_accept_on_bad_origin(self) -> None:
        import asyncio

        with patch.object(_ws, "settings", _production_settings()):
            ws = MagicMock()
            ws.headers = {"origin": "https://evil.example"}
            ws.accept = MagicMock()
            # close() is async on a real WebSocket — make the mock
            # return a coroutine so ``await`` works.
            ws.close = AsyncMock()
            ws.receive_text = AsyncMock()

            asyncio.run(_ws.websocket_simulation_progress(ws, simulation_id=1))

            ws.close.assert_awaited_once()
            # close must have been called with code 4003 (forbidden).
            close_args = ws.close.await_args
            assert close_args is not None
            assert close_args.kwargs.get("code") == 4003 or (
                len(close_args.args) > 0 and close_args.args[0] == 4003
            )
            # accept must NEVER have been called for a hostile origin.
            ws.accept.assert_not_called()
