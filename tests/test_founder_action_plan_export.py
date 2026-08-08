"""Tests for the founder-action-plan export helper and route."""
from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

from app.schemas.founder_action_plan import (
    ActionPlanItem,
    ActionPlanSummary,
    FounderActionPlanOut,
)
from app.simulation.founder_action_plan_export import (
    founder_action_plan_to_csv,
    founder_action_plan_to_json,
)


def _payload() -> FounderActionPlanOut:
    return FounderActionPlanOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        product_type="saas",
        headline_conversion=0.031,
        signal_quality=0.62,
        primary_bottleneck="DECIDE",
        summary=ActionPlanSummary(
            total_actions=2,
            total_critical=1,
            total_warning=1,
            quick_win_count=1,
            estimated_total_conversion_impact=0.07,
            verdict="CRITICAL_ISSUES",
        ),
        actions=[
            ActionPlanItem(
                priority=1,
                title="De-risk the final decision",
                summary="Buyers stall at the decision point.",
                domain="PricingArchitect",
                stage="DECIDE",
                metric_affected="will_pay_probability",
                source="DOMAIN_FINDING",
                severity="CRITICAL",
                effort="MEDIUM",
                quick_win_score=0.42,
                estimated_conversion_impact=0.05,
                recommended_action="Simplify pricing",
                related_cluster_ids=["cluster_b", "cluster_c"],
            ),
            ActionPlanItem(
                priority=2,
                title="Cut first-page friction",
                summary="Visitors leave before evaluating.",
                domain="OnboardingArchitect",
                stage="BROWSE",
                metric_affected="onboarding_completion_rate",
                source="FUNNEL_BOTTLENECK",
                severity="WARNING",
                effort="LOW",
                quick_win_score=0.35,
                estimated_conversion_impact=0.02,
                recommended_action="Cut onboarding steps",
                related_cluster_ids=[],
            ),
        ],
        meta={"cac_source": "derived_default"},
    )


def test_csv_renders_summary_and_ranked_actions() -> None:
    csv_text = founder_action_plan_to_csv(
        _payload(),
        metadata={
            "generated_at": "now",
            "user_id": 42,
            "format_version": "1",
            "simulation_id": 1,
            "project_id": 2,
        },
    )

    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "simulation_id,1" in csv_text
    assert "project_id,2" in csv_text
    assert "section,Founder Action Plan Summary" in csv_text
    assert "primary_bottleneck,DECIDE" in csv_text
    assert "verdict,CRITICAL_ISSUES" in csv_text
    assert "section,Ranked Actions" in csv_text
    assert "priority,title,summary,domain,stage" in csv_text
    assert "1,De-risk the final decision" in csv_text
    assert "cluster_b|cluster_c" in csv_text
    assert "section,Meta" in csv_text
    assert "cac_source,derived_default" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = founder_action_plan_to_csv(
        FounderActionPlanOut(simulation_id=0, project_id=0)
    )

    assert "section,Founder Action Plan Summary" in csv_text
    assert "section,Ranked Actions" in csv_text
    assert "priority,title,summary,domain,stage" in csv_text
    assert "total_actions,0" in csv_text
    assert "verdict,INSUFFICIENT_DATA" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = founder_action_plan_to_csv(
        {
            "simulation_id": 7,
            "project_id": 8,
            "status": "COMPLETED",
            "summary": {
                "total_actions": 0,
                "total_critical": 0,
                "total_warning": 0,
                "quick_win_count": 0,
                "estimated_total_conversion_impact": 0.0,
                "verdict": "INSUFFICIENT_DATA",
            },
            "meta": {},
        }
    )

    assert "simulation_id,7" in csv_text
    assert "project_id,8" in csv_text
    assert "verdict,INSUFFICIENT_DATA" in csv_text
    assert "section,Ranked Actions" in csv_text
    assert "section,Meta" not in csv_text


def test_csv_guards_formula_injection() -> None:
    payload = FounderActionPlanOut(
        simulation_id=1,
        project_id=2,
        summary=ActionPlanSummary(verdict="CRITICAL_ISSUES"),
        actions=[
            ActionPlanItem(
                priority=1,
                title="=HYPERLINK(evil)",
                summary="+SUM(1,1)",
                recommended_action="-cmd",
                related_cluster_ids=[],
            )
        ],
    )

    csv_text = founder_action_plan_to_csv(payload)
    assert "'=HYPERLINK(evil)" in csv_text
    assert "'+SUM(1,1)" in csv_text
    assert "'-cmd" in csv_text


def test_csv_tolerates_malformed_summary_actions_and_related_ids() -> None:
    """A non-dict summary or a single-string related_cluster_ids must not crash."""
    csv_text = founder_action_plan_to_csv(
        {
            "simulation_id": 9,
            "project_id": 10,
            "summary": "not-a-dict",
            "actions": [
                ActionPlanItem(
                    priority=1,
                    title="First action",
                    related_cluster_ids=["cluster_a", "cluster_b"],
                ),
                {
                    "priority": 2,
                    "title": "Second action",
                    "related_cluster_ids": "cluster_c",
                },
            ],
            "meta": "also-not-a-dict",
        }
    )

    assert "simulation_id,9" in csv_text
    assert "project_id,10" in csv_text
    assert "verdict," in csv_text
    assert "First action" in csv_text
    assert "Second action" in csv_text
    assert "cluster_a|cluster_b" in csv_text
    assert "cluster_c" in csv_text
    assert "section,Meta" not in csv_text


def test_json_renders_payload_with_metadata() -> None:
    json_text = founder_action_plan_to_json(
        _payload(),
        metadata={"generated_at": "now", "user_id": 42},
    )
    assert '"metadata"' in json_text
    assert '"founder_action_plan"' in json_text
    assert '"verdict"' in json_text
    assert '"primary_bottleneck"' in json_text
    assert '"De-risk the final decision"' in json_text


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def _import_simulations_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import simulations as sim_mod

    return sim_mod


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    simulation_id: int = 1,
    format: str = "csv",
    payload: FounderActionPlanOut | None = None,
):
    sim_mod = _import_simulations_module()
    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        sim_mod,
        "get_founder_action_plan",
        lambda **kwargs: fake_payload,
    )
    return sim_mod.export_founder_action_plan(
        simulation_id=simulation_id,
        format=format,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="founder-action-plan.csv"' in resp.headers["Content-Disposition"]
    assert resp.headers["Cache-Control"] == "no-store"
    body = _body(resp).decode("utf-8")
    assert "section,Founder Action Plan Summary" in body
    assert "verdict,CRITICAL_ISSUES" in body
    assert "section,Ranked Actions" in body
    assert "De-risk the final decision" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="founder-action-plan.json"' in resp.headers["Content-Disposition"]
    assert resp.headers["Cache-Control"] == "no-store"
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"founder_action_plan"' in body
    assert '"verdict"' in body
    assert '"primary_bottleneck"' in body


def test_export_route_rejects_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported format must not pay for the expensive payload build."""
    sim_mod = _import_simulations_module()
    calls: list[object] = []

    def _forbidden_build(**kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError("payload builder should not run for bad format")

    monkeypatch.setattr(sim_mod, "get_founder_action_plan", _forbidden_build)

    with pytest.raises(HTTPException) as exc_info:
        sim_mod.export_founder_action_plan(
            simulation_id=1,
            format="yaml",
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []


def test_export_route_registered() -> None:
    """The founder-action-plan export route is present in the router."""
    sim_mod = _import_simulations_module()
    paths = [r.path for r in sim_mod.router.routes]
    assert "/simulations/{simulation_id}/founder-action-plan/export" in paths
