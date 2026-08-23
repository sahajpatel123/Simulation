"""Tests for the per-assumption evidence-verdict scorecard.

Covers the ``_judge`` decision table (ON_TRACK / KILLED / INCONSISTENT_* /
NO_METRIC / UNBENCHMARKED_*), latest-decisive-row selection, attention
ordering, the count rollups (UNBENCHMARKED_* fold into on-track / killed),
the next-action priority chain, and the route wiring.
"""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from fastapi import HTTPException

from app.schemas.evidence_verdicts import (
    EvidenceVerdictRow,
    EvidenceVerdictsOut,
)
from app.simulation.evidence_verdicts import (
    METHOD_THRESHOLDS,
    build_evidence_verdicts,
)

_WTP = "WILLINGNESS_TO_PAY_SURVEY"  # canonical bar: 0.30


def _asm(id_: int, text: str = "Claim", category: str = "PRICING"):
    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(
    assumption_id: int,
    *,
    id_: int = 1,
    result: str = "PASS",
    method: str = _WTP,
    observed_metric: float | None = 0.42,
    created_at: datetime | None = None,
):
    return SimpleNamespace(
        assumption_id=assumption_id,
        id=id_,
        result=result,
        method=method,
        observed_metric=observed_metric,
        created_at=created_at or datetime(2026, 8, 1, tzinfo=UTC),
    )


def _scorecard(assumptions, evidence) -> dict:
    return build_evidence_verdicts(
        project_id=5, assumptions=assumptions, evidence=evidence
    )


def _row_of(scorecard: dict, assumption_id: int) -> dict:
    return next(
        r for r in scorecard["rows"] if r["assumption_id"] == assumption_id
    )


# ---------------------------------------------------------------------------
# _judge decision table
# ---------------------------------------------------------------------------


def test_pass_exactly_at_bar_is_on_track() -> None:
    card = _scorecard([_asm(1)], [_ev(1, result="PASS", observed_metric=0.30)])
    row = _row_of(card, 1)
    assert row["verdict"] == "ON_TRACK"
    assert row["threshold"] == 0.30
    assert row["margin_pp"] == 0.0
    assert "30.0%" in row["explanation"]


def test_pass_above_bar_margin_math() -> None:
    card = _scorecard([_asm(1)], [_ev(1, result="PASS", observed_metric=0.35)])
    row = _row_of(card, 1)
    assert row["verdict"] == "ON_TRACK"
    assert row["margin_pp"] == pytest.approx(5.0)
    assert "+5.00pp" in row["explanation"]


def test_fail_below_bar_is_killed() -> None:
    card = _scorecard([_asm(1)], [_ev(1, result="FAIL", observed_metric=0.12)])
    row = _row_of(card, 1)
    assert row["verdict"] == "KILLED"
    assert row["margin_pp"] == pytest.approx(-18.0)


def test_pass_below_bar_is_inconsistent() -> None:
    card = _scorecard([_asm(1)], [_ev(1, result="PASS", observed_metric=0.20)])
    row = _row_of(card, 1)
    assert row["verdict"] == "INCONSISTENT_PASS"
    assert row["margin_pp"] == pytest.approx(-10.0)
    assert "re-check the call" in row["explanation"]


def test_fail_above_bar_is_inconsistent() -> None:
    card = _scorecard([_asm(1)], [_ev(1, result="FAIL", observed_metric=0.55)])
    row = _row_of(card, 1)
    assert row["verdict"] == "INCONSISTENT_FAIL"
    assert row["margin_pp"] == pytest.approx(25.0)
    assert "re-check the call" in row["explanation"]


def test_benchmarked_method_without_metric() -> None:
    card = _scorecard(
        [_asm(1)], [_ev(1, result="PASS", observed_metric=None)]
    )
    row = _row_of(card, 1)
    assert row["verdict"] == "NO_METRIC"
    assert row["threshold"] == 0.30
    assert row["margin_pp"] is None
    assert row["latest_result"] == "PASS"
    assert "cannot be checked" in row["explanation"]


def test_unbenchmarked_methods_stand_alone() -> None:
    card = _scorecard(
        [_asm(1), _asm(2)],
        [
            _ev(1, result="PASS", method="FOCUS_GROUP"),
            _ev(2, result="FAIL", method="FOCUS_GROUP"),
        ],
    )
    assert _row_of(card, 1)["verdict"] == "UNBENCHMARKED_PASS"
    assert _row_of(card, 2)["verdict"] == "UNBENCHMARKED_FAIL"
    for aid in (1, 2):
        row = _row_of(card, aid)
        assert row["threshold"] is None
        assert row["margin_pp"] is None
        assert "founder judgment stands" in row["explanation"]


# ---------------------------------------------------------------------------
# History selection
# ---------------------------------------------------------------------------


def test_latest_decisive_row_wins_over_older() -> None:
    card = _scorecard(
        [_asm(1)],
        [
            _ev(1, id_=1, result="PASS", observed_metric=0.90),
            _ev(1, id_=2, result="FAIL", observed_metric=0.10),
        ],
    )
    row = _row_of(card, 1)
    assert row["verdict"] == "KILLED"
    assert row["latest_result"] == "FAIL"
    assert row["evidence_count"] == 2


def test_inconclusive_only_history() -> None:
    card = _scorecard(
        [_asm(1)],
        [_ev(1, result="INCONCLUSIVE", observed_metric=None)],
    )
    row = _row_of(card, 1)
    assert row["verdict"] == "INCONCLUSIVE"
    assert row["latest_result"] == "INCONCLUSIVE"
    assert "decisive" in row["explanation"]


def test_inconclusive_latest_fields_use_newest_row() -> None:
    """latest_* must follow (id, created_at) order, not append order."""
    card = _scorecard(
        [_asm(1)],
        [
            _ev(
                1,
                id_=7,
                result="INCONCLUSIVE",
                method="USER_INTERVIEWS",
                observed_metric=None,
            ),
            _ev(
                1,
                id_=3,
                result="INCONCLUSIVE",
                method="CONCIERGE_MVP",
                observed_metric=None,
            ),
        ],
    )
    row = _row_of(card, 1)
    assert row["evidence_count"] == 2
    assert row["latest_method"] == "USER_INTERVIEWS"
    assert row["method_label"] == "User interviews"


def test_pending_without_evidence() -> None:
    card = _scorecard([_asm(1)], [])
    row = _row_of(card, 1)
    assert row["verdict"] == "PENDING"
    assert row["evidence_count"] == 0
    assert "No experiments logged yet." == row["explanation"]


# ---------------------------------------------------------------------------
# Counts, ordering, next action, meta
# ---------------------------------------------------------------------------


def test_attention_ordering_and_counts() -> None:
    assumptions = [_asm(i) for i in range(1, 6)]
    evidence = [
        _ev(1, id_=1, result="FAIL", observed_metric=0.10),  # KILLED
        _ev(2, id_=2, result="PASS", observed_metric=0.10),  # INCONSISTENT
        _ev(3, id_=3, result="PASS", observed_metric=0.50),  # ON_TRACK
        _ev(4, id_=4, result="PASS", observed_metric=None),  # NO_METRIC
        # assumption 5: no evidence → PENDING
    ]
    card = _scorecard(assumptions, evidence)
    verdicts = [r["verdict"] for r in card["rows"]]
    assert verdicts == [
        "INCONSISTENT_PASS",
        "KILLED",
        "ON_TRACK",
        "NO_METRIC",
        "PENDING",
    ]
    assert card["total_assumptions"] == 5
    assert card["judged_count"] == 3
    assert card["on_track_count"] == 1
    assert card["killed_count"] == 1
    assert card["inconsistent_count"] == 1
    assert card["unjudged_count"] == 2


def test_unbenchmarked_results_roll_into_counts() -> None:
    card = _scorecard(
        [_asm(1), _asm(2)],
        [
            _ev(1, result="PASS", method="FOCUS_GROUP"),
            _ev(2, result="FAIL", method="FOCUS_GROUP"),
        ],
    )
    assert card["on_track_count"] == 1
    assert card["killed_count"] == 1
    assert card["judged_count"] == 2
    assert card["unjudged_count"] == 0


def test_next_action_prioritizes_inconsistencies() -> None:
    evidence = [
        _ev(1, id_=1, result="FAIL", observed_metric=0.10),  # KILLED
        _ev(2, id_=2, result="PASS", observed_metric=0.05),  # INCONSISTENT
    ]
    card = _scorecard([_asm(1), _asm(2)], evidence)
    assert "re-check those calls first" in card["next_action"]


def test_next_action_kill_bar_message() -> None:
    card = _scorecard(
        [_asm(1)], [_ev(1, result="FAIL", observed_metric=0.05)]
    )
    assert "hit a kill bar" in card["next_action"]


def test_next_action_all_on_track_vs_mixed() -> None:
    only_pass = _scorecard(
        [_asm(1)], [_ev(1, result="PASS", observed_metric=0.60)]
    )
    assert only_pass["next_action"] == "All 1 judged assumption(s) are on track."

    mixed = _scorecard(
        [_asm(1), _asm(2)],
        [_ev(1, result="PASS", observed_metric=0.60)],
    )
    assert "keep testing the 1 still unjudged" in mixed["next_action"]


def test_empty_project_next_action() -> None:
    card = _scorecard([], [])
    assert card["total_assumptions"] == 0
    assert card["rows"] == []
    assert card["next_action"].startswith("Import or create assumptions")


def test_meta_block_pins_model_and_thresholds() -> None:
    card = _scorecard([_asm(1)], [_ev(1)])
    assert card["meta"]["model"] == "evidence_verdicts_v1"
    assert card["meta"]["thresholds"][_WTP] == pytest.approx(0.30)
    assert "latest decisive" in card["meta"]["judgment_rule"]
    assert METHOD_THRESHOLDS["LANDING_PAGE_SMOKE_TEST"] == pytest.approx(0.03)


def test_row_schema_validates() -> None:
    card = _scorecard(
        [_asm(1)], [_ev(1, result="PASS", observed_metric=0.35)]
    )
    row = EvidenceVerdictRow.model_validate(card["rows"][0])
    assert row.verdict == "ON_TRACK"


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def test_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    hits = {
        path
        for path in methods_by_path
        if path.endswith("/evidence-verdicts")
    }
    assert hits, "evidence-verdicts route not registered"
    for path in hits:
        assert "GET" in methods_by_path[path]


class _FakeQuery:
    def __init__(self, rows: list):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self) -> list:
        return self._rows


class _FakeDB:
    def __init__(self, assumptions: list, evidence: list):
        from app.models.assumption import Assumption
        from app.models.assumption_evidence import AssumptionEvidence

        self._by_model = {
            Assumption: assumptions,
            AssumptionEvidence: evidence,
        }

    def query(self, model):
        return _FakeQuery(self._by_model[model])


def test_route_round_trip(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    monkeypatch.setattr(
        ev_mod,
        "get_owned_project",
        lambda db, user_id, project_id: SimpleNamespace(id=project_id),
    )
    db = _FakeDB(
        assumptions=[_asm(1), _asm(2)],
        evidence=[
            _ev(1, id_=1, result="PASS", observed_metric=0.35),
            _ev(2, id_=2, result="FAIL", observed_metric=0.10),
        ],
    )
    user = SimpleNamespace(id=42)

    out = ev_mod.get_evidence_verdicts(
        project_id=5, db=db, current_user=user  # type: ignore[arg-type]
    )
    assert isinstance(out, EvidenceVerdictsOut)
    assert out.project_id == 5
    assert out.total_assumptions == 2
    assert out.judged_count == 2
    # Attention order: the kill lands first.
    assert out.rows[0].verdict == "KILLED"
    assert all(isinstance(r, EvidenceVerdictRow) for r in out.rows)


def test_route_requires_owned_project(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    def _deny(db, user_id, project_id):
        raise HTTPException(status_code=404, detail="project not found")

    monkeypatch.setattr(ev_mod, "get_owned_project", _deny)
    db = _FakeDB(assumptions=[], evidence=[])
    with pytest.raises(HTTPException) as exc:
        ev_mod.get_evidence_verdicts(
            project_id=999,
            db=db,  # type: ignore[arg-type]
            current_user=SimpleNamespace(id=42),
        )
    assert exc.value.status_code == 404
