"""Defensive tests for decode_token's required-claims enforcement.

decode_token now passes ``options={"require": ["exp", "sub", "type"]}`` to
python-jose. A token missing any of those claims must fail closed (return
None) rather than silently bypassing the check. This file pins that
contract so the defence cannot regress to a permissive default.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import settings
from app.core.security import decode_token


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def test_decode_accepts_well_formed_token() -> None:
    """Baseline: a token with exp, sub, and type decodes successfully."""
    token = _encode(
        {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "sub": "123",
            "type": "access",
        }
    )
    assert decode_token(token, token_type="access") == "123"


def test_decode_rejects_token_missing_exp() -> None:
    """A token with no ``exp`` must fail closed — expiry cannot be skipped."""
    token = _encode({"sub": "123", "type": "access"})
    assert decode_token(token, token_type="access") is None


def test_decode_rejects_token_missing_sub() -> None:
    """A token with no ``sub`` must fail closed — we cannot identify the user."""
    token = _encode(
        {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "type": "access",
        }
    )
    assert decode_token(token, token_type="access") is None


def test_decode_rejects_token_missing_type() -> None:
    """A token with no ``type`` must fail closed — token-type confusion guard."""
    token = _encode(
        {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "sub": "123",
        }
    )
    assert decode_token(token, token_type="access") is None


def test_decode_rejects_wrong_token_type() -> None:
    """A refresh token must not be accepted as an access token."""
    token = _encode(
        {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "sub": "123",
            "type": "refresh",
        }
    )
    assert decode_token(token, token_type="access") is None


def test_decode_rejects_expired_token() -> None:
    """An expired token must fail closed even if all other claims are present."""
    token = _encode(
        {
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
            "sub": "123",
            "type": "access",
        }
    )
    assert decode_token(token, token_type="access") is None


def test_decode_rejects_wrong_signature() -> None:
    """A token signed with a different secret must fail closed."""
    token = jwt.encode(
        {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "sub": "123",
            "type": "access",
        },
        "wrong-secret-not-the-real-one-32chars-min",
        algorithm=settings.ALGORITHM,
    )
    assert decode_token(token, token_type="access") is None
