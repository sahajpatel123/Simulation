"""Tests for the cohort-retention exports (CSV / JSON / Markdown).

The export reuses the exact payload produced by
``GET /simulations/{id}/cohort-retention``; these tests pin the section
layout, formula-injection guarding, non-finite-number handling, strict
JSON envelope, and the founder-facing Markdown brief.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import MagicMock

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.cohort_retention_export import (  # noqa: E402
    FORMAT_VERSION,
    cohort_retention_to_csv,
    cohort_retention_to_json,
    cohort_retention_to_markdown,
)


def _payload(**overrides) -> dict:
    data = {
        "simulation_id": 91,
        "project_id": 12,
        "status": "COMPLETED",
        "overall_conversion": 0.31,
        "total_agents": 10000,
        "total_converted": 3100,
        "market_day30_survival": 0.44,
        "market_day90_survival": 0.29,
        "market_day365_survival": 0.17,
        "highest_churn_stage": "CONSIDER",
        "best_retention_cluster": "metro_power_professional",
        "worst_retention_cluster": "Side | notes",
        "reengagement_viable": True,
        "product_type_detected": "saas",
        "primary_failure_domain": "RetentionArchitect",
        "signal_quality": 0.82,
        "churn_trigger_distribution": {"PRICE": 7, "TRUST": 3},
        "cluster_profiles": [
            {
                "cluster_id": "metro_power_professional",
                "cluster_name": "Metro power professional",
                "population_weight": 0.0412,
                "conversion_rate": 0.52,
                "agents_converted": 214,
                "day30_survival": 0.71,
                "day90_survival": 0.58,
                "churn_risk": "LOW",
                "churn_trigger": "",
                "ltv_score": 8.4,
                "ltv_estimate": 12480.5,
                "reengagement_viable": True,
                "reengagement_prob_30d": 0.33,
                "retention_curve": [
                    {"day": 1, "survival_rate": 0.98, "cumulative_churn": 0.02, "active_users": 406},
                    {"day": 30, "survival_rate": 0.71, "cumulative_churn": 0.29, "active_users": 294},
                ],
            },
            {
                "cluster_id": "tier2_price_sensitive_pragmatist",
                "cluster_name": "Tier-2 pragmatist",
                "population_weight": 0.0389,
                "conversion_rate": -0.05,
                "agents_converted": 41,
                "day30_survival": 0.22,
                "day90_survival": 0.11,
                "churn_risk": "CRITICAL",
                "churn_trigger": "=SUM(A1:A2)",
                "ltv_score": 2.1,
                "ltv_estimate": 990.0,
                "reengagement_viable": False,
                "reengagement_prob_30d": 0.04,
                "retention_curve": [],
            },
        ],
        "segment_summary": [
            {
                "segment": "HIGH_CHURN_RISK",
                "cluster_count": 1,
                "total_population_weight": 0.0389,
                "mean_day30_survival": 0.22,
                "mean_day90_survival": 0.11,
                "mean_ltv_score": 2.1,
                "mean_churn_risk_score": 0.87,
            }
        ],
        "recommendations": ["Anchor onboarding around the first value moment."],
        "meta": {},
    }
    data.update(overrides)
    return data


_METADATA = {
    "generated_at": "2026-08-23T09:15:00+00:00",
    "user_id": 42,
    "simulation_id": 91,
    "format_version": FORMAT_VERSION,
}


def _csv_lines(payload: dict, metadata: dict | None = _METADATA) -> list[str]:
    return cohort_retention_to_csv(payload, metadata=metadata).splitlines()


def test_csv_renders_overview_profiles_curves_and_segments() -> None:
    lines = _csv_lines(_payload())

    assert lines[0] == "generated_at,2026-08-23T09:15:00+00:00"

    overview_at = lines.index("section,Retention Overview")
    assert lines[overview_at + 1] == "key,value"
    assert "overall_conversion,0.31" in lines
    assert "market_day365_survival,0.17" in lines

    triggers_at = lines.index("section,Churn Triggers")
    assert lines[triggers_at + 1] == "trigger,count"
    assert lines[triggers_at + 2] == "PRICE,7"
    assert lines[triggers_at + 3] == "TRUST,3"

    profiles_at = lines.index("section,Cluster Profiles")
    header = lines[profiles_at + 1]
    assert header.startswith("cluster_id,cluster_name,population_weight,")
    # Numbers stay native — negative conversion is NOT apostrophe-guarded.
    assert (
        "tier2_price_sensitive_pragmatist,Tier-2 pragmatist,0.0389,-0.05,41,"
        in lines[profiles_at + 3]
    )

    curves_at = lines.index("section,Retention Curve Points")
    assert lines[curves_at + 1] == "cluster_id,day,survival_rate,cumulative_churn,active_users"
    assert "metro_power_professional,1,0.98,0.02,406" in lines
    assert "metro_power_professional,30,0.71,0.29,294" in lines

    segments_at = lines.index("section,Segment Summary")
    assert lines[segments_at + 2] == "HIGH_CHURN_RISK,1,0.0389,0.22,0.11,2.1,0.87"

    recs_at = lines.index("section,Recommendations")
    assert (
        lines[recs_at + 1]
        == "Anchor onboarding around the first value moment."
    )


def test_csv_guards_formulas_and_blanks_non_finite_numbers() -> None:
    payload = _payload()
    payload["signal_quality"] = float("nan")

    body = cohort_retention_to_csv(payload, metadata=_METADATA)

    assert "'=SUM(A1:A2)" in body
    lines = body.splitlines()
    quality_row = next(line for line in lines if line.startswith("signal_quality,"))
    assert quality_row == "signal_quality,"


def test_csv_handles_empty_payload_sections() -> None:
    lines = _csv_lines(
        _payload(
            cluster_profiles=[],
            segment_summary=[],
            recommendations=[],
            churn_trigger_distribution={},
        ),
        metadata=None,
    )

    assert "section,Churn Triggers" not in lines
    assert "section,Retention Curve Points" not in lines
    assert "section,Segment Summary" not in lines
    assert "section,Recommendations" not in lines
    # Profiles section always renders, even empty.
    profiles_at = lines.index("section,Cluster Profiles")
    assert lines[profiles_at + 2] == ""


def test_json_envelope_is_strict_and_stable() -> None:
    payload = _payload()
    payload["signal_quality"] = float("-inf")

    text = cohort_retention_to_json(payload, metadata=_METADATA)
    assert text.endswith("\n")

    parsed = json.loads(text)
    assert set(parsed) == {"metadata", "cohort_retention"}
    assert parsed["metadata"]["format_version"] == "1"
    envelope = parsed["cohort_retention"]
    assert envelope["best_retention_cluster"] == "metro_power_professional"
    # allow_nan=False would have raised; -inf was replaced by None instead.
    assert envelope["signal_quality"] is None


def test_markdown_brief_renders_headlines_and_tables() -> None:
    body = cohort_retention_to_markdown(_payload(), metadata=_METADATA)

    assert body.startswith("# Cohort Retention")
    assert "*Generated: 2026-08-23*" in body
    assert "T09:15" not in body  # date-only rendering, no time leakage

    assert "| Overall conversion | 31.0% |" in body
    assert "| Day-90 survival | 29.0% |" in body
    assert "| Primary failure domain | RetentionArchitect |" in body

    assert "**Weakest cohort: Side \\| notes**" in body

    assert (
        "| HIGH_CHURN_RISK | 1 | 22.0% | 11.0% | 2.1 |" in body
    )
    assert (
        "| Metro power professional | 52.0% | 71.0% | 58.0% | LOW | 12480.5 | yes |"
        in body
    )
    assert (
        "| Tier-2 pragmatist | -5.0% | 22.0% | 11.0% | CRITICAL | 990.0 | no |"
        in body
    )

    assert "- Anchor onboarding around the first value moment." in body
    assert "*Cohort retention · Simulation 91 · Generated 2026-08-23*" in body


def test_markdown_brief_empty_fallback() -> None:
    body = cohort_retention_to_markdown(
        _payload(cluster_profiles=[], segment_summary=[], recommendations=[]),
        metadata=None,
    )

    assert "_No cluster profiles returned._" in body
    assert "## Segments" not in body
    assert "## Recommendations" not in body


def test_markdown_brief_ranks_churn_triggers_and_tallies_reengagement() -> None:
    body = cohort_retention_to_markdown(_payload())

    triggers_at = body.index("## Churn Triggers")
    segments_at = body.index("## Segments")
    assert triggers_at < segments_at  # trigger table sits before segments
    # Sorted by count descending.
    price_at = body.index("| PRICE | 7 |")
    trust_at = body.index("| TRUST | 3 |")
    assert price_at < trust_at

    # One of the two fixture clusters is re-engagement viable.
    assert "*1 of 2 clusters remain re-engagement viable.*" in body


def test_markdown_brief_skips_reengagement_when_none_viable() -> None:
    payload = _payload()
    for profile in payload["cluster_profiles"]:
        profile["reengagement_viable"] = False

    body = cohort_retention_to_markdown(payload)

    assert "re-engagement viable" not in body


def test_export_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in sim_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/simulations/{simulation_id}/cohort-retention/export"
    assert "GET" in methods_by_path.get(path, set())


def test_route_rejects_unsupported_format() -> None:
    """Bad format fails before the projection (and any DB access) runs."""
    from fastapi import HTTPException

    from app.api.v1 import simulations as sim_mod

    # Any session interaction (even bare attribute access) registers a call
    # on the mock, so post-hoc emptiness proves format validation
    # short-circuits long before the DB layer.
    db_mock = MagicMock()

    with pytest.raises(HTTPException) as exc:
        sim_mod.export_cohort_retention(
            simulation_id=91,
            format="xlsx",
            db=db_mock,
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
    assert db_mock.mock_calls == []


def _call_export_route(format: str):
    """Call the export route with the projection builder stubbed out."""
    from app.api.v1 import simulations as sim_mod

    sent: dict = {}

    def _fake_builder(**kwargs):
        sent.update(kwargs)
        return _payload()

    original = sim_mod.get_cohort_retention
    sim_mod.get_cohort_retention = _fake_builder
    try:
        response = sim_mod.export_cohort_retention(
            simulation_id=91,
            format=format,
            cluster_limit=52,
            db=object(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    finally:
        sim_mod.get_cohort_retention = original

    # The route forwards ownership context and the cluster cap.
    assert sent["simulation_id"] == 91
    assert sent["cluster_limit"] == 52
    return response


async def _drain(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response) -> bytes:
    return asyncio.run(_drain(response))


def test_route_export_json_round_trip() -> None:
    response = _call_export_route("json")

    assert response.media_type == "application/json; charset=utf-8"
    assert 'filename="cohort-retention-91.json"' in (
        response.headers["Content-Disposition"]
    )
    body = _body(response)
    assert int(response.headers["Content-Length"]) == len(body)
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["cohort_retention"]["simulation_id"] == 91
    assert parsed["metadata"]["user_id"] == 42
    assert parsed["metadata"]["format_version"] == "1"


def test_route_export_csv_round_trip() -> None:
    response = _call_export_route("csv")

    assert response.media_type == "text/csv; charset=utf-8"
    assert 'filename="cohort-retention-91.csv"' in (
        response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    text = _body(response).decode("utf-8")
    assert "section,Retention Overview" in text.splitlines()


def test_route_export_md_round_trip() -> None:
    response = _call_export_route("md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert 'filename="cohort-retention-91.md"' in (
        response.headers["Content-Disposition"]
    )
    assert _body(response).decode("utf-8").startswith("# Cohort Retention")
