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
