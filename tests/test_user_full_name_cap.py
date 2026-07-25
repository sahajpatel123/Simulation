"""Regression tests for full_name length caps on user schemas.

``UserCreate.full_name`` and ``UserUpdate.full_name`` previously
accepted any length. A single request could persist a 10MB string
into ``users.full_name`` (VARCHAR(255) column — would fail at the DB
level with a confusing 500) or pass through to the Press Office
"Cast Defaults" rendering.

Cap both at 255 chars (matches the DB column) so the limit fails
fast at the Pydantic layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import UserCreate, UserUpdate


class TestUserCreateFullName:
    def test_short_ok(self) -> None:
        r = UserCreate(email="a@b.com", password="StrongPass1!", full_name="Alice")
        assert r.full_name == "Alice"

    def test_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(
                email="a@b.com",
                password="StrongPass1!",
                full_name="x" * 256,
            )

    def test_max_boundary_ok(self) -> None:
        r = UserCreate(
            email="a@b.com", password="StrongPass1!", full_name="x" * 255
        )
        assert r.full_name == "x" * 255

    def test_optional(self) -> None:
        r = UserCreate(email="a@b.com", password="StrongPass1!")
        assert r.full_name is None


class TestUserUpdateFullName:
    def test_short_ok(self) -> None:
        r = UserUpdate(full_name="Alice")
        assert r.full_name == "Alice"

    def test_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserUpdate(full_name="x" * 256)

    def test_max_boundary_ok(self) -> None:
        r = UserUpdate(full_name="x" * 255)
        assert r.full_name == "x" * 255

    def test_optional(self) -> None:
        assert UserUpdate().full_name is None
