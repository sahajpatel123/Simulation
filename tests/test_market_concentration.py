"""
Tests for demand-concentration helpers
(``app.simulation.market_concentration``).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.schemas.market_concentration import MarketConcentrationOut
from app.simulation.market_concentration import (
    FLAG_HIGH_CONCENTRATION,
    FLAG_SINGLE_SEGMENT,
    FLAG_TOP_HEAVY,
    VERDICT_CONCENTRATED,
    VERDICT_DIVERSIFIED,
    VERDICT_INSUFFICIENT,
    VERDICT_MODERATE,
    build_market_concentration,
)


def _uniform_registry(n: int = 52) -> dict[str, dict[str, Any]]:
    return {
        f"c{i}": {
            "name": f"Cluster {i}",
            "population_weight": 1.0 / n,
        }
        for i in range(1, n + 1)
    }


def _results(
    breakdown: dict[str, Any] | None = None,
    *,
    cr: float = 0.05,
    n: int = 52,
) -> dict[str, Any]:
    if breakdown is None:
        breakdown = {f"c{i}": cr for i in range(1, n + 1)}
    return {
        "population_weighted_conversion": cr,
        "cluster_breakdown": breakdown,
    }


def test_empty_results_yield_zero_state() -> None:
    out = build_market_concentration(None, simulation_id=1, project_id=2)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.hhi == 0.0
    assert out.normalized_hhi == 0.0
    assert out.effective_segments == 0.0
    assert out.segment_shares == []
    assert out.clusters_with_demand == 0
    assert out.recommendations


def test_garbage_and_empty_payloads_yield_zero_state() -> None:
    bad = build_market_concentration(
        "{nope", simulation_id=1, project_id=1
    )
    assert bad.verdict == VERDICT_INSUFFICIENT

    empty = build_market_concentration(
        {"cluster_breakdown": {}}, simulation_id=1, project_id=1
    )
    assert empty.verdict == VERDICT_INSUFFICIENT
    assert empty.total_clusters == 0

    all_zero = build_market_concentration(
        _results({f"c{i}": 0.0 for i in range(1, 5)}),
        simulation_id=1,
        project_id=1,
    )
    assert all_zero.verdict == VERDICT_INSUFFICIENT
    assert all_zero.total_clusters == 4


def test_json_string_input_parses() -> None:
    out = build_market_concentration(
        json.dumps(_results(n=4, cr=0.08)),
        simulation_id=1,
        project_id=1,
    )
    assert out.clusters_with_demand == 4
    assert out.total_clusters == 4


def test_dict_cluster_breakdown_payloads_parse() -> None:
    breakdown = {
        "c1": {"conversion_rate": 0.10, "weight": 1.0},
        "c2": {"conversion": 0.10, "weight": 1.0},
        "c3": 0.10,
    }
    out = build_market_concentration(
        _results(breakdown, n=3),
        simulation_id=1,
        project_id=1,
        cluster_registry=_uniform_registry(3),
    )
    assert out.clusters_with_demand == 3
    assert out.total_clusters == 3
    for item in out.segment_shares:
        assert item.demand_share == pytest.approx(1 / 3, abs=0.001)


def test_uniform_52_cluster_demand_is_diversified() -> None:
    out = build_market_concentration(
        _results(n=52, cr=0.04),
        simulation_id=1,
        project_id=1,
        cluster_registry=_uniform_registry(52),
    )
    assert out.verdict == VERDICT_DIVERSIFIED
    assert out.hhi == pytest.approx(1 / 52, abs=0.0001)
    assert out.normalized_hhi == 0.0
    assert out.effective_segments == pytest.approx(52.0, abs=0.01)
    assert out.top_1_share == pytest.approx(1 / 52, abs=0.001)
    assert out.fragility_flags == []
    assert out.recommendations
    assert out.top_cluster_id is not None


def test_small_uniform_markets_do_not_false_flag() -> None:
    for n in (3, 4, 5):
        out = build_market_concentration(
            _results(n=n, cr=0.06),
            simulation_id=1,
            project_id=1,
            cluster_registry=_uniform_registry(n),
        )
        assert out.verdict == VERDICT_DIVERSIFIED, f"n={n}"
        assert out.fragility_flags == [], f"n={n}"


def test_single_segment_monopoly_is_maximally_concentrated() -> None:
    out = build_market_concentration(
        _results({"c1": 0.05}, n=1),
        simulation_id=1,
        project_id=1,
        cluster_registry=_uniform_registry(1),
    )
    assert out.verdict == VERDICT_CONCENTRATED
    assert out.hhi == pytest.approx(1.0, abs=0.0001)
    assert out.normalized_hhi == pytest.approx(1.0, abs=0.0001)
    assert out.effective_segments == pytest.approx(1.0, abs=0.01)
    assert out.top_1_share == pytest.approx(1.0, abs=0.0001)
    assert out.top_cluster_id == "c1"
    assert out.top_cluster_name == "Cluster 1"
    assert out.clusters_with_demand == 1
    assert FLAG_SINGLE_SEGMENT in out.fragility_flags
    assert FLAG_HIGH_CONCENTRATION in out.fragility_flags
    assert any("diversif" in r.lower() for r in out.recommendations)


def test_zero_conversion_siblings_do_not_dilute_monopoly() -> None:
    out = build_market_concentration(
        _results({"c1": 0.06, "c2": 0.0, "c3": 0.0}, n=3),
        simulation_id=1,
        project_id=1,
        cluster_registry=_uniform_registry(3),
    )
    assert out.total_clusters == 3
    assert out.clusters_with_demand == 1
    assert out.verdict == VERDICT_CONCENTRATED
    assert out.hhi == pytest.approx(1.0, abs=0.0001)
    assert out.normalized_hhi == pytest.approx(1.0, abs=0.0001)
    assert FLAG_SINGLE_SEGMENT in out.fragility_flags
    assert FLAG_HIGH_CONCENTRATION in out.fragility_flags


def test_dominant_segment_is_concentrated() -> None:
    registry = _uniform_registry(52)
    breakdown = {"c1": 0.50}
    for i in range(2, 53):
        breakdown[f"c{i}"] = 0.005
    out = build_market_concentration(
        _results(breakdown, n=52),
        simulation_id=1,
        project_id=1,
        cluster_registry=registry,
    )
    assert out.verdict == VERDICT_CONCENTRATED
    assert out.top_cluster_id == "c1"
    assert out.top_cluster_name == "Cluster 1"
    assert out.top_1_share > 0.60
    assert FLAG_SINGLE_SEGMENT in out.fragility_flags
    assert FLAG_TOP_HEAVY in out.fragility_flags
    assert FLAG_HIGH_CONCENTRATION in out.fragility_flags
    assert out.normalized_hhi >= 0.30
    assert out.effective_segments < 3.0
    assert any("diversif" in r.lower() for r in out.recommendations)


def test_moderate_concentration_verdict() -> None:
    registry = _uniform_registry(10)
    breakdown = {"c1": 0.60}
    for i in range(2, 11):
        breakdown[f"c{i}"] = 0.10
    out = build_market_concentration(
        _results(breakdown, n=10),
        simulation_id=1,
        project_id=1,
        cluster_registry=registry,
    )
    assert out.verdict == VERDICT_MODERATE
    assert FLAG_SINGLE_SEGMENT in out.fragility_flags
    assert FLAG_TOP_HEAVY not in out.fragility_flags
    assert out.normalized_hhi == pytest.approx(0.1111, abs=0.001)


def test_shares_normalise_and_cumulative_reaches_one() -> None:
    registry = _uniform_registry(8)
    out = build_market_concentration(
        _results(
            {
                f"c{i}": 0.01 * i
                for i in range(1, 9)
            },
            n=8,
        ),
        simulation_id=1,
        project_id=1,
        cluster_registry=registry,
    )
    shares = [item.demand_share for item in out.segment_shares]
    assert sum(shares) == pytest.approx(1.0, abs=0.001)
    assert out.segment_shares[-1].cumulative_share == pytest.approx(
        1.0, abs=0.001
    )
    assert shares == sorted(shares, reverse=True)


def test_summary_weights_used_when_registry_missing() -> None:
    summaries = [
        {"cluster_id": "c1", "agents_assigned": 6000, "agents_converted": 300},
        {"cluster_id": "c2", "agents_assigned": 4000, "agents_converted": 100},
    ]
    out = build_market_concentration(
        _results({"c1": 0.05, "c2": 0.025}, n=2),
        simulation_id=1,
        project_id=1,
        cluster_summaries=summaries,
    )
    # c1 demand = 0.6 * 0.05 = 0.03 ; c2 = 0.4 * 0.025 = 0.01
    assert out.segment_shares[0].cluster_id == "c1"
    assert out.segment_shares[0].demand_share == pytest.approx(0.75, abs=0.001)
    assert out.segment_shares[1].demand_share == pytest.approx(0.25, abs=0.001)
    assert out.meta["demand_weighting"] == "cluster_run_summaries"


def test_meta_reports_registry_weighting_when_registry_wins() -> None:
    summaries = [
        {"cluster_id": "c1", "agents_assigned": 9000, "agents_converted": 100},
        {"cluster_id": "c2", "agents_assigned": 1000, "agents_converted": 100},
    ]
    registry = {
        "c1": {"name": "Big", "population_weight": 0.5},
        "c2": {"name": "Small", "population_weight": 0.5},
    }
    out = build_market_concentration(
        _results({"c1": 0.04, "c2": 0.04}, n=2),
        simulation_id=1,
        project_id=1,
        cluster_summaries=summaries,
        cluster_registry=registry,
    )
    # Registry weights take precedence over summaries, so the metadata
    # must say so instead of claiming cluster_run_summaries.
    assert out.meta["demand_weighting"] == "registry"


def test_meta_reports_uniform_when_no_weight_source() -> None:
    out = build_market_concentration(
        _results({"c1": 0.05, "c2": 0.05}, n=2),
        simulation_id=1,
        project_id=1,
    )
    assert out.meta["demand_weighting"] == "uniform"


def test_registry_weights_override_summaries() -> None:
    summaries = [
        {"cluster_id": "c1", "agents_assigned": 9000, "agents_converted": 100},
        {"cluster_id": "c2", "agents_assigned": 1000, "agents_converted": 100},
    ]
    registry = {
        "c1": {"name": "Big", "population_weight": 0.5},
        "c2": {"name": "Small", "population_weight": 0.5},
    }
    out = build_market_concentration(
        _results({"c1": 0.04, "c2": 0.04}, n=2),
        simulation_id=1,
        project_id=1,
        cluster_summaries=summaries,
        cluster_registry=registry,
    )
    # Equal registry weights → equal shares, ignoring agent counts.
    assert out.segment_shares[0].demand_share == pytest.approx(0.5, abs=0.001)


def test_schema_round_trip() -> None:
    out = build_market_concentration(
        _results(n=52, cr=0.03),
        simulation_id=7,
        project_id=9,
        signal_quality=0.61,
        cluster_registry=_uniform_registry(52),
    )
    payload = out.model_dump()
    restored = MarketConcentrationOut.model_validate(payload)
    assert restored.simulation_id == 7
    assert restored.project_id == 9
    assert restored.signal_quality == 0.61
    assert restored.verdict == out.verdict
    assert len(restored.segment_shares) == 52


def test_constants_are_sane() -> None:
    from app.simulation.market_concentration import (
        CONCENTRATED_NHHI,
        MODERATE_NHHI,
    )

    assert 0.0 < MODERATE_NHHI < CONCENTRATED_NHHI <= 1.0
