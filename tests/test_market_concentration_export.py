"""Pure-helper tests for the market-concentration CSV/JSON export."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest

from app.schemas.market_concentration import (
    ClusterDemandShare,
    MarketConcentrationOut,
)
from app.simulation.market_concentration import build_market_concentration
from app.simulation.market_concentration_export import (
    market_concentration_to_csv,
    market_concentration_to_json,
)


def _registry(n: int) -> dict[str, dict[str, Any]]:
    return {
        f"c{i}": {"name": f"Cluster {i}", "population_weight": 1.0 / n}
        for i in range(1, n + 1)
    }


def _uniform_payload(n: int = 4, cr: float = 0.05) -> MarketConcentrationOut:
    return build_market_concentration(
        {"cluster_breakdown": {f"c{i}": cr for i in range(1, n + 1)}},
        simulation_id=1,
        project_id=2,
        signal_quality=0.62,
        cluster_registry=_registry(n),
    )


def _metadata() -> dict[str, Any]:
    return {
        "generated_at": "2026-08-11T12:00:00+00:00",
        "user_id": 42,
        "format_version": "1",
        "simulation_id": 1,
        "project_id": 2,
    }


def test_csv_contains_metadata_and_summary() -> None:
    csv_text = market_concentration_to_csv(
        _uniform_payload(),
        metadata=_metadata(),
    )

    assert csv_text.startswith("\ufeff")
    assert "generated_at,2026-08-11T12:00:00+00:00" in csv_text
    assert "user_id,42" in csv_text
    assert "simulation_id,1" in csv_text
    assert "project_id,2" in csv_text
    assert "section,Demand Concentration Summary" in csv_text
    assert "verdict,DIVERSIFIED" in csv_text
    assert "clusters_with_demand,4" in csv_text
    assert "effective_segments,4.0" in csv_text


def test_csv_renders_one_row_per_segment_with_full_share_table() -> None:
    csv_text = market_concentration_to_csv(_uniform_payload())

    assert "section,Segment Demand Shares" in csv_text
    assert (
        "rank,cluster_id,cluster_name,population_weight,conversion_rate,"
        "demand_share,cumulative_share" in csv_text
    )
    for rank in range(1, 5):
        assert f"{rank},c{rank},Cluster {rank},0.25,0.05,0.25," in csv_text
    assert "section,Fragility Flags" in csv_text
    assert "section,Recommendations" in csv_text
    assert "1,Demand is well spread across ~4 effective segments" in csv_text
    assert "section,Meta" in csv_text
    assert "cluster_count,4" in csv_text
    assert "demand_weighting,registry" in csv_text


def test_csv_starts_with_utf8_bom_for_excel() -> None:
    csv_text = market_concentration_to_csv(_uniform_payload())
    assert csv_text.encode("utf-8").startswith(b"\xef\xbb\xbf")


def test_csv_neutralises_formula_injection() -> None:
    payload = MarketConcentrationOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        signal_quality=0.5,
        total_conversion_rate=0.05,
        hhi=1.0,
        normalized_hhi=1.0,
        effective_segments=1.0,
        verdict="CONCENTRATED",
        top_1_share=1.0,
        top_3_share=1.0,
        top_5_share=1.0,
        top_cluster_id="c1",
        top_cluster_name="=SUM(A1:A9)",
        total_clusters=1,
        clusters_with_demand=1,
        fragility_flags=["SINGLE_SEGMENT_DEPENDENCY"],
        recommendations=["-HYPERLINK(\"https://evil.example\")"],
        segment_shares=[
            ClusterDemandShare(
                cluster_id="c1",
                cluster_name="=SUM(A1:A9)",
                population_weight=1.0,
                conversion_rate=0.05,
                demand_share=1.0,
                cumulative_share=1.0,
            )
        ],
    )

    csv_text = market_concentration_to_csv(payload)
    assert "'=SUM(A1:A9)" in csv_text
    parsed = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
    recommendation_cells = [
        row[1] for row in parsed if len(row) >= 2 and row[0] == "1"
    ]
    assert any(
        cell.startswith("'-HYPERLINK(") for cell in recommendation_cells
    )
    # The raw formula must never appear unguarded as a cell value.
    assert "SUM(A1:A9)" not in csv_text.replace("'=SUM(A1:A9)", "")


def test_csv_handles_empty_zero_state_gracefully() -> None:
    empty = build_market_concentration(None, simulation_id=1, project_id=2)
    csv_text = market_concentration_to_csv(empty, metadata=_metadata())

    assert "verdict,INSUFFICIENT_DATA" in csv_text
    assert "clusters_with_demand,0" in csv_text
    assert "section,Segment Demand Shares" in csv_text
    assert "section,Recommendations" in csv_text
    assert "section,Fragility Flags" in csv_text


def test_csv_sanitises_non_finite_summary_numbers() -> None:
    payload = MarketConcentrationOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        total_conversion_rate=float("nan"),
        hhi=float("inf"),
        normalized_hhi=float("nan"),
        effective_segments=0.0,
        verdict="INSUFFICIENT_DATA",
        total_clusters=0,
        clusters_with_demand=0,
    )
    csv_text = market_concentration_to_csv(payload)

    assert "total_conversion_rate,0.0" in csv_text
    assert "hhi,0.0" in csv_text
    assert "normalized_hhi,0.0" in csv_text
    assert "nan" not in csv_text.lower()
    assert "inf" not in csv_text.lower()


def test_json_round_trips_payload_with_non_latin_text() -> None:
    payload = MarketConcentrationOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        signal_quality=0.62,
        total_conversion_rate=0.04,
        hhi=0.25,
        normalized_hhi=0.0,
        effective_segments=4.0,
        verdict="DIVERSIFIED",
        top_1_share=0.25,
        top_3_share=0.75,
        top_5_share=1.0,
        top_cluster_id="c1",
        top_cluster_name="都市通勤族",
        total_clusters=4,
        clusters_with_demand=4,
        recommendations=["優先開拓 c1"],
        segment_shares=[
            ClusterDemandShare(
                cluster_id="c1",
                cluster_name="都市通勤族",
                population_weight=0.25,
                conversion_rate=0.04,
                demand_share=0.25,
                cumulative_share=0.25,
            )
        ],
        meta={"generated_at": "2026-08-11T12:00:00+00:00"},
    )

    text = market_concentration_to_json(payload, metadata=_metadata())
    assert text.endswith("\n")
    assert "都市通勤族" in text
    assert "\\u" not in text

    parsed = json.loads(text)
    assert parsed["metadata"]["simulation_id"] == 1
    body = parsed["market_concentration"]
    assert body["top_cluster_name"] == "都市通勤族"
    assert body["segment_shares"][0]["demand_share"] == pytest.approx(0.25)


def test_json_accepts_plain_dicts() -> None:
    text = market_concentration_to_json(
        {"simulation_id": 7, "segment_shares": []},
        metadata={"simulation_id": 7},
    )
    parsed = json.loads(text)
    assert parsed["market_concentration"]["simulation_id"] == 7
