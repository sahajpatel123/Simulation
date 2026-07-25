"""Regression tests for the handle field's character-class restriction.

``UserUpdate.handle`` is exposed in JSON (the export endpoint returns
it directly) and is rendered in the frontend profile surface. The
field previously had only a 64-char length cap, so a stored XSS
payload like ``"<script>alert(1)</script>"`` could be smuggled
through this field — relying on the frontend to escape it before
rendering.

The Pydantic layer now pins the character class to ``[A-Za-z0-9_-]``
so the API rejects unsafe handles at validation time, regardless of
what the renderer does downstream.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import UserUpdate


VALID_HANDLES = [
    "alice",
    "alice_123",
    "a-b-c",
    "TestUser",
    "x",
    "A1_b-2_C",
    "123",
    "a" * 64,  # max length
]


INVALID_HANDLES = [
    # XSS payloads
    "<script>",
    "<script>alert(1)</script>",
    "alice<bob",
    # Email-like
    "alice@example.com",
    "alice@bob",
    # Whitespace
    "alice space",
    "alice ",
    " alice",
    # Special chars
    "alice!",
    "alice?",
    "alice#",
    "alice/bob",
    "a&b",
    "alice's",
    'alice"',
    # Path-traversal-ish
    "../alice",
    "alice/../bob",
    # Empty
    "",
    # Unicode (defence: stick to ASCII so the field is
    # universally safe across renderers)
    "álice",
    "alice🚀",
]


@pytest.mark.parametrize("handle", VALID_HANDLES)
def test_valid_handles_accepted(handle: str) -> None:
    r = UserUpdate(handle=handle)
    assert r.handle == handle


@pytest.mark.parametrize("handle", INVALID_HANDLES)
def test_invalid_handles_rejected(handle: str) -> None:
    with pytest.raises(ValidationError):
        UserUpdate(handle=handle)


def test_handle_is_optional() -> None:
    assert UserUpdate().handle is None


def test_handle_max_length_64() -> None:
    assert UserUpdate(handle="a" * 64).handle == "a" * 64
    with pytest.raises(ValidationError):
        UserUpdate(handle="a" * 65)
