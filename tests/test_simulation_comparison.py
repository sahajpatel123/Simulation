"""
Tests for simulation comparison helpers
(cycle 28 simulation-comparison).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.schemas.simulation_comparison import SimulationCompareRequest
from app.simulation.comparison import build_simulation_comparison


def _row(
    sim_id: int,
    *,
    cr: float,
    project_id: int = 1,
    status: str = "COMPLETED",
    clusters: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    revenue: float | None = None,
    signal: float | None = 0.7,
    product_type: str = "saas",
    domain: str = "PricingArchitect",
) -> dict[str, Any]:
    return {
        "id": sim_id,
        "project_id": project_id,
        "status": status,
        "signal_quality": signal,
        "created_at": f"2026-07-2{sim_id}T00:00:00+00:00",
        "results_json": {
            "population_weighted_conversion": cr,
            "conversion_rate": cr,
            "revenue_projection": revenue,
            "cluster_breakdown": clusters
            or {
                "metro_power_professional": cr + 0.02,
                "tier2_price_sensitive_pragmatist": max(0.0, cr - 0.01),
            },
            "domain_findings": findings or [],
            "primary_failure_domain": domain,
            "product_type_detected": product_type,
        },
    }


def test_requires_at_least_two_simulations() -> None:
    with pytest.raises(ValueError, match="At least 2"):
        build_simulation_comparison([_row(1, cr=0.05)])


def test_rejects_more_than_five() -> None:
    rows = [_row(i, cr=0.04 + i * 0.001) for i in range(1, 7)]
    with pytest.raises(ValueError, match="At most 5"):
        build_simulation_comparison(rows)


def test_clear_winner_verdict_and_labels() -> None:
    out = build_simulation_comparison(
        [
            _row(10, cr=0.03, revenue=3000),
            _row(11, cr=0.08, revenue=8000),
        ]
    )
    assert out.project_id == 1
    assert out.summary.best_simulation_id == 11
    assert out.summary.worst_simulation_id == 10
    assert out.summary.winner_label == "B"
    assert out.summary.verdict == "CLEAR_WINNER"
    assert out.summary.conversion_spread_pct > 20
    assert out.summary.revenue_spread_pct is not None
    assert len(out.simulations) == 2
    assert out.simulations[0].simulation_id == 10


def test_close_race_verdict() -> None:
    out = build_simulation_comparison(
        [
            _row(1, cr=0.050),
            _row(2, cr=0.052),
        ]
    )
    assert out.summary.verdict == "CLOSE_RACE"


def test_mixed_by_cluster_when_winners_diverge() -> None:
    out = build_simulation_comparison(
        [
            _row(
                1,
                cr=0.05,
                clusters={"a": 0.10, "b": 0.02},
            ),
            _row(
                2,
                cr=0.055,
                clusters={"a": 0.03, "b": 0.09},
            ),
        ],
        cluster_registry={
            "a": {"name": "A", "population_weight": 0.5},
            "b": {"name": "B", "population_weight": 0.5},
        },
    )
    assert out.summary.verdict == "MIXED_BY_CLUSTER"
    by_cid = {r.cluster_id: r for r in out.cluster_comparison}
    assert by_cid["a"].best_simulation_id == 1
    assert by_cid["b"].best_simulation_id == 2
    assert by_cid["a"].winner_label == "A"
    assert by_cid["b"].winner_label == "B"


def test_cluster_dict_payloads_and_deltas() -> None:
    out = build_simulation_comparison(
        [
            _row(
                1,
                cr=0.04,
                clusters={
                    "metro": {"conversion_rate": 0.06, "name": "Metro"},
                    "tier2": {"conversion_rate": 0.02},
                },
            ),
            _row(
                2,
                cr=0.06,
                clusters={
                    "metro": {"conversion_rate": 0.09},
                    "tier2": {"conversion_rate": 0.03},
                },
            ),
        ],
        cluster_registry={
            "metro": {"name": "Metro Pros", "population_weight": 0.4},
            "tier2": {"name": "Tier-2", "population_weight": 0.6},
        },
    )
    metro = next(r for r in out.cluster_comparison if r.cluster_id == "metro")
    assert metro.cluster_name == "Metro Pros"
    assert metro.conversions[2] == 0.09
    assert metro.delta_from_best[1] == pytest.approx(-0.03, abs=1e-4)
    assert metro.best_simulation_id == 2
    # Sorted by population weight desc → tier2 first.
    assert out.cluster_comparison[0].cluster_id == "tier2"


def test_domain_consensus_all_agree() -> None:
    finding = {
        "architect_name": "PricingArchitect",
        "severity": "CRITICAL",
        "finding": "price too high",
    }
    out = build_simulation_comparison(
        [
            _row(1, cr=0.03, findings=[finding]),
            _row(2, cr=0.04, findings=[dict(finding)]),
        ]
    )
    assert len(out.domain_finding_comparison) == 1
    row = out.domain_finding_comparison[0]
    assert row.domain == "PricingArchitect"
    assert row.consensus == "ALL_AGREE"
    assert "Prioritize" in row.recommendation


def test_domain_consensus_single_sim_only() -> None:
    out = build_simulation_comparison(
        [
            _row(
                1,
                cr=0.03,
                findings=[
                    {
                        "architect_name": "TrustArchitect",
                        "severity": "WARNING",
                    }
                ],
            ),
            _row(2, cr=0.04, findings=[]),
        ]
    )
    row = out.domain_finding_comparison[0]
    assert row.consensus == "SINGLE_SIM_ONLY"
    assert row.severity_by_sim[2] is None
    assert "Only simulation 1" in row.recommendation


def test_domain_consensus_mixed() -> None:
    out = build_simulation_comparison(
        [
            _row(
                1,
                cr=0.03,
                findings=[
                    {"architect_name": "OnboardingArchitect", "severity": "CRITICAL"}
                ],
            ),
            _row(
                2,
                cr=0.04,
                findings=[
                    {"architect_name": "OnboardingArchitect", "severity": "INFO"}
                ],
            ),
        ]
    )
    row = out.domain_finding_comparison[0]
    assert row.consensus == "MIXED"
    assert "CRITICAL" in row.recommendation


def test_json_string_results_and_incomplete_verdict() -> None:
    import json

    row_a = _row(1, cr=0.05)
    row_b = _row(2, cr=0.04, status="RUNNING")
    row_a["results_json"] = json.dumps(row_a["results_json"])
    out = build_simulation_comparison([row_a, row_b])
    # Only one COMPLETED → PARTIAL_COMPLETION when mixed statuses with at
    # least one completed.
    assert out.summary.verdict == "PARTIAL_COMPLETION"
    assert out.summary.best_simulation_id == 1


def test_incomplete_data_when_none_completed() -> None:
    out = build_simulation_comparison(
        [
            _row(1, cr=0.05, status="FAILED"),
            _row(2, cr=0.02, status="RUNNING"),
        ]
    )
    assert out.summary.verdict == "INCOMPLETE_DATA"


def test_request_schema_rejects_duplicates() -> None:
    with pytest.raises(Exception):
        SimulationCompareRequest(simulation_ids=[1, 1])


def test_request_schema_accepts_valid_range() -> None:
    req = SimulationCompareRequest(simulation_ids=[3, 7, 9])
    assert req.simulation_ids == [3, 7, 9]


def test_metadata_and_schema_round_trip() -> None:
    out = build_simulation_comparison(
        [
            _row(1, cr=0.03, product_type="saas", domain="PricingArchitect"),
            _row(2, cr=0.06, product_type="saas", domain="TrustArchitect"),
        ]
    )
    dumped = out.model_dump()
    assert dumped["metadata"]["total_simulations_compared"] == 2
    assert dumped["metadata"]["completed_count"] == 2
    assert "PricingArchitect" in dumped["metadata"]["primary_failure_domains"]
    assert dumped["comparison_id"]
    assert dumped["generated_at"]
