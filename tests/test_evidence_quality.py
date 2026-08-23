"""Tests for the evidence-quality grader.

Pins the four scoring factors (method reliability, decisiveness, metric
presence, recency), the 60/40 latest-vs-history blend, label cutoffs,
rollups (index, weakest link, untested counting), and route wiring.
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

from app.schemas.evidence_quality import EvidenceQualityOut
from app.simulation.evidence_quality import build_evidence_quality

_NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _asm(id_: int, text: str = "Claim", category: str = "Pricing"):
    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(
    assumption_id: int,
    *,
    id_: int = 1,
    result: str = "PASS",
    method: str = "CONCIERGE_MVP",
    observed_metric: float | None = 0.5,
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


def _quality(assumptions, evidence):
    return build_evidence_quality(
        project_id=5, assumptions=assumptions, evidence=evidence, now=_NOW
    )


def _row_of(quality: dict, assumption_id: int) -> dict:
    return next(
        r for r in quality["rows"] if r["assumption_id"] == assumption_id
    )


# ---------------------------------------------------------------------------
# Scoring factors
# ---------------------------------------------------------------------------


def test_perfect_row_scores_one_high() -> None:
    card = _quality([_asm(1)], [_ev(1)])
    row = _row_of(card, 1)
    assert row["quality"] == pytest.approx(1.0)
    assert row["quality_label"] == "HIGH"
    assert row["reasons"] == []


def test_method_reliability_orders_rows() -> None:
    card = _quality(
        [_asm(1), _asm(2)],
        [
            _ev(1, id_=1, method="PAID_ACQUISITION_TEST"),
            _ev(2, id_=2, method="COMPETITIVE_DESK_RESEARCH"),
        ],
    )
    paid = _row_of(card, 1)["latest_method_reliability"]
    desk = _row_of(card, 2)["latest_method_reliability"]
    assert paid > desk


def test_missing_metric_penalises() -> None:
    with_metric = _quality([_asm(1)], [_ev(1)])
    without = _quality([_asm(2)], [_ev(2, observed_metric=None)])
    q_with = _row_of(with_metric, 1)["quality"]
    q_without = _row_of(without, 2)["quality"]
    assert q_without == pytest.approx(q_with * 0.6)
    assert any("observed_metric" in r for r in _row_of(without, 2)["reasons"])


def test_recency_decays_to_floor() -> None:
    fresh = _quality([_asm(1)], [_ev(1, age_days=3)])
    ancient = _quality([_asm(2)], [_ev(2, age_days=120)])
    assert _row_of(fresh, 1)["quality"] == pytest.approx(1.0)
    assert _row_of(ancient, 2)["quality"] == pytest.approx(0.5)
    assert any("old" in r for r in _row_of(ancient, 2)["reasons"])
    assert _row_of(ancient, 2)["latest_age_days"] == 120


def test_inconclusive_rows_score_low() -> None:
    card = _quality(
        [_asm(1)],
        [
            _ev(
                1,
                result="INCONCLUSIVE",
                method="USER_INTERVIEWS",
                observed_metric=None,
            )
        ],
    )
    row = _row_of(card, 1)
    # 0.50 reliability × 0.30 decisive × 0.60 metric × 1.0 recency
    assert row["quality"] == pytest.approx(0.09)
    assert row["quality_label"] == "LOW"


def test_wtp_survey_is_medium_not_high() -> None:
    """Stated intent must never grade as high-trust evidence."""
    card = _quality(
        [_asm(1)],
        [_ev(1, method="WILLINGNESS_TO_PAY_SURVEY", observed_metric=0.4)],
    )
    row = _row_of(card, 1)
    assert row["quality"] == pytest.approx(0.55)
    assert row["quality_label"] == "MEDIUM"
    assert any("stated intent" in r for r in row["reasons"])


def test_blend_latest_counts_sixty_percent() -> None:
    """Weak history drags even a perfect latest run below 1.0."""
    card = _quality(
        [_asm(1)],
        [
            _ev(
                1,
                id_=1,
                result="FAIL",
                method="COMPETITIVE_DESK_RESEARCH",
                age_days=60,
            ),
            _ev(1, id_=2, result="PASS", age_days=1),
        ],
    )
    row = _row_of(card, 1)
    # older: 0.35 × 1 × 1 × 0.75 = 0.2625; blended: .6·1 + .4·.2625
    assert row["quality"] == pytest.approx(0.6 * 1.0 + 0.4 * 0.2625)
    assert row["evidence_count"] == 2


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------


def test_untested_assumptions_counted_not_graded() -> None:
    card = _quality([_asm(1), _asm(2)], [_ev(1)])
    assert card["total_assumptions"] == 2
    assert card["tested_count"] == 1
    assert card["untested_count"] == 1
    assert len(card["rows"]) == 1


def test_index_and_weakest_link() -> None:
    card = _quality(
        [_asm(1, "Strong claim"), _asm(2, "Flimsy claim")],
        [
            _ev(1, id_=1),
            _ev(
                2,
                id_=2,
                method="COMPETITIVE_DESK_RESEARCH",
                observed_metric=None,
                age_days=120,
            ),
        ],
    )
    strong = _row_of(card, 1)["quality"]
    flimsy = _row_of(card, 2)["quality"]
    assert card["evidence_quality_index"] == pytest.approx((strong + flimsy) / 2)
    assert card["rows"][0]["assumption_id"] == 2  # lowest first
    assert card["weakest_link"]["assumption_id"] == 2
    assert "indirect" in card["weakest_link"]["reason"] or (
        "observed_metric" in card["weakest_link"]["reason"]
    )


def test_empty_project_narrative_and_nulls() -> None:
    card = _quality([], [])
    assert card["total_assumptions"] == 0
    assert card["evidence_quality_index"] is None
    assert card["index_label"] is None
    assert card["weakest_link"] is None
    assert card["narrative"].startswith("No experiments logged yet")


def test_meta_pins_model_and_reliability_table() -> None:
    card = _quality([], [])
    assert card["meta"]["model"] == "evidence_quality_v1"
    assert card["meta"]["method_reliability"]["CONCIERGE_MVP"] > (
        card["meta"]["method_reliability"]["COMPETITIVE_DESK_RESEARCH"]
    )
    assert "60%" in card["meta"]["blend_rule"]


def test_out_schema_validates() -> None:
    card = _quality([_asm(1)], [_ev(1)])
    out = EvidenceQualityOut(**card)
    assert out.rows[0].quality == pytest.approx(1.0)
    assert out.index_label == "HIGH"


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
    path = "/projects/{project_id}/evidence-quality"
    assert "GET" in methods_by_path.get(path, set())


def test_route_round_trip(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    monkeypatch.setattr(
        ev_mod,
        "get_owned_project",
        lambda db, user_id, project_id: SimpleNamespace(id=project_id),
    )
    db = _FakeDB(
        assumptions=[_asm(1)],
        evidence=[_ev(1)],
    )
    out = ev_mod.get_evidence_quality(
        project_id=5, db=db, current_user=SimpleNamespace(id=42)  # type: ignore[arg-type]
    )
    assert isinstance(out, EvidenceQualityOut)
    assert out.project_id == 5
    assert out.tested_count == 1


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
        ev_mod.get_evidence_quality(
            project_id=999,
            db=_FakeDB([], []),  # type: ignore[arg-type]
            current_user=SimpleNamespace(id=42),
        )
    assert exc.value.status_code == 404
