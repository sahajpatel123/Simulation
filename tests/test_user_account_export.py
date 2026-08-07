"""Tests for the pure user account export helper."""
from __future__ import annotations

from app.simulation.user_account_export import user_account_to_csv


def test_user_account_to_csv_contains_header_and_row() -> None:
    csv_text = user_account_to_csv(
        {
            "user_id": 42,
            "email": "a@b.com",
            "full_name": "Ada",
            "tier": "free",
            "subscription_tier": None,
            "simulations_used_this_month": 2,
            "is_admin": False,
            "created_at": "2026-08-08T04:00:00+00:00",
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "user_id,email,full_name,tier" in csv_text
    assert "42,a@b.com,Ada,free,,2,False" in csv_text
    assert "generated_at,now" in csv_text


def test_user_account_to_csv_handles_missing_fields() -> None:
    csv_text = user_account_to_csv({"user_id": 42})

    assert "42," in csv_text
