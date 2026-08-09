"""Tests for the pure investor-readiness digest builder."""
from __future__ import annotations

from typing import Any

from app.schemas.investor_readiness import InvestorReadinessOut
from app.schemas.unit_economics import UnitEconomicsOut
from app.simulation.investor_readiness import build_investor_readiness


def _strong_market() -> dict[str, Any]:
    return {
        "annual_revenue": 1_500_000.0,
        "tam_customers": 10_000_000,
        "sam_customers": 2_500_000,
        "som_customers": 25_000,
        "average_order_value": 100.0,
    }


def _strong_economics() -> dict[str, Any]:
    return {
        "blended_ltv_cac_ratio": 3.8,
        "blended_payback_months": 12.0,
        "verdict": "STRONG",
    }


def _strong_retention() -> dict[str, Any]:
    return {
        "weighted_day30_survival": 0.35,
        "weighted_day90_survival": 0.18,
        "highest_churn_stage": "day30",
        "verdict": "STRONG",
    }


def _strong_moat() -> dict[str, Any]:
    return {
        "moat_index": 0.68,
        "primary_weakest_lever_label": "Brand trust",
        "verdict": "STRONG",
    }


def _strong_readiness() -> dict[str, Any]:
    return {
        "readiness_score": 0.88,
        "verdict": "READY",
        "recommendations": ["Run a pilot before raising"],
    }


def _strong_quality() -> dict[str, Any]:
    return {
        "trust_score": 0.92,
        "verdict": "PASS",
        "recommendations": [],
    }


def _weak_pillars() -> dict[str, Any]:
    return {
        "market": {
            "annual_revenue": 10_000.0,
            "tam_customers": 100_000,
            "sam_customers": 25_000,
            "som_customers": 100,
            "average_order_value": 50.0,
        },
        "economics": {
            "blended_ltv_cac_ratio": 0.4,
            "blended_payback_months": 48.0,
            "verdict": "UNPROFITABLE",
        },
        "retention": {
            "weighted_day30_survival": 0.03,
            "weighted_day90_survival": 0.01,
            "highest_churn_stage": "day30",
            "verdict": "HIGH_CHURN",
        },
        "moat": {
            "moat_index": 0.15,
            "primary_weakest_lever_label": "Feature parity",
            "verdict": "WEAK",
        },
        "readiness": {
            "readiness_score": 0.20,
            "verdict": "NOT_READY",
            "recommendations": ["Re-run with complete assumptions"],
        },
        "quality": {
            "trust_score": 0.10,
            "verdict": "FAIL",
            "recommendations": [],
        },
    }


def _build(
    *,
    market: Any | None = None,
    economics: Any | None = None,
    retention: Any | None = None,
    moat: Any | None = None,
    readiness: Any | None = None,
    quality: Any | None = None,
    findings: list[Any] | None = None,
    signal_quality: float | None = 0.85,
) -> InvestorReadinessOut:
    return build_investor_readiness(
        {"population_weighted_conversion": 0.04},
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        signal_quality=signal_quality,
        product_type="saas",
        market=market,
        economics=economics,
        retention=retention,
        moat=moat,
        readiness=readiness,
        quality=quality,
        domain_findings=findings,
    )


def test_strong_signals_score_investment_grade() -> None:
    out = _build(
        market=_strong_market(),
        economics=_strong_economics(),
        retention=_strong_retention(),
        moat=_strong_moat(),
        readiness=_strong_readiness(),
        quality=_strong_quality(),
    )

    assert out.investor_score is not None
    assert out.investor_score >= 80
    assert out.verdict == "INVESTMENT_GRADE"
    assert out.verdict_label == "Venture-grade signals"
    assert len(out.pillars) == 6
    assert all(p.score is not None for p in out.pillars)
    assert out.strengths
    assert all("(100/100)" in s or "/100)" in s for s in out.strengths)
    assert out.top_actions
    assert out.meta["available_pillars"] == 6
    assert out.meta["headline_conversion"] == 0.04


def test_weak_signals_score_not_investable() -> None:
    weak = _weak_pillars()
    out = _build(
        market=weak["market"],
        economics=weak["economics"],
        retention=weak["retention"],
        moat=weak["moat"],
        readiness=weak["readiness"],
        quality=weak["quality"],
    )

    assert out.investor_score is not None
    assert out.investor_score < 40
    assert out.verdict == "NOT_INVESTABLE"
    assert out.risks
    assert any("Retention" in risk for risk in out.risks)
    assert len(out.risks) <= 5


def test_fewer_than_three_pillars_is_insufficient() -> None:
    out = _build(
        market=_strong_market(),
        economics=_strong_economics(),
    )

    assert out.investor_score is None
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.meta["available_pillars"] == 2
    assert "cannot be scored" in out.narrative


def test_missing_pillar_payloads_are_insufficient() -> None:
    out = _build(
        market=None,
        economics=None,
        retention=None,
        moat=None,
        readiness=_strong_readiness(),
        quality=_strong_quality(),
    )

    assert out.investor_score is None
    assert out.verdict == "INSUFFICIENT_DATA"
    insufficient = [p for p in out.pillars if p.verdict == "INSUFFICIENT_DATA"]
    assert len(insufficient) == 4


def test_critical_findings_surface_in_risks() -> None:
    findings = [
        {"severity": "CRITICAL", "title": "Support burden"},
        {"severity": "MAJOR", "title": "Pricing confusion"},
        {"severity": "MINOR", "title": "Copy tweak"},
    ]
    weak = _weak_pillars()
    out = _build(
        market=weak["market"],
        economics=weak["economics"],
        retention=weak["retention"],
        moat=weak["moat"],
        readiness=weak["readiness"],
        quality=weak["quality"],
        findings=findings,
    )

    assert any("Support burden" in risk for risk in out.risks)
    assert any("Pricing confusion" in risk for risk in out.risks)
    assert not any("Copy tweak" in risk for risk in out.risks)


def test_pydantic_pillar_models_are_accepted() -> None:
    economics = UnitEconomicsOut(
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        blended_ltv_cac_ratio=3.8,
        blended_payback_months=12.0,
        verdict="STRONG",
    )
    out = _build(
        market=_strong_market(),
        economics=economics,
        retention=_strong_retention(),
        moat=_strong_moat(),
        readiness=_strong_readiness(),
        quality=_strong_quality(),
    )

    economics_pillar = next(p for p in out.pillars if p.key == "economics")
    assert economics_pillar.score == 100
    assert economics_pillar.verdict == "STRONG"


def test_non_finite_signal_quality_is_sanitised() -> None:
    out = _build(
        market=_strong_market(),
        economics=_strong_economics(),
        retention=_strong_retention(),
        moat=_strong_moat(),
        readiness=_strong_readiness(),
        quality=_strong_quality(),
        signal_quality=float("nan"),
    )

    assert out.signal_quality is None


def test_no_findings_means_no_finding_risks() -> None:
    weak = _weak_pillars()
    out = _build(
        market=weak["market"],
        economics=weak["economics"],
        retention=weak["retention"],
        moat=weak["moat"],
        readiness=weak["readiness"],
        quality=weak["quality"],
        findings=[],
    )

    assert not any(risk.startswith("Finding:") for risk in out.risks)
