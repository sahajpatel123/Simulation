"""Production gating of the /system/* observability digests.

The ten ``/system`` endpoints compose an operations dashboard: per-route
traffic and error statistics, LLM provider health, broker queue depths,
pool utilization, and live simulation IDs. Until 2026-08-25 they answered
anonymous callers everywhere. ``require_admin_in_production`` now keys
them off the effective environment like every other production guard —
open in development tooling, admin-only on a public deploy (401 for
anonymous callers, ``require_admin()``'s 403 otherwise).

The AST pin runs everywhere (no app import needed). The behavioural tests
import the router module, which pulls the auth stack — they skip on
minimal venvs without PyJWT and run fully in CI's hash-locked install.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

_GUARD = "require_admin_in_production"
_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "backend" / "app" / "api" / "v1" / "system_health.py"
)


def _system_health():
    """Import the router module, skipping cleanly when jwt is absent."""
    pytest.importorskip("jwt", reason="auth stack required to import the router")
    from app.api.v1 import system_health

    return system_health


def _settings():
    from app.core.config import settings

    return settings


def test_development_allows_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sh = _system_health()
    monkeypatch.setattr(_settings(), "ENVIRONMENT", "development")
    assert sh.require_admin_in_production(current_user=None) is None


def test_production_rejects_anonymous_with_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fastapi_httpexception = pytest.importorskip("fastapi").HTTPException
    sh = _system_health()
    monkeypatch.setattr(_settings(), "ENVIRONMENT", "production")
    with pytest.raises(fastapi_httpexception) as excinfo:
        sh.require_admin_in_production(current_user=None)
    assert excinfo.value.status_code == 401
    assert excinfo.value.headers == {"WWW-Authenticate": "Bearer"}


def test_production_rejects_non_admin_with_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fastapi_httpexception = pytest.importorskip("fastapi").HTTPException
    sh = _system_health()
    monkeypatch.setattr(_settings(), "ENVIRONMENT", "production")
    non_admin = SimpleNamespace(is_admin=False, email="founder@example.com")
    with pytest.raises(fastapi_httpexception) as excinfo:
        sh.require_admin_in_production(current_user=non_admin)
    assert excinfo.value.status_code == 403


def test_production_admits_db_flag_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sh = _system_health()
    monkeypatch.setattr(_settings(), "ENVIRONMENT", "production")
    admin = SimpleNamespace(is_admin=True, email="anyone@example.com")
    assert sh.require_admin_in_production(current_user=admin) is None


def test_production_admits_admin_email_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sh = _system_health()
    cfg = _settings()
    monkeypatch.setattr(cfg, "ENVIRONMENT", "production")
    monkeypatch.setattr(cfg, "ADMIN_EMAILS", "boss@example.com")
    allowlisted = SimpleNamespace(is_admin=False, email="BOSS@example.com")
    assert sh.require_admin_in_production(current_user=allowlisted) is None


def test_every_system_route_carries_the_guard() -> None:
    """AST pin: any future @router.get under /system must declare the guard.

    A new diagnostic digest added without the dependency would silently
    reintroduce anonymous exposure on production deploys.
    """
    tree = ast.parse(_MODULE_PATH.read_text())
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "get"
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "router"
            ):
                routes.append((node.name, dec))
    assert len(routes) >= 10, f"expected the ten /system routes, saw {routes}"
    ungated = [name for name, dec in routes if _GUARD not in ast.unparse(dec)]
    assert ungated == [], f"/system routes missing {_GUARD}: {ungated}"
