"""Tests for personal API tokens (security helpers, CRUD routes, auth).

Covers the pure primitives in ``app.core.security``, the
``/users/me/api-tokens`` management routes, and the API-token fallback in
``app.core.deps`` (scope enforcement, revocation, expiry, JWT coexistence).
Uses an in-memory SQLite database so no PostgreSQL/Redis is required.
"""

from __future__ import annotations

import hashlib
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.api.v1.api_tokens import (  # noqa: E402
    MAX_ACTIVE_TOKENS,
    create_api_token,
    list_api_tokens,
    revoke_api_token,
)
from app.core.deps import get_current_user, get_current_user_optional, get_db  # noqa: E402
from app.core.security import (  # noqa: E402
    API_TOKEN_DEFAULT_DAYS,
    API_TOKEN_MAX_DAYS,
    API_TOKEN_MIN_DAYS,
    API_TOKEN_PREFIX,
    api_token_expiry,
    api_token_is_expired,
    create_access_token,
    generate_api_token,
    hash_api_token,
)
from app.models import Base  # noqa: E402
from app.models.api_token import ApiToken  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.api_token import (  # noqa: E402
    ApiTokenCreateIn,
)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create only the tables this feature touches. Other models carry
    # PostgreSQL-only DDL (e.g. partial unique indexes) that SQLite cannot
    # compile, and this test never queries them.
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["api_tokens"],
        ],
    )
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()
    engine.dispose()


def _user(db, user_id: int = 7) -> User:
    row = User(
        id=user_id,
        email=f"user{user_id}@example.com",
        hashed_password="x",
        full_name="Test User",
    )
    db.add(row)
    db.commit()
    return row


def _token_row(db, user_id: int, *, scope: str = "read", expires_in_days: int | None = 90):
    plaintext = generate_api_token()
    row = ApiToken(
        user_id=user_id,
        name="ci",
        token_hash=hash_api_token(plaintext),
        scope=scope,
        expires_at=api_token_expiry(expires_in_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext


def _app_with(db) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    def protected(current_user: User = Depends(get_current_user)) -> dict:
        return {"user_id": current_user.id}

    @app.post("/protected-write")
    def protected_write(current_user: User = Depends(get_current_user)) -> dict:
        return {"user_id": current_user.id}

    @app.get("/optional")
    def optional(
        current_user: User | None = Depends(get_current_user_optional),
    ) -> dict:
        return {"user_id": current_user.id if current_user else None}

    @app.post("/optional-write")
    def optional_write(
        current_user: User | None = Depends(get_current_user_optional),
    ) -> dict:
        return {"user_id": current_user.id if current_user else None}

    app.dependency_overrides[get_db] = lambda: db
    return app


# ---------------------------------------------------------------------------
# Pure security helpers
# ---------------------------------------------------------------------------


def test_generate_token_is_prefixed_unique_and_hashed() -> None:
    a = generate_api_token()
    b = generate_api_token()
    assert a.startswith(API_TOKEN_PREFIX)
    assert a != b
    # codeql[py/weak-sensitive-data-hashing]: characterization test pinning
    # at-rest hashing to plain SHA-256 (high-entropy token, not a password).
    assert hash_api_token(a) == hashlib.sha256(a.encode("utf-8")).hexdigest()
    assert hash_api_token(a) != hash_api_token(b)


def test_api_token_expiry_defaults_and_bounds() -> None:
    default = api_token_expiry(None)
    assert timedelta(days=API_TOKEN_DEFAULT_DAYS - 1) < default - datetime.now(UTC) < timedelta(days=API_TOKEN_DEFAULT_DAYS + 1)

    explicit = api_token_expiry(30)
    assert timedelta(days=29) < explicit - datetime.now(UTC) < timedelta(days=31)

    clamped_low = api_token_expiry(0)
    assert timedelta(days=API_TOKEN_MIN_DAYS - 1) < clamped_low - datetime.now(UTC) < timedelta(days=API_TOKEN_MIN_DAYS + 1)

    clamped_high = api_token_expiry(9999)
    assert timedelta(days=API_TOKEN_MAX_DAYS - 1) < clamped_high - datetime.now(UTC) < timedelta(days=API_TOKEN_MAX_DAYS + 1)


def test_expired_check_handles_none_naive_and_aware() -> None:
    now = datetime.now(UTC)
    assert api_token_is_expired(None) is False
    assert api_token_is_expired(now - timedelta(days=1)) is True
    assert api_token_is_expired(now + timedelta(days=1)) is False
    # Naive datetimes (SQLite round-trips) are interpreted as UTC.
    assert api_token_is_expired(now.replace(tzinfo=None) - timedelta(days=1)) is True
    assert api_token_is_expired(now.replace(tzinfo=None) + timedelta(days=1)) is False


def test_create_schema_strips_names_and_rejects_bad_input() -> None:
    payload = ApiTokenCreateIn(name="  ci bot  ", scope="read", expires_in_days=30)
    assert payload.name == "ci bot"

    with pytest.raises(ValidationError):
        ApiTokenCreateIn(name="   ", scope="read")
    with pytest.raises(ValidationError):
        ApiTokenCreateIn(name="ci", scope="sudo")
    with pytest.raises(ValidationError):
        ApiTokenCreateIn(name="ci", scope="read", expires_in_days=0)
    with pytest.raises(ValidationError):
        ApiTokenCreateIn(name="ci", scope="read", expires_in_days=366)


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------


def test_create_returns_plaintext_once_and_list_hides_it(db_session) -> None:
    user = _user(db_session)
    created = create_api_token(
        payload=ApiTokenCreateIn(name=" staging CI ", scope="read", expires_in_days=30),
        db=db_session,
        current_user=user,
    )

    assert created.token.startswith(API_TOKEN_PREFIX)
    assert created.name == "staging CI"
    assert created.scope == "read"
    stored = db_session.query(ApiToken).filter(ApiToken.id == created.id).first()
    assert stored is not None
    assert stored.token_hash == hash_api_token(created.token)
    assert stored.token_hash != created.token

    listed = list_api_tokens(db=db_session, current_user=user)
    assert listed.active_count == 1
    assert len(listed.items) == 1
    assert listed.items[0].id == created.id
    assert listed.items[0].is_active is True
    assert listed.items[0].scope == "read"
    assert not hasattr(listed.items[0], "token")


def test_active_token_cap_is_enforced(db_session) -> None:
    user = _user(db_session)
    for index in range(MAX_ACTIVE_TOKENS):
        create_api_token(
            payload=ApiTokenCreateIn(name=f"token-{index}", scope="read"),
            db=db_session,
            current_user=user,
        )

    with pytest.raises(HTTPException) as exc:
        create_api_token(
            payload=ApiTokenCreateIn(name="overflow", scope="read"),
            db=db_session,
            current_user=user,
        )
    assert exc.value.status_code == 400
    assert "limit reached" in str(exc.value.detail)

    # Revoking one frees a slot.
    first = db_session.query(ApiToken).first()
    revoke_api_token(token_id=first.id, db=db_session, current_user=user)
    created = create_api_token(
        payload=ApiTokenCreateIn(name="after-revoke", scope="read"),
        db=db_session,
        current_user=user,
    )
    assert created.id is not None


def test_revoke_is_idempotent_and_marks_token_inactive(db_session) -> None:
    user = _user(db_session)
    row, _ = _token_row(db_session, user.id)

    assert revoke_api_token(token_id=row.id, db=db_session, current_user=user) == {
        "ok": True
    }
    assert revoke_api_token(token_id=row.id, db=db_session, current_user=user) == {
        "ok": True
    }

    listed = list_api_tokens(db=db_session, current_user=user)
    assert listed.active_count == 0
    assert listed.items[0].is_active is False
    assert listed.items[0].revoked_at is not None


def test_revoke_enforces_ownership(db_session) -> None:
    user = _user(db_session, user_id=7)
    other = _user(db_session, user_id=8)
    row, _ = _token_row(db_session, other.id)

    with pytest.raises(HTTPException) as exc:
        revoke_api_token(token_id=row.id, db=db_session, current_user=user)
    assert exc.value.status_code == 404
    assert "not found" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# Authentication integration
# ---------------------------------------------------------------------------


def test_api_token_authenticates_protected_endpoints(db_session) -> None:
    user = _user(db_session)
    _, plaintext = _token_row(db_session, user.id, scope="read_write")
    client = TestClient(_app_with(db_session))

    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": user.id}


def test_read_scope_allows_get_but_blocks_post(db_session) -> None:
    user = _user(db_session)
    _, plaintext = _token_row(db_session, user.id, scope="read")
    client = TestClient(_app_with(db_session))

    get_resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert get_resp.status_code == 200

    post_resp = client.post(
        "/protected-write",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert post_resp.status_code == 403
    assert "scope 'read'" in post_resp.json()["detail"]


def test_read_write_scope_allows_mutating_methods(db_session) -> None:
    user = _user(db_session)
    _, plaintext = _token_row(db_session, user.id, scope="read_write")
    client = TestClient(_app_with(db_session))

    resp = client.post(
        "/protected-write",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"user_id": user.id}


def test_revoked_token_is_rejected(db_session) -> None:
    user = _user(db_session)
    row, plaintext = _token_row(db_session, user.id)
    revoke_api_token(token_id=row.id, db=db_session, current_user=user)
    client = TestClient(_app_with(db_session))

    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired token"


def test_expired_token_is_rejected(db_session) -> None:
    user = _user(db_session)
    plaintext = generate_api_token()
    row = ApiToken(
        user_id=user.id,
        name="expired",
        token_hash=hash_api_token(plaintext),
        scope="read",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(row)
    db_session.commit()
    client = TestClient(_app_with(db_session))

    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 401


def test_unknown_and_malformed_tokens_are_rejected(db_session) -> None:
    user = _user(db_session)
    _token_row(db_session, user.id)
    client = TestClient(_app_with(db_session))

    unknown = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {generate_api_token()}"},
    )
    assert unknown.status_code == 401

    malformed = client.get(
        "/protected",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert malformed.status_code == 401


def test_jwt_authentication_still_works_after_fallback(db_session) -> None:
    user = _user(db_session)
    client = TestClient(_app_with(db_session))
    jwt_token = create_access_token(str(user.id))

    resp = client.get("/protected", headers={"Authorization": f"Bearer {jwt_token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": user.id}


def test_optional_auth_resolves_token_or_none(db_session) -> None:
    user = _user(db_session)
    _, plaintext = _token_row(db_session, user.id, scope="read")
    client = TestClient(_app_with(db_session))

    ok = client.get(
        "/optional",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert ok.status_code == 200
    assert ok.json() == {"user_id": user.id}

    anonymous = client.get("/optional")
    assert anonymous.status_code == 200
    assert anonymous.json() == {"user_id": None}

    invalid = client.get(
        "/optional",
        headers={"Authorization": "Bearer nope"},
    )
    assert invalid.status_code == 200
    assert invalid.json() == {"user_id": None}


def test_optional_auth_read_scope_rejects_mutating_methods(db_session) -> None:
    """A valid read-scoped token is not downgraded to anonymous on POST —
    the scope violation surfaces as 403 instead of a silent bypass."""
    user = _user(db_session)
    _, plaintext = _token_row(db_session, user.id, scope="read")
    client = TestClient(_app_with(db_session))

    resp = client.post(
        "/optional-write",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 403
    assert "scope 'read'" in resp.json()["detail"]


def test_optional_auth_read_write_scope_allows_mutating_methods(db_session) -> None:
    user = _user(db_session)
    _, plaintext = _token_row(db_session, user.id, scope="read_write")
    client = TestClient(_app_with(db_session))

    resp = client.post(
        "/optional-write",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"user_id": user.id}


def test_optional_auth_invalid_token_stays_anonymous_on_mutating_methods(
    db_session,
) -> None:
    """Invalid credentials still downgrade to anonymous (None) on optional
    auth — only valid-but-insufficient tokens are rejected."""
    client = TestClient(_app_with(db_session))

    resp = client.post(
        "/optional-write",
        headers={"Authorization": "Bearer nope"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"user_id": None}


def test_last_used_at_is_stamped_on_authentication(db_session) -> None:
    user = _user(db_session)
    row, plaintext = _token_row(db_session, user.id)
    assert row.last_used_at is None

    client = TestClient(_app_with(db_session))
    resp = client.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert resp.status_code == 200

    refreshed = db_session.query(ApiToken).filter(ApiToken.id == row.id).first()
    assert refreshed.last_used_at is not None
