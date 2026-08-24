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


def test_password_policy_caps_at_bcrypt_byte_limit() -> None:
    """bcrypt digests only the first 72 bytes of a secret — anything
    longer must be rejected at validation time instead of silently
    truncated (or blowing up inside passlib depending on backend)."""
    boundary = "Aa1!" + "a" * 68  # exactly 72 bytes, all rules satisfied
    assert len(boundary.encode("utf-8")) == 72
    assert validate_password_strength(boundary) == boundary

    with pytest.raises(ValueError, match="72 bytes"):
        validate_password_strength(boundary + "x")


def test_password_policy_counts_bytes_not_characters() -> None:
    """Multi-byte characters consume bcrypt's byte budget faster than the
    character count suggests — the cap must be measured in UTF-8 bytes."""
    emoji = "\U0001f600"  # 😀 — 4 UTF-8 bytes
    password = "Aa1!" + "a" * 6 + emoji * 16
    assert len(password) == 26  # passes the character floor
    assert len(password.encode("utf-8")) == 74  # but blows the byte cap
    with pytest.raises(ValueError, match="72 bytes"):
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


# ---------------------------------------------------------------------------
# Login timing equalisation — unknown emails must not be a fast path
# ---------------------------------------------------------------------------


def test_password_hash_roundtrip_survives_real_bcrypt() -> None:
    """A real hash → verify roundtrip against the installed backend.

    This is the regression that catches a broken hash-pairing: the pinned
    ``passlib==1.7.4`` + ``bcrypt==5.0.0`` combo made every ``hash()``
    raise ``ValueError`` regardless of input length, and no import-only
    test could see it.
    """
    from app.core.security import get_password_hash, verify_password

    hashed = get_password_hash("StrongPass1!")
    assert hashed.startswith("$2")  # genuine bcrypt digest format
    assert verify_password("StrongPass1!", hashed) is True
    assert verify_password("WrongPass1!", hashed) is False


def test_verify_password_reads_malformed_digest_as_false() -> None:
    """A corrupt digest in storage must authenticate as 'wrong password',
    never crash the login path with an unhandled ValueError."""
    from app.core.security import verify_password

    assert verify_password("StrongPass1!", "not-a-bcrypt-digest") is False


def test_login_burns_bcrypt_for_unknown_emails() -> None:
    """The unknown-email branch must still perform a bcrypt verify against
    the dummy digest so its latency is indistinguishable from the
    wrong-password branch — otherwise response timing enumerates which
    addresses are registered."""
    pytest.importorskip("jwt")

    import sys
    import types
    from unittest.mock import patch

    from fastapi import HTTPException

    # Stub razorpay to avoid the transitive pkg_resources import that
    # breaks on minimal envs when app.api.v1.__init__ runs.
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.api.v1 import auth as auth_mod
    from app.schemas.auth import UserLogin

    class _FakeQuery:
        def filter(self, *_a, **_k):
            return self

        def first(self):
            return None  # no such user

    class _FakeDB:
        def query(self, *_a, **_k):
            return _FakeQuery()

    verify_calls: list[tuple[str, str]] = []

    def fake_verify(plain: str, hashed: str) -> bool:
        verify_calls.append((plain, hashed))
        return False

    payload = UserLogin(email="nobody@example.com", password="Whatever-123!")
    with patch.object(auth_mod, "verify_password", fake_verify):
        with pytest.raises(HTTPException) as exc_info:
            auth_mod.login(payload, db=_FakeDB())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Incorrect email or password"
    # Exactly one bcrypt round burned — against the dummy digest, with
    # the caller-supplied password as the candidate secret.
    assert len(verify_calls) == 1
    plain, hashed = verify_calls[0]
    assert plain == "Whatever-123!"
    assert hashed == auth_mod._DUMMY_PASSWORD_HASH
