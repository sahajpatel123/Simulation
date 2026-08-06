"""Regression tests for OpenAPI surface gating in production.

The /docs, /redoc, and /openapi.json endpoints expose the full route
map and request/response schemas. In production this is information
leakage — attackers can enumerate endpoints and craft payloads
without probing. The app constructor now sets these URLs to None
when ENVIRONMENT == "production", so FastAPI does not register the
routes at all.

These tests pin that gating so the routes cannot silently re-appear.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch


def _reload_app_with_env(env: str, monkeypatch=None):
    """Reload the FastAPI app with ENVIRONMENT set to ``env``.

    We patch ``app.core.config.settings`` so the app reads the desired
    environment value without polluting the real process state.
    """
    if "razorpay" not in sys.modules:
        # Stub razorpay so the package __init__ chain doesn't fail in
        # local environments where the real SDK can't import pkg_resources.
        razorpay_stub = type(sys)("razorpay")
        razorpay_stub.Client = type("Client", (), {})
        sys.modules["razorpay"] = razorpay_stub

    from app.core import config as cfg

    new_settings = cfg.Settings(
        DATABASE_URL="postgresql://x",
        ENVIRONMENT=env,
        FRONTEND_URL="https://app.thecee.example",
        SECRET_KEY="production-test-secret-with-32-plus-chars",
    )
    with patch.object(cfg, "settings", new_settings):
        # Force reimport of main so the FastAPI() constructor re-evaluates
        # the conditional URLs against the patched settings.
        import app.main as main_module

        importlib.reload(main_module)
        return main_module.app


class TestProductionHidesOpenAPI:
    def test_docs_url_is_none_in_production(self) -> None:
        app = _reload_app_with_env("production")
        assert app.docs_url is None, (
            "FastAPI auto-registers GET /docs when docs_url is set; "
            "in production this leaks the full API surface."
        )

    def test_redoc_url_is_none_in_production(self) -> None:
        app = _reload_app_with_env("production")
        assert app.redoc_url is None

    def test_openapi_url_is_none_in_production(self) -> None:
        app = _reload_app_with_env("production")
        assert app.openapi_url is None

    def test_docs_route_not_registered_in_production(self) -> None:
        """No GET /docs route should exist on the production app."""
        app = _reload_app_with_env("production")

        def _collect_paths(routes):
            out = set()
            for r in routes:
                path = getattr(r, "path", None)
                if path:
                    out.add(path)
                # Recurse into mounted sub-routers (FastAPI's APIRouter).
                inner = getattr(r, "routes", None)
                if inner:
                    out.update(_collect_paths(inner))
            return out

        paths = _collect_paths(app.routes)
        assert "/docs" not in paths, (
            "Production app still exposes /docs; openapi/docs gating is broken."
        )
        assert "/redoc" not in paths
        assert "/openapi.json" not in paths


class TestDevelopmentKeepsOpenAPI:
    def test_docs_url_set_in_development(self) -> None:
        app = _reload_app_with_env("development")
        assert app.docs_url == "/docs"

    def test_redoc_url_set_in_development(self) -> None:
        app = _reload_app_with_env("development")
        assert app.redoc_url == "/redoc"

    def test_openapi_url_set_in_development(self) -> None:
        app = _reload_app_with_env("development")
        assert app.openapi_url == "/openapi.json"
