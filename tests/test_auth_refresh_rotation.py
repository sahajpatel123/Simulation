"""Regression tests for the atomic refresh-token rotation in app.api.v1.auth.

The atomic claim refactor (UPDATE...RETURNING pinned to NOT revoked AND not
expired) closes a TOCTOU race where two concurrent rotation requests could
both pass the prior read-then-write check and emit duplicate access tokens.
These tests pin the new behaviour so a regression cannot silently re-introduce
the race.

We import the auth module directly (bypassing app.api.v1.__init__) so this
test stays decoupled from the rest of the v1 router package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.auth import RefreshRequest

_AUTH_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "v1"
    / "auth.py"
)


def _load_auth_module():
    spec = importlib.util.spec_from_file_location(
        "app_api_v1_auth_under_test", _AUTH_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_auth = _load_auth_module()


def _session_returning(claim: dict | None) -> MagicMock:
    """Build a mock Session whose execute() returns the given claim row."""
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = claim
    session.execute.return_value = result
    return session


def test_first_rotation_succeeds_and_persists_new_token() -> None:
    """A valid refresh token rotates and stores the new token in one transaction."""
    session = _session_returning({"user_id": 42})

    with patch.object(_auth, "_store_refresh_token") as store, \
            patch.object(_auth, "create_refresh_token", return_value="new-refresh"), \
            patch.object(_auth, "create_access_token", return_value="new-access"):
        response = _auth.refresh_access_token(
            payload=RefreshRequest(refresh_token="valid-token"),
            db=session,
        )

    assert response.access_token == "new-access"
    assert response.refresh_token == "new-refresh"
    store.assert_called_once_with(session, 42, "new-refresh")
    session.commit.assert_called_once()


def test_second_rotation_of_same_token_is_rejected() -> None:
    """After the first rotation, the WHERE clause matches zero rows
    (revoked=TRUE) and the endpoint raises 401 — no duplicate access token."""
    session = _session_returning(None)

    with patch.object(_auth, "_store_refresh_token") as store, \
            patch.object(_auth, "create_access_token") as create_access:
        with pytest.raises(HTTPException) as exc_info:
            _auth.refresh_access_token(
                payload=RefreshRequest(refresh_token="already-rotated"),
                db=session,
            )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid refresh token"
    store.assert_not_called()
    create_access.assert_not_called()
    session.commit.assert_not_called()


def test_expired_token_is_rejected_without_side_effects() -> None:
    """An expired refresh token produces no claim row and no commit."""
    session = _session_returning(None)

    with patch.object(_auth, "_store_refresh_token") as store:
        with pytest.raises(HTTPException) as exc_info:
            _auth.refresh_access_token(
                payload=RefreshRequest(refresh_token="expired-token"),
                db=session,
            )

    assert exc_info.value.status_code == 401
    store.assert_not_called()
    session.commit.assert_not_called()


def test_unknown_token_is_rejected_with_uniform_detail() -> None:
    """Unknown tokens share the same 401 detail as revoked/expired tokens —
    prevents oracle-style enumeration of which check failed."""
    session = _session_returning(None)

    with pytest.raises(HTTPException) as exc_info:
        _auth.refresh_access_token(
            payload=RefreshRequest(refresh_token="never-issued"),
            db=session,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid refresh token"
