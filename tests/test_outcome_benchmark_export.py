"""Tests for the outcome-benchmark export helpers.

Covers the multi-section CSV rendering, the JSON envelope, spreadsheet
formula-injection guarding, malformed-payload resilience, and the honest
blank-cell behaviour when no current outcome or peers exist.
"""

from __future__ import annotations

import json

import pytest

from app.simulation.outcome_benchmark_export import (
    FORMAT_VERSION,
    outcome_benchmark_to_csv,
    outcome_benchmark_to_json,
)


def _payload(*, with_current: bool = True) -> dict:
    payload = {
        "has_data": with_current,
        "category": "saas",
        "current": {
            "outcome_id": 1,
            "simulation_id": 7,
            "project_id": 10,
            "days_since_launch": 30,
            "actual_conversion_rate": 0.06,
            "predicted_conversion_rate": 0.04,
            "data_confidence": "ESTIMATED",
            "launched": True,
            "recorded_at": "2026-08-01T00:00:00+00:00",
        },
        "distribution": {
            "peer_count": 5,
            "min": 0.01,
            "p25": 0.02,
            "median": 0.03,
            "p75": 0.04,
            "max": 0.05,
            "mean": 0.03,
        },
        "percentile_rank": 100.0,
        "verdict": "TOP_QUARTILE",
        "median_comparison": "Above the peer median (0.03)",
        "narrative": "Ranks at 100.0% of comparable launched outcomes.",
        "insights": [
            "Ranks above 100.0% of comparable launched outcomes.",
            "Actual conversion is 1.5x the simulated prediction.",
        ],
        "key_signals": [
            {
                "label": "outcome_benchmark",
                "value": "TOP_QUARTILE",
                "severity": "ok",
                "display": "Real-world conversion verdict: Top Quartile",
            }
        ],
        "meta": {
            "benchmark_scope": (
                "other launched projects in the same product category "
                "across TheCee"
            ),
            "peers_scanned": 5,
            "peers_usable": 5,
            "peers_skipped_invalid": 0,
            "peers_skipped_product_changed": 0,
            "data_sufficient": True,
        },
    }
    if not with_current:
        payload["current"] = None
        payload["percentile_rank"] = None
        payload["verdict"] = "INSUFFICIENT_DATA"
        payload["median_comparison"] = None
        payload["narrative"] = (
            "No founder outcome recorded yet — the real-world benchmark "
            "unlocks after you report how launch went."
        )
        payload["insights"] = [
            "Record a founder outcome for this project to see how its "
            "real-world conversion ranks against peer launches."
        ]
        payload["distribution"] = {
            "peer_count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
            "mean": None,
        }
        payload["meta"] = {
            "benchmark_scope": (
                "other launched projects in the same product category "
                "across TheCee"
            ),
            "peers_scanned": 0,
            "peers_usable": 0,
            "peers_skipped_invalid": 0,
            "peers_skipped_product_changed": 0,
            "data_sufficient": False,
        }
    return payload


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


def test_csv_renders_metadata_and_current_outcome() -> None:
    csv_text = outcome_benchmark_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-09T12:00:00+00:00",
            "user_id": 42,
            "project_id": 10,
            "category": "saas",
            "format_version": FORMAT_VERSION,
        },
    )

    assert csv_text.startswith("generated_at,")
    assert "user_id,42" in csv_text
    assert "project_id,10" in csv_text
    assert "category,saas" in csv_text
    assert "section,Current Outcome" in csv_text
    assert "outcome_id,1" in csv_text
    assert "simulation_id,7" in csv_text
    assert "days_since_launch,30" in csv_text
    assert "actual_conversion_rate,0.06" in csv_text
    assert "predicted_conversion_rate,0.04" in csv_text
    assert "conversion_delta,0.02" in csv_text
    assert "data_confidence,ESTIMATED" in csv_text
    assert "launched,true" in csv_text


def test_csv_renders_distribution_ranking_insights_and_meta() -> None:
    csv_text = outcome_benchmark_to_csv(_payload())

    assert "section,Peer Distribution" in csv_text
    assert "peer_count,5" in csv_text
    assert "min,0.01" in csv_text
    assert "median,0.03" in csv_text
    assert "max,0.05" in csv_text
    assert "mean,0.03" in csv_text
    assert "section,Ranking" in csv_text
    assert "percentile_rank,100.0" in csv_text
    assert "verdict,TOP_QUARTILE" in csv_text
    assert "median_comparison,Above the peer median (0.03)" in csv_text
    assert "section,Insights" in csv_text
    assert "Ranks above 100.0%" in csv_text
    assert "section,Meta" in csv_text
    assert "peers_scanned,5" in csv_text
    assert "peers_usable,5" in csv_text
    assert "data_sufficient,true" in csv_text
    assert "benchmark_scope,other launched projects" in csv_text


def test_csv_renders_blanks_when_no_current_outcome() -> None:
    csv_text = outcome_benchmark_to_csv(_payload(with_current=False))

    assert "section,Current Outcome" in csv_text
    assert "outcome_id," in csv_text
    assert "actual_conversion_rate," in csv_text
    assert "predicted_conversion_rate," in csv_text
    assert "conversion_delta," in csv_text
    assert "section,Peer Distribution" in csv_text
    assert "peer_count,0" in csv_text
    assert "median," in csv_text
    assert "section,Ranking" in csv_text
    assert "percentile_rank," in csv_text
    assert "verdict,INSUFFICIENT_DATA" in csv_text
    assert "Record a founder outcome" in csv_text


def test_csv_guards_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["insights"] = ['=HYPERLINK("https://evil.example")']
    payload["narrative"] = " \t+SUM(A1:A2)"
    payload["median_comparison"] = "@SUM(A1:A2)"
    payload["category"] = "-2+3"

    csv_text = outcome_benchmark_to_csv(payload)

    assert "'=HYPERLINK" in csv_text
    assert "' \t+SUM(A1:A2)" in csv_text
    assert "'@SUM(A1:A2)" in csv_text
    assert "'-2+3" in csv_text


def test_csv_handles_malformed_payload_without_raising() -> None:
    csv_text = outcome_benchmark_to_csv(
        {
            "current": "junk",
            "distribution": None,
            "percentile_rank": float("nan"),
            "verdict": None,
            "median_comparison": None,
            "narrative": None,
            "insights": None,
            "meta": {
                "peers_scanned": float("inf"),
                "peers_usable": 1e999,
                "peers_skipped_invalid": "n/a",
                "peers_skipped_product_changed": None,
                "data_sufficient": None,
                "benchmark_scope": None,
            },
        }
    )

    assert "section,Current Outcome" in csv_text
    assert "outcome_id," in csv_text
    assert "section,Peer Distribution" in csv_text
    assert "peer_count,0" in csv_text
    assert "median," in csv_text
    assert "section,Ranking" in csv_text
    assert "percentile_rank," in csv_text
    assert "section,Insights" in csv_text
    assert "section,Meta" in csv_text
    assert "peers_scanned,0" in csv_text
    assert "peers_usable,0" in csv_text
    assert "data_sufficient," in csv_text
    assert "benchmark_scope," in csv_text


def test_csv_ignores_non_dict_metadata_without_raising() -> None:
    csv_text = outcome_benchmark_to_csv(
        _payload(),
        metadata=["not", "a", "dict"],
    )

    assert not csv_text.startswith("generated_at,")
    assert "section,Current Outcome" in csv_text

    no_metadata = outcome_benchmark_to_csv(_payload(), metadata=None)
    assert no_metadata.startswith("section,Current Outcome")


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def test_json_renders_envelope_with_payload() -> None:
    text = outcome_benchmark_to_json(
        _payload(),
        metadata={
            "generated_at": "2026-08-09T12:00:00+00:00",
            "user_id": 42,
            "project_id": 10,
            "category": "saas",
            "format_version": FORMAT_VERSION,
        },
    )
    data = json.loads(text)

    assert data["metadata"]["format_version"] == "1"
    assert data["metadata"]["project_id"] == 10
    assert data["outcome_benchmark"]["verdict"] == "TOP_QUARTILE"
    assert data["outcome_benchmark"]["current"]["actual_conversion_rate"] == (
        pytest.approx(0.06)
    )
    assert data["outcome_benchmark"]["distribution"]["median"] == (
        pytest.approx(0.03)
    )
    assert text.endswith("\n")


def test_json_handles_no_data_payload() -> None:
    text = outcome_benchmark_to_json(_payload(with_current=False))
    data = json.loads(text)

    assert data["outcome_benchmark"]["has_data"] is False
    assert data["outcome_benchmark"]["current"] is None
    assert data["outcome_benchmark"]["verdict"] == "INSUFFICIENT_DATA"
