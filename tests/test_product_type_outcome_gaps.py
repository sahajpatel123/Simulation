"""Tests for the product-type outcome-feedback coverage digest.

Covers the pure digest builder (rollup math, urgency distribution, accuracy
aggregation, narratives, weakest-first sorting) and the
``GET /users/me/outcome-gaps/product-types`` route (SQL scoping, registration).
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.product_type_outcome_gaps import ProductTypeOutcomeGapsOut
from app.simulation.outcome_gaps import URGENCY_HIGH, URGENCY_LOW, URGENCY_MEDIUM
from app.simulation.product_type_outcome_gaps import (
    build_product_type_outcome_gaps_digest,
)

pytest.importorskip("scipy", reason="Route registration requires scipy")

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _coverage_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "product_type": "saas",
        "project_id": 7,
        "total_completed": 10,
        "scored": 4,
        "unscored": 6,
        "learning_eligible_unscored": 2,
        "high_priority_unscored": 1,
        "medium_priority_unscored": 1,
        "oldest_unscored_created_at": _NOW - timedelta(days=40),
        "oldest_eligible_unscored_created_at": _NOW - timedelta(days=40),
    }
    row.update(overrides)
    return row


def _accuracy_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "product_type": "saas",
        "results_json": {"population_weighted_conversion": 0.04},
        "actual_conversion_rate": 0.06,
    }
    row.update(overrides)
    return row


# ── Pure builder tests ─────────────────────────────────────────────


def test_empty_digest() -> None:
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[],
        accuracy_rows=[],
        now=_NOW,
    )

    assert payload["user_id"] == 42
    assert payload["product_types"] == []
    assert payload["learning_eligible_only"] is False
    summary = payload["summary"]
    assert summary["product_type_count"] == 0
    assert summary["project_count"] == 0
    assert summary["total_completed"] == 0
    assert summary["coverage_rate_pct"] == 0.0
    assert summary["oldest_unscored_age_days"] is None
    assert "No completed simulations across your portfolio yet" in (
        summary["narrative"]
    )


def test_all_scored_digest() -> None:
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(
                total_completed=3,
                scored=3,
                unscored=0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                medium_priority_unscored=0,
                oldest_unscored_created_at=None,
                oldest_eligible_unscored_created_at=None,
            )
        ],
        accuracy_rows=[],
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["coverage_rate_pct"] == 100.0
    assert summary["unscored"] == 0
    row = payload["product_types"][0]
    assert row["urgency_counts"] == {
        URGENCY_HIGH: 0,
        URGENCY_MEDIUM: 0,
        URGENCY_LOW: 0,
    }
    assert row["recommendation"] == (
        "All completed runs for this product type have outcome feedback."
    )
    assert "All completed simulations across your portfolio" in (
        summary["narrative"]
    )


def test_mixed_product_types_rollup_and_weakest_first_sort() -> None:
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(),
            _coverage_row(
                product_type="consumer_hardware",
                project_id=9,
                total_completed=6,
                scored=0,
                unscored=6,
                learning_eligible_unscored=3,
                high_priority_unscored=2,
                medium_priority_unscored=1,
                oldest_unscored_created_at=_NOW - timedelta(days=45),
                oldest_eligible_unscored_created_at=_NOW - timedelta(days=45),
            ),
            _coverage_row(
                product_type="",
                project_id=7,
                total_completed=2,
                scored=2,
                unscored=0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                medium_priority_unscored=0,
                oldest_unscored_created_at=None,
                oldest_eligible_unscored_created_at=None,
            ),
        ],
        accuracy_rows=[],
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["product_type_count"] == 3
    assert summary["project_count"] == 2
    assert summary["total_completed"] == 18
    assert summary["scored"] == 6
    assert summary["unscored"] == 12
    assert summary["coverage_rate_pct"] == pytest.approx(33.33)
    assert summary["learning_eligible_unscored"] == 5
    assert summary["high_priority_unscored"] == 3
    assert summary["oldest_unscored_age_days"] == 45

    types_ = [row["product_type"] for row in payload["product_types"]]
    assert types_ == ["consumer_hardware", "saas", "unknown"]

    hardware = payload["product_types"][0]
    assert hardware["coverage_rate_pct"] == 0.0
    assert hardware["unscored"] == 6
    assert hardware["urgency_counts"] == {
        URGENCY_HIGH: 2,
        URGENCY_MEDIUM: 1,
        URGENCY_LOW: 3,
    }
    assert "2 stale learning-eligible run(s) need" in (
        hardware["recommendation"]
    )

    unknown = payload["product_types"][2]
    assert unknown["product_type"] == "unknown"
    assert unknown["coverage_rate_pct"] == 100.0

    narrative = summary["narrative"]
    assert "Across 3 product type(s) and 2 project(s)" in narrative
    assert "6 of 18 completed runs" in narrative
    assert "12 unscored run(s) remain" in narrative
    assert "Weakest feedback loop: 'consumer_hardware' — 0 of 6 scored" in (
        narrative
    )
    assert "oldest unscored run is 45 days old" in narrative
    assert "3 of those are 30+ days old" in narrative


def test_learning_eligible_only_uses_eligible_counts_but_full_totals() -> None:
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(),
            _coverage_row(
                product_type="consumer_hardware",
                project_id=9,
                total_completed=6,
                scored=0,
                unscored=6,
                learning_eligible_unscored=3,
                high_priority_unscored=2,
                medium_priority_unscored=1,
                oldest_unscored_created_at=_NOW - timedelta(days=45),
                oldest_eligible_unscored_created_at=_NOW - timedelta(days=45),
            ),
        ],
        accuracy_rows=[],
        learning_eligible_only=True,
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["total_completed"] == 16
    assert summary["scored"] == 4
    assert summary["unscored"] == 5
    assert summary["coverage_rate_pct"] == pytest.approx(25.0)
    assert summary["learning_eligible_unscored"] == 5
    assert summary["high_priority_unscored"] == 3
    assert summary["oldest_unscored_age_days"] == 45
    assert payload["learning_eligible_only"] is True

    saas = next(
        row for row in payload["product_types"] if row["product_type"] == "saas"
    )
    assert saas["unscored"] == 2
    assert saas["total_completed"] == 10
    assert saas["urgency_counts"] == {
        URGENCY_HIGH: 1,
        URGENCY_MEDIUM: 1,
        URGENCY_LOW: 0,
    }
    hardware = next(
        row
        for row in payload["product_types"]
        if row["product_type"] == "consumer_hardware"
    )
    assert hardware["unscored"] == 3
    assert hardware["urgency_counts"] == {
        URGENCY_HIGH: 2,
        URGENCY_MEDIUM: 1,
        URGENCY_LOW: 0,
    }

    narrative = summary["narrative"]
    assert narrative.startswith("Showing learning-eligible unscored runs only.")
    assert "5 unscored learning-eligible run(s) remain." in narrative
    assert "25.0%" in narrative


def test_mean_absolute_gap_aggregation_per_product_type() -> None:
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(total_completed=3, scored=2, unscored=1),
            _coverage_row(
                product_type="consumer_hardware",
                project_id=9,
                total_completed=2,
                scored=1,
                unscored=1,
            ),
        ],
        accuracy_rows=[
            _accuracy_row(actual_conversion_rate=0.05),
            _accuracy_row(actual_conversion_rate=0.07),
            _accuracy_row(
                product_type="consumer_hardware",
                results_json={"population_weighted_conversion": 0.04},
                actual_conversion_rate=0.02,
            ),
            _accuracy_row(actual_conversion_rate=None),
            _accuracy_row(results_json={"not_a_conversion": 1}),
            None,
        ],
        now=_NOW,
    )

    saas = next(
        row for row in payload["product_types"] if row["product_type"] == "saas"
    )
    hardware = next(
        row
        for row in payload["product_types"]
        if row["product_type"] == "consumer_hardware"
    )
    assert saas["scored_with_prediction"] == 2
    assert saas["mean_absolute_gap"] == pytest.approx(0.02)
    assert hardware["scored_with_prediction"] == 1
    assert hardware["mean_absolute_gap"] == pytest.approx(0.02)


def test_mean_absolute_gap_uses_scalar_prediction_fields() -> None:
    """The route can avoid shipping full results blobs for accuracy math."""
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(
                total_completed=2,
                scored=2,
                unscored=0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                medium_priority_unscored=0,
                oldest_unscored_created_at=None,
                oldest_eligible_unscored_created_at=None,
            )
        ],
        accuracy_rows=[
            {
                "product_type": "saas",
                "population_weighted_conversion": 0.04,
                "conversion_rate": None,
                "mean_conversion_rate": None,
                "actual_conversion_rate": 0.06,
            },
            {
                "product_type": "saas",
                "population_weighted_conversion": None,
                "conversion_rate": 0.10,
                "mean_conversion_rate": None,
                "actual_conversion_rate": 0.08,
            },
        ],
        now=_NOW,
    )

    saas = payload["product_types"][0]
    assert saas["scored_with_prediction"] == 2
    assert saas["mean_absolute_gap"] == pytest.approx(0.02)


def test_learning_eligible_only_recommendation_for_below_floor_only() -> None:
    """A product type with only low-signal unscored runs is not 'all scored'."""
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(
                total_completed=5,
                scored=3,
                unscored=2,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                medium_priority_unscored=0,
                oldest_unscored_created_at=_NOW - timedelta(days=2),
                oldest_eligible_unscored_created_at=None,
            )
        ],
        learning_eligible_only=True,
        now=_NOW,
    )

    saas = payload["product_types"][0]
    assert saas["unscored"] == 0
    assert "No learning-eligible unscored runs remain" in saas["recommendation"]
    assert "All completed runs" not in saas["recommendation"]


def test_malformed_coverage_rate_is_clamped_and_validates() -> None:
    """Scored-beyond-total rows cannot overflow the 100% schema bound."""
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            _coverage_row(
                total_completed=2,
                scored=5,
                unscored=0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                medium_priority_unscored=0,
                oldest_unscored_created_at=None,
                oldest_eligible_unscored_created_at=None,
            )
        ],
        now=_NOW,
    )

    assert payload["product_types"][0]["coverage_rate_pct"] == 100.0
    assert payload["summary"]["coverage_rate_pct"] == 100.0
    # The response schema must still accept the payload (previously a 500).
    parsed = ProductTypeOutcomeGapsOut(**payload)
    assert parsed.product_types[0].coverage_rate_pct == 100.0


def test_malformed_rows_are_tolerated() -> None:
    payload = build_product_type_outcome_gaps_digest(
        user_id=42,
        coverage_rows=[
            None,
            {"product_type": "saas", "total_completed": "oops"},
            {
                "product_type": "  ",
                "project_id": "bad",
                "total_completed": 3,
                "scored": 1,
                "unscored": 2,
                "learning_eligible_unscored": "oops",
                "high_priority_unscored": 1,
                "medium_priority_unscored": "oops",
                "oldest_unscored_created_at": "not-a-date",
            },
        ],
        accuracy_rows=[{"product_type": "saas", "actual_conversion_rate": "nan"}],
        now=_NOW,
    )

    summary = payload["summary"]
    assert summary["product_type_count"] == 2
    assert summary["total_completed"] == 3
    assert summary["scored"] == 1
    assert summary["unscored"] == 2
    assert summary["project_count"] == 0
    rows_by_type = {
        row["product_type"]: row for row in payload["product_types"]
    }
    assert rows_by_type["unknown"]["oldest_unscored_age_days"] is None
    assert rows_by_type["saas"]["mean_absolute_gap"] is None


# ── Route tests ────────────────────────────────────────────────────


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return list(self.rows)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self.rows)


class _FakeSession:
    def __init__(self, *, responses: list[_FakeResult] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def execute(self, statement, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append({"sql": str(statement), "params": params})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResult([])


def _responses() -> list[_FakeResult]:
    return [
        _FakeResult(
            [
                {
                    "product_type": "saas",
                    "project_id": 7,
                    "total_completed": 3,
                    "scored": 1,
                    "unscored": 2,
                    "learning_eligible_unscored": 1,
                    "high_priority_unscored": 1,
                    "medium_priority_unscored": 1,
                    "oldest_unscored_created_at": _NOW - timedelta(days=40),
                    "oldest_eligible_unscored_created_at": (
                        _NOW - timedelta(days=40)
                    ),
                },
                {
                    "product_type": "consumer_hardware",
                    "project_id": 9,
                    "total_completed": 2,
                    "scored": 2,
                    "unscored": 0,
                    "learning_eligible_unscored": 0,
                    "high_priority_unscored": 0,
                    "medium_priority_unscored": 0,
                    "oldest_unscored_created_at": None,
                    "oldest_eligible_unscored_created_at": None,
                },
            ]
        ),
        _FakeResult(
            [
                {
                    "product_type": "saas",
                    "results_json": {"population_weighted_conversion": 0.04},
                    "actual_conversion_rate": 0.06,
                }
            ]
        ),
    ]


def _call_route(
    *,
    session: _FakeSession | None = None,
    learning_eligible_only: bool = False,
) -> ProductTypeOutcomeGapsOut:
    from app.api.v1 import users as users_mod

    return users_mod.get_my_outcome_gaps_by_product_type(
        learning_eligible_only=learning_eligible_only,
        db=session or _FakeSession(responses=_responses()),
        current_user=type("U", (), {"id": 42})(),
    )


def test_route_returns_product_type_digest_payload() -> None:
    result = _call_route()

    assert isinstance(result, ProductTypeOutcomeGapsOut)
    assert result.user_id == 42
    assert result.summary.product_type_count == 2
    assert result.summary.project_count == 2
    assert result.summary.total_completed == 5
    assert result.summary.scored == 3
    assert result.summary.unscored == 2
    assert result.summary.coverage_rate_pct == pytest.approx(60.0)
    assert [row.product_type for row in result.product_types] == [
        "saas",
        "consumer_hardware",
    ]
    saas = result.product_types[0]
    assert saas.coverage_rate_pct == pytest.approx(33.33)
    assert saas.urgency_counts[URGENCY_HIGH] == 1
    assert saas.mean_absolute_gap == pytest.approx(0.02)
    assert saas.scored_with_prediction == 1


def test_route_sql_is_scoped_and_uses_filter_aggregates() -> None:
    session = _FakeSession(responses=_responses())
    _call_route(session=session)

    assert len(session.calls) == 2
    coverage_sql = session.calls[0]["sql"]
    accuracy_sql = session.calls[1]["sql"]
    assert "p.user_id = :uid" in coverage_sql
    assert "p.user_id = :uid" in accuracy_sql
    assert "UPPER(s.status) = 'COMPLETED'" in coverage_sql
    assert "FILTER" in coverage_sql
    assert "GROUP BY s.project_id, product_type" in coverage_sql
    assert "fo.simulation_id = s.id" in coverage_sql
    assert "fo.project_id = s.project_id" in coverage_sql
    assert "fo.actual_conversion_rate IS NOT NULL" in accuracy_sql
    assert "DISTINCT ON (s.id)" in accuracy_sql
    assert "fo.project_id = s.project_id" in accuracy_sql
    assert "UPPER(s.status) = 'COMPLETED'" in accuracy_sql
    assert "population_weighted_conversion" in accuracy_sql
    assert "s.results_json AS results_json" not in accuracy_sql
    assert session.calls[0]["params"] == {
        "uid": 42,
        "min_sq": 0.25,
        "stale_cutoff": session.calls[0]["params"]["stale_cutoff"],
        "recent_cutoff": session.calls[0]["params"]["recent_cutoff"],
    }
    assert session.calls[1]["params"] == {"uid": 42}


def test_route_learning_eligible_only_is_forwarded() -> None:
    result = _call_route(learning_eligible_only=True)

    assert result.learning_eligible_only is True
    assert result.summary.unscored == 1
    assert result.summary.total_completed == 5
    saas = result.product_types[0]
    assert saas.urgency_counts[URGENCY_MEDIUM] == 0
    assert saas.urgency_counts[URGENCY_LOW] == 0


def test_route_is_registered_on_users_router() -> None:
    from app.api.v1 import users as users_mod

    paths = {route.path for route in users_mod.router.routes}
    assert "/users/me/outcome-gaps/product-types" in paths
    for route in users_mod.router.routes:
        if route.path == "/users/me/outcome-gaps/product-types":
            assert "GET" in (route.methods or set())
