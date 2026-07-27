from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.security import validate_password_strength


def test_password_policy_accepts_strong_password() -> None:
    password = "StrongPass1!"
    assert validate_password_strength(password) == password


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short1A!", "at least 10 characters"),
        ("nouppercase1!", "uppercase"),
        ("NOLOWERCASE1!", "lowercase"),
        ("NoNumberHere!", "number"),
        ("NoSpecial123", "special character"),
    ],
)
def test_password_policy_rejects_weak_passwords(password: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_password_strength(password)


def test_production_cors_only_allows_configured_frontend() -> None:
    settings = Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
        ENVIRONMENT="production",
        FRONTEND_URL="https://app.thecee.ai",
        SECRET_KEY="production-test-secret-with-32-plus-chars",
    )

    assert settings.cors_allowed_origins() == ["https://app.thecee.ai"]


def test_development_cors_keeps_localhost_origins() -> None:
    settings = Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
        ENVIRONMENT="development",
        FRONTEND_URL="https://staging.thecee.ai",
    )

    assert settings.cors_allowed_origins() == [
        "https://staging.thecee.ai",
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_production_rejects_http_frontend_url() -> None:
    """Regression: in production, FRONTEND_URL must be HTTPS.

    Without this guard a deployment that forgets to set the
    env var would silently fall back to the dev default
    http://localhost:3000 — and the CORS layer would accept
    HTTP requests from localhost against the production API.
    """
    with pytest.raises(
        ValueError,
        match="FRONTEND_URL must be an https:// URL in production",
    ):
        Settings(
            DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
            ENVIRONMENT="production",
            FRONTEND_URL="http://app.thecee.ai",
            SECRET_KEY="production-test-secret-with-32-plus-chars",
        )


def test_production_rejects_empty_frontend_url() -> None:
    """An empty FRONTEND_URL in production would silently
    allow NO origin (fail-closed at CORS) but a missing env
    var is almost always a deploy bug — surface it loudly."""
    with pytest.raises(
        ValueError,
        match="FRONTEND_URL must be an https:// URL in production",
    ):
        Settings(
            DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
            ENVIRONMENT="production",
            FRONTEND_URL="",
            SECRET_KEY="production-test-secret-with-32-plus-chars",
        )


def test_production_accepts_https_frontend_url() -> None:
    """The happy path: production + HTTPS works."""
    settings = Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
        ENVIRONMENT="production",
        FRONTEND_URL="https://app.thecee.ai",
        SECRET_KEY="production-test-secret-with-32-plus-chars",
    )
    assert settings.cors_allowed_origins() == ["https://app.thecee.ai"]


def test_development_allows_http_frontend_url() -> None:
    """Dev / staging shouldn't fail closed on http://.
    The dev allowlist always prepends the localhost defaults
    (3000, 3001) regardless of FRONTEND_URL."""
    settings = Settings(
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/thecee",
        ENVIRONMENT="development",
        FRONTEND_URL="http://localhost:3000",
    )
    origins = settings.cors_allowed_origins()
    assert "http://localhost:3000" in origins
    assert "http://localhost:3001" in origins
