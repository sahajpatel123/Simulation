"""Route-level tests for the /me/account/export endpoint."""
from __future__ import annotations

import asyncio
import sys
import types

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _User:
    def __init__(self) -> None:
        self.id = 42
        self.email = "a@b.com"
        self.full_name = "Ada"
        self.tier = "free"
        self.subscription_tier = None
        self.simulations_used_this_month = 2
        self.is_admin = False
        self.created_at = "2026-08-08T04:00:00+00:00"


def _call_route(*, format: str = "csv"):
    from app.api.v1 import users as user_mod

    return user_mod.export_my_account(
        format=format,
        db=object(),
        current_user=_User(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_my_account_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'attachment; filename="my-account.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "user_id,email,full_name,tier" in body
    assert "42,a@b.com,Ada,free,,2,False" in body
    assert "user_id,42" in body


def test_export_my_account_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"account"' in body
    assert '"user_id": 42' in body
    assert '"email": "a@b.com"' in body
