"""Platform-inferred production environment guards.

Every production guard in ``app.core.config.Settings`` (JWT-secret
strength, HTTPS frontend, CORS lockdown) keys off ``ENVIRONMENT`` — whose
default is ``"development"``. A deployment that forgets that single env
var used to silently disarm all of them while serving real traffic:
weak dev JWT secret accepted, localhost CORS origins allowed, HTTP
frontend URL tolerated.

These tests pin the fix: Railway's auto-injected ``RAILWAY_ENVIRONMENT``
promotes an omitted ``ENVIRONMENT`` to ``production``, so the guards can
no longer be skipped by omission on the project's deploy target. An
explicit ``ENVIRONMENT`` (any source) still wins as a deliberate opt-out.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings

_DB_URL = "postgresql://postgres:postgres@localhost:5432/thecee"


@pytest.fixture(autouse=True)
def _clean_platform_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control both channels Settings sources read for this decision."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)


def _settings(**overrides: str) -> Settings:
    # _env_file=None keeps a developer's local .env out of the picture so
    # each test exercises exactly the env vars it controls.
    return Settings(_env_file=None, DATABASE_URL=_DB_URL, **overrides)


def test_forgotten_environment_on_railway_becomes_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this file exists for: a deploy that never set
    ENVIRONMENT must not run as "development" on Railway."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    # Strong secret + HTTPS frontend so ONLY the ENVIRONMENT promotion is
    # under test (each guard's rejection gets its own test below).
    settings = _settings(
        FRONTEND_URL="https://app.thecee.ai",
        SECRET_KEY="inferred-prod-secret-with-enough-length-32",
    )
    assert settings.ENVIRONMENT == "production"


def test_inferred_production_rejects_weak_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The forgotten-env-var deploy must hard-fail on the dev SECRET_KEY
    default instead of silently minting JWTs with it."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="SECRET_KEY must be"):
        _settings()  # SECRET_KEY left at its dev default


def test_explicit_development_beats_platform_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ENVIRONMENT is a deliberate opt-out and must win over
    the platform signal — inference only covers omission."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    settings = _settings(ENVIRONMENT="development")
    assert settings.ENVIRONMENT == "development"
    assert "http://localhost:3000" in settings.cors_allowed_origins()


def test_no_platform_signal_keeps_dev_default() -> None:
    """Local development without Railway vars is completely unchanged —
    including acceptance of the weak dev secret default."""
    settings = _settings(SECRET_KEY="dev-secret-change-in-prod")
    assert settings.ENVIRONMENT == "development"
    assert "http://localhost:3000" in settings.cors_allowed_origins()


def test_preview_environments_get_full_guards_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Railway preview deploys are public internet as well, so *any*
    RAILWAY_ENVIRONMENT value infers production (presence-based, not
    value-matched). Set ENVIRONMENT=development explicitly if a preview
    genuinely needs dev-mode guards."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "pr-123-preview")
    with pytest.raises(ValueError, match="SECRET_KEY must be"):
        _settings()


def test_inferred_production_requires_https_frontend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    # Strong secret so the HTTPS guard is the one that trips (validators
    # run in definition order; the weak-secret guard fires first otherwise).
    with pytest.raises(ValueError, match="FRONTEND_URL must be an https:// URL"):
        _settings(
            FRONTEND_URL="http://localhost:3000",
            SECRET_KEY="inferred-prod-secret-with-enough-length-32",
        )


def test_inferred_production_locks_cors_when_configured_properly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: a correctly configured Railway deploy gets the locked
    production CORS allowlist through inference alone."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    settings = _settings(
        FRONTEND_URL="https://app.thecee.ai",
        SECRET_KEY="inferred-prod-secret-with-enough-length-32",
    )
    assert settings.cors_allowed_origins() == ["https://app.thecee.ai"]
