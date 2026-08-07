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


def test_user_account_to_csv_neutralizes_formula_injection() -> None:
    csv_text = user_account_to_csv(
        {
            "user_id": 42,
            "email": "=HYPERLINK(\"http://evil\")",
            "full_name": "-2+3",
            "tier": "free",
            "subscription_tier": "@cmd",
            "simulations_used_this_month": 2,
            "is_admin": False,
            "created_at": "=NOW()",
        },
        metadata={
            "generated_at": "=NOW()",
            "user_id": 42,
            "format_version": "1",
        },
    )

    assert "'=HYPERLINK" in csv_text
    assert "'-2+3" in csv_text
    assert "'@cmd" in csv_text
    assert "'=NOW()" in csv_text
    # Non-string cells stay unchanged.
    assert "False" in csv_text
    assert "2" in csv_text


def test_user_account_to_csv_neutralizes_formula_after_leading_whitespace() -> None:
    csv_text = user_account_to_csv(
        {
            "user_id": 7,
            "email": " =SUM(1,2)",
            "full_name": "\t=cmd",
            "tier": "  +1",
            "subscription_tier": "free",
            "simulations_used_this_month": 0,
            "is_admin": False,
            "created_at": "2026-08-08T04:00:00+00:00",
        }
    )

    assert "' =SUM(1,2)" in csv_text
    assert "'\t=cmd" in csv_text
    assert "'  +1" in csv_text


def test_user_account_to_csv_keeps_normal_text_unchanged() -> None:
    csv_text = user_account_to_csv(
        {
            "user_id": 8,
            "email": "ada@example.com",
            "full_name": "Ada Lovelace - mathematician",
            "tier": "free",
            "subscription_tier": None,
            "simulations_used_this_month": 1,
            "is_admin": True,
            "created_at": "2026-08-08T04:00:00+00:00",
        }
    )

    assert "ada@example.com" in csv_text
    assert "Ada Lovelace - mathematician" in csv_text
    assert "'Ada" not in csv_text
    assert "True" in csv_text
