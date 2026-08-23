"""Tests for the assumption recovery planner.

Covers theme classification, playbook rendering from METHOD_SPECS,
audit-first handling of inconsistent records, ordering, counts, the
narrative, and the route wiring.
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

from app.schemas.recovery_plan import RecoveryPlanOut, RecoveryRow
from app.simulation.recovery_planner import (
    _classify_theme,
    build_recovery_plan,
)
from app.simulation.validation_experiment_planner import METHOD_SPECS

_WTP = "WILLINGNESS_TO_PAY_SURVEY"  # bar 0.30
_SMOKE = "LANDING_PAGE_SMOKE_TEST"  # bar 0.03


def _asm(id_: int, text: str, category: str = "Pricing"):
    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(
    assumption_id: int,
    *,
    id_: int = 1,
    result: str = "FAIL",
    method: str = _WTP,
    observed_metric: float | None = 0.10,
):
    return SimpleNamespace(
        assumption_id=assumption_id,
        id=id_,
        result=result,
        method=method,
        observed_metric=observed_metric,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _plan(assumptions, evidence) -> dict:
    return build_recovery_plan(
        project_id=5, assumptions=assumptions, evidence=evidence
    )


# ---------------------------------------------------------------------------
# Theme classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("category", "text", "expected"),
    [
        ("Pricing", "Users pay ₹999", "pricing"),
        ("Demand", "Landing page converts visitors", "demand"),
        ("Trust", "Users trust a new brand", "trust"),
        ("Competition", "Incumbents respond fast", "competition"),
        ("UX", "Onboarding is frictionless", "usability"),
        ("Retention", "Churn stays below 5%", "retention"),
        ("Market", "Something entirely unclassifiable", "general"),
    ],
)
def test_classify_theme(category, text, expected) -> None:
    assert _classify_theme(category, text) == expected


# ---------------------------------------------------------------------------
# Plan content
# ---------------------------------------------------------------------------


def test_killed_pricing_assumption_gets_full_playbook() -> None:
    plan = _plan(
        [_asm(1, "Users will pay ₹999 monthly", "Pricing")],
        [_ev(1, result="FAIL", method=_WTP, observed_metric=0.10)],
    )
    assert plan["attention_count"] == 1
    row = plan["rows"][0]
    assert row["trigger"] == "KILLED"
    assert row["theme"] == "pricing"
    # Full playbook for a straight kill.
    assert len(row["actions"]) == 3
    first = row["actions"][0]
    assert "lower anchor price" in first["title"]
    spec = METHOD_SPECS["WILLINGNESS_TO_PAY_SURVEY"]
    assert first["method_label"] == spec["label"]
    assert first["cost_tier"] == spec["cost_tier"]
    assert (
        first["estimated_duration_days"]
        == spec["estimated_duration_days"]
    )
    assert first["success_threshold"] == spec["success_threshold"]
    assert row["fastest_path_days"] == min(
        a["estimated_duration_days"] for a in row["actions"]
    )
    assert row["cheapest_action_title"]


def test_inconsistent_record_gets_audit_first() -> None:
    plan = _plan(
        [_asm(1, "Landing converts visitors", "Demand")],
        [_ev(1, result="PASS", method=_SMOKE, observed_metric=0.01)],
    )
    row = plan["rows"][0]
    assert row["trigger"] == "INCONSISTENT_PASS"
    audit, retest = row["actions"][0], row["actions"][1]
    assert audit["title"].startswith("Audit")
    assert "1.0%" in audit["rationale"] and "3%" in audit["rationale"]
    assert audit["cost_tier"] == "FREE"
    assert audit["estimated_duration_days"] == 1
    # Exactly one fresh experiment follows the audit.
    assert len(row["actions"]) == 2
    assert retest["method"] == _SMOKE
    assert retest["order"] == 2


def test_rows_killed_before_inconsistent() -> None:
    plan = _plan(
        [_asm(1, "Churn stays low", "Retention"), _asm(2, "Users pay ₹99")],
        [
            _ev(1, id_=1, result="PASS", method=_WTP, observed_metric=0.05),
            _ev(2, id_=2, result="FAIL", method=_WTP, observed_metric=0.02),
        ],
    )
    triggers = [r["trigger"] for r in plan["rows"]]
    assert triggers == ["KILLED", "INCONSISTENT_PASS"]


def test_counts_themes_and_narrative() -> None:
    assumptions = [
        _asm(1, "Users pay ₹999", "Pricing"),
        _asm(2, "Landing converts", "Demand"),
        _asm(3, "Onboarding is easy", "UX"),
        _asm(4, "Healthy signups", "Demand"),
    ]
    evidence = [
        _ev(1, id_=1, result="FAIL", observed_metric=0.05),
        _ev(2, id_=2, result="FAIL", method=_SMOKE, observed_metric=0.005),
        _ev(3, id_=3, result="FAIL", method=_SMOKE, observed_metric=0.01),
        # assumption 4 on track
        _ev(4, id_=4, result="PASS", method=_SMOKE, observed_metric=0.20),
    ]
    plan = _plan(assumptions, evidence)
    assert plan["total_assumptions"] == 4
    assert plan["attention_count"] == 3
    assert plan["killed_count"] == 3
    assert plan["inconsistent_count"] == 0
    # Onboarding kill at exactly the bar is KILLED (metric < bar required);
    # 0.01 < 0.03 so it dies too.
    assert plan["theme_counts"]["pricing"] == 1
    assert plan["theme_counts"]["demand"] >= 1
    assert "need recovery" in plan["narrative"]
    assert "Cheapest first step:" in plan["narrative"]


def test_healthy_project_has_empty_plan() -> None:
    plan = _plan(
        [_asm(1, "Users pay ₹999")],
        [_ev(1, result="PASS", observed_metric=0.55)],
    )
    assert plan["attention_count"] == 0
    assert plan["rows"] == []
    assert plan["theme_counts"] == {}
    assert plan["narrative"].startswith("Nothing needs recovery")


def test_empty_project_plan() -> None:
    plan = _plan([], [])
    assert plan["total_assumptions"] == 0
    assert plan["narrative"].startswith("Nothing needs recovery")


def test_meta_pins_model_and_source() -> None:
    plan = _plan([], [])
    assert plan["meta"]["model"] == "recovery_planner_v1"
    assert plan["meta"]["judgment_source"] == "evidence_verdicts_v1"
    assert "pricing" in plan["meta"]["playbook_themes"]


def test_out_schema_validates_round_trip() -> None:
    plan = _plan(
        [_asm(1, "Users pay ₹999")],
        [_ev(1, result="FAIL", observed_metric=0.05)],
    )
    out = RecoveryPlanOut(**plan)
    assert isinstance(out.rows[0], RecoveryRow)
    assert out.rows[0].actions[0].method == "WILLINGNESS_TO_PAY_SURVEY"


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
    path = "/projects/{project_id}/assumption-recovery-plan"
    assert "GET" in methods_by_path.get(path, set())


def test_route_round_trip(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    monkeypatch.setattr(
        ev_mod,
        "get_owned_project",
        lambda db, user_id, project_id: SimpleNamespace(id=project_id),
    )
    db = _FakeDB(
        assumptions=[_asm(1, "Users pay ₹999")],
        evidence=[_ev(1, result="FAIL", observed_metric=0.05)],
    )
    out = ev_mod.get_assumption_recovery_plan(
        project_id=5, db=db, current_user=SimpleNamespace(id=42)  # type: ignore[arg-type]
    )
    assert isinstance(out, RecoveryPlanOut)
    assert out.project_id == 5
    assert out.attention_count == 1
    assert out.rows[0].actions[0].method == "WILLINGNESS_TO_PAY_SURVEY"


def test_route_requires_owned_project(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    def _deny(db, user_id, project_id):
        raise HTTPException(status_code=404, detail="project not found")

    monkeypatch.setattr(ev_mod, "get_owned_project", _deny)
    with pytest.raises(HTTPException) as exc:
        ev_mod.get_assumption_recovery_plan(
            project_id=999,
            db=_FakeDB([], []),  # type: ignore[arg-type]
            current_user=SimpleNamespace(id=42),
        )
    assert exc.value.status_code == 404
