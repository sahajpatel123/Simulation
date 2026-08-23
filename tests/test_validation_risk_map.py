"""Tests for the validation risk map.

Pins the category grouping (including the General fallback), the
transparent risk-score weights, verdict rollup parity with the verdicts
scorecard (killed = KILLED + UNBENCHMARKED_FAIL), quality rollup parity
with the evidence-quality grader, ranking, narrative, meta, and route
wiring.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from fastapi import HTTPException

from app.schemas.validation_risk_map import ValidationRiskMapOut
from app.simulation.validation_risk_map import build_validation_risk_map

_NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _asm(id_: int, text: str, category: str | None = "Pricing"):
    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(
    assumption_id: int,
    *,
    id_: int = 1,
    result: str = "PASS",
    method: str = "CONCIERGE_MVP",
    observed_metric: float | None = 0.65,
    age_days: int = 1,
):
    return SimpleNamespace(
        assumption_id=assumption_id,
        id=id_,
        result=result,
        method=method,
        observed_metric=observed_metric,
        created_at=_NOW - timedelta(days=age_days),
    )


def _map(assumptions, evidence):
    return build_validation_risk_map(
        project_id=5, assumptions=assumptions, evidence=evidence, now=_NOW
    )


def _cat(card: dict, name: str) -> dict:
    return next(c for c in card["categories"] if c["category"] == name)


_BASE = [
    # Killed pricing claim: WTP survey FAIL 10% against a 30% bar.
    _asm(1, "Users will pay ₹999 monthly", "Pricing"),
    # On-track demand claim: concierge PASS 65% against a 60% bar.
    _asm(2, "Users want this workflow", "Demand"),
    # Untested pricing claim.
    _asm(3, "Churn stays under 5%", "Pricing"),
]
_BASE_EVIDENCE = [
    _ev(
        1,
        id_=1,
        result="FAIL",
        method="WILLINGNESS_TO_PAY_SURVEY",
        observed_metric=0.10,
    ),
    _ev(2, id_=2),
]


# ---------------------------------------------------------------------------
# Grouping and rollups
# ---------------------------------------------------------------------------


def test_categories_ranked_by_risk_score() -> None:
    card = _map(_BASE, _BASE_EVIDENCE)
    assert [c["category"] for c in card["categories"]] == [
        "Pricing",
        "Demand",
    ]
    assert card["riskiest_category"] == "Pricing"


def test_rollups_match_per_assumption_endpoints() -> None:
    card = _map(_BASE, _BASE_EVIDENCE)
    assert card["total_assumptions"] == 3
    assert card["tested_count"] == 2
    assert card["untested_count"] == 1
    assert card["killed_count"] == 1
    assert card["on_track_count"] == 1
    assert card["inconsistent_count"] == 0
    assert card["category_count"] == 2


def test_unbenchmarked_fail_counts_as_killed() -> None:
    card = _map(
        [_asm(1, "Experts approve", "Trust")],
        [_ev(1, id_=1, result="FAIL", method="FOCUS_GROUP", observed_metric=0.2)],
    )
    trust = _cat(card, "Trust")
    assert trust["killed_count"] == 1
    # Killed (1.0) plus the unknown-method row's low-quality evidence
    # (0.3), across a single assumption.
    assert trust["risk_score"] == pytest.approx(1.3)


def test_inconsistent_scores_below_killed() -> None:
    inconsistent_card = _map(
        [_asm(1, "Landing converts", "Demand")],
        [
            _ev(
                1,
                id_=1,
                result="PASS",
                method="LANDING_PAGE_SMOKE_TEST",
                observed_metric=0.01,
            )
        ],
    )
    killed_card = _map(
        [_asm(1, "Users will pay", "Pricing")],
        [
            _ev(
                1,
                id_=1,
                result="FAIL",
                method="WILLINGNESS_TO_PAY_SURVEY",
                observed_metric=0.10,
            )
        ],
    )
    assert (
        _cat(inconsistent_card, "Demand")["inconsistent_count"] == 1
    )
    assert (
        _cat(inconsistent_card, "Demand")["risk_score"]
        < _cat(killed_card, "Pricing")["risk_score"]
    )


def test_risk_score_weights_are_transparent() -> None:
    # Pricing: 1 killed (1.0) + 1 untested (0.5) + the killed row's
    # medium-quality evidence bonus (0.1), across 2 assumptions → 1.6/2.
    card = _map(_BASE, _BASE_EVIDENCE)
    pricing = _cat(card, "Pricing")
    assert pricing["risk_score"] == pytest.approx(0.8)
    # Demand: one high-quality on-track claim → 0.0.
    assert _cat(card, "Demand")["risk_score"] == pytest.approx(0.0)


def test_missing_category_falls_into_general() -> None:
    card = _map([_asm(1, "Mystery claim", None)], [])
    assert card["category_count"] == 1
    general = _cat(card, "General")
    assert general["total_assumptions"] == 1
    assert general["untested_count"] == 1


def test_quality_and_weakest_link_rollups() -> None:
    card = _map(_BASE, _BASE_EVIDENCE)
    pricing = _cat(card, "Pricing")
    assert pricing["mean_quality"] == pytest.approx(0.55)
    assert pricing["quality_label"] == "MEDIUM"
    assert pricing["weakest_assumption_id"] == 1
    assert "₹999" in pricing["weakest_assumption_text"]
    demand = _cat(card, "Demand")
    assert demand["mean_quality"] == pytest.approx(1.0)
    assert demand["quality_label"] == "HIGH"


def test_narrative_names_the_riskiest_area() -> None:
    card = _map(_BASE, _BASE_EVIDENCE)
    assert card["narrative"].startswith(
        "Pricing carries the most validation risk: 1 killed, "
        "0 inconsistent, and 1 untested of 2 assumption(s)."
    )


def test_empty_project() -> None:
    card = _map([], [])
    assert card["category_count"] == 0
    assert card["riskiest_category"] is None
    assert card["categories"] == []
    assert card["narrative"] == "No assumptions to map yet."


def test_meta_pins_model_weights_and_sources() -> None:
    card = _map(_BASE, _BASE_EVIDENCE)
    assert card["meta"]["model"] == "validation_risk_map_v1"
    assert card["meta"]["risk_weights"]["killed"] == 1.0
    assert card["meta"]["risk_weights"]["untested"] == 0.5
    assert card["meta"]["sources"] == [
        "evidence_verdicts_v1",
        "evidence_quality_v1",
    ]


def test_out_schema_validates() -> None:
    card = _map(_BASE, _BASE_EVIDENCE)
    out = ValidationRiskMapOut(**card)
    assert out.categories[0].category == "Pricing"
    assert out.riskiest_category == "Pricing"
    assert out.categories[0].risk_score == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, assumptions, evidence):
        from app.models.assumption import Assumption
        from app.models.assumption_evidence import AssumptionEvidence

        self._by_model = {
            Assumption: assumptions,
            AssumptionEvidence: evidence,
        }

    def query(self, model):
        return _FakeQuery(self._by_model[model])


def test_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/validation-risk-map"
    assert "GET" in methods_by_path.get(path, set())


def test_route_round_trip(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    monkeypatch.setattr(
        ev_mod,
        "get_owned_project",
        lambda db, user_id, project_id: SimpleNamespace(id=project_id),
    )
    db = _FakeDB(assumptions=_BASE, evidence=_BASE_EVIDENCE)
    out = ev_mod.get_validation_risk_map(
        project_id=5, db=db, current_user=SimpleNamespace(id=42)  # type: ignore[arg-type]
    )
    assert isinstance(out, ValidationRiskMapOut)
    assert out.project_id == 5
    assert out.riskiest_category == "Pricing"


def test_route_requires_owned_project(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    monkeypatch.setattr(
        ev_mod,
        "get_owned_project",
        lambda db, user_id, project_id: (_ for _ in ()).throw(
            HTTPException(status_code=404, detail="nope")
        ),
    )
    with pytest.raises(HTTPException) as exc:
        ev_mod.get_validation_risk_map(
            project_id=999,
            db=_FakeDB([], []),  # type: ignore[arg-type]
            current_user=SimpleNamespace(id=42),
        )
    assert exc.value.status_code == 404
