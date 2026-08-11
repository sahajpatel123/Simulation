"""Pure-helper tests for the cluster-run-summary CSV/JSON export."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from app.simulation.cluster_run_summary_export import (
    build_cluster_run_summary_export,
    cluster_run_summary_to_csv,
    cluster_run_summary_to_json,
)


def _row(
    *,
    cluster_id: str = "metro_power_professional",
    cluster_name: str = "Metro Power Professional",
) -> dict[str, Any]:
    return {
        "id": 11,
        "cluster_id": cluster_id,
        "agents_assigned": 1000,
        "agents_converted": 40,
        "conversion_rate": 0.04,
        "drop_state_distribution": {"ARRIVE": 1000, "BROWSE": 600, "CONSIDER": 200},
        "mean_drop_state": "CONSIDER",
        "architect_scores": {"PricingArchitect": 0.62, "TrustArchitect": 0.48},
        "primary_drop_trigger": "price_sensitivity",
        "signal_quality": 0.62,
        "claim_confidence_distribution": {"HIGH": 0.8, "MEDIUM": 0.2},
        "product_type": "saas",
        "created_at": "2026-08-12T10:00:00+00:00",
        "cluster_name": cluster_name,
    }


def _metadata() -> dict[str, Any]:
    return {
        "generated_at": "2026-08-12T12:00:00+00:00",
        "user_id": 42,
        "format_version": "1",
        "simulation_id": 7,
        "project_id": 9,
    }


def _strict_json_loads(text: str) -> Any:
    """Parse JSON, rejecting the non-standard NaN/Infinity tokens."""

    def _reject_constant(_: str) -> None:
        raise AssertionError("non-finite JSON token emitted")

    return json.loads(text, parse_constant=_reject_constant)


def test_build_payload_aggregates_rows_and_enriches_names() -> None:
    export = build_cluster_run_summary_export(
        [
            _row(),
            _row(
                cluster_id="tier3_first_time_app_user",
                cluster_name="Tier-3 First-Time App User",
            ),
        ],
        simulation_id=7,
        project_id=9,
        status="COMPLETED",
        cluster_names={
            "metro_power_professional": "Metro Power Professional",
            "tier3_first_time_app_user": "Tier-3 First-Time App User",
        },
        created_at="2026-08-12T09:00:00+00:00",
    )

    assert export["simulation_id"] == 7
    assert export["project_id"] == 9
    assert export["status"] == "COMPLETED"
    assert export["created_at"] == "2026-08-12T09:00:00+00:00"
    assert export["total_clusters"] == 2
    assert export["total_agents_assigned"] == 2000
    assert export["total_agents_converted"] == 80
    assert export["agents_weighted_conversion_rate"] == 0.04
    assert export["rows"][0]["cluster_name"] == "Metro Power Professional"
    assert export["rows"][1]["cluster_name"] == "Tier-3 First-Time App User"


def test_build_payload_sanitises_malformed_rows() -> None:
    malformed = _row()
    malformed.update(
        {
            "agents_assigned": "not-a-number",
            "conversion_rate": float("inf"),
            "signal_quality": float("nan"),
            "drop_state_distribution": None,
        }
    )
    export = build_cluster_run_summary_export(
        [malformed],
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
    )

    row = export["rows"][0]
    assert row["agents_assigned"] == 0
    assert row["conversion_rate"] == 0.0
    assert row["signal_quality"] is None
    assert row["drop_state_distribution"] is None
    assert export["total_agents_assigned"] == 0
    assert export["total_agents_converted"] == 40
    assert export["agents_weighted_conversion_rate"] is None


def test_export_sanitises_nested_non_finite_values() -> None:
    row = _row()
    row.update(
        {
            "drop_state_distribution": {
                "ARRIVE": 1000,
                "BROWSE": float("inf"),
                "CONSIDER": float("nan"),
            },
            "architect_scores": {
                "PricingArchitect": float("inf"),
                "TrustArchitect": 0.48,
            },
            "claim_confidence_distribution": {"HIGH": float("nan")},
        }
    )
    export = build_cluster_run_summary_export(
        [row],
        simulation_id=7,
        project_id=9,
        status="COMPLETED",
    )

    rendered = export["rows"][0]
    assert rendered["drop_state_distribution"]["BROWSE"] is None
    assert rendered["drop_state_distribution"]["CONSIDER"] is None
    assert rendered["architect_scores"]["PricingArchitect"] is None
    assert rendered["architect_scores"]["TrustArchitect"] == 0.48
    assert rendered["claim_confidence_distribution"]["HIGH"] is None

    json_text = cluster_run_summary_to_json(export, metadata=_metadata())
    assert "NaN" not in json_text
    assert "Infinity" not in json_text
    parsed = _strict_json_loads(json_text)
    parsed_row = parsed["cluster_run_summaries"]["rows"][0]
    assert parsed_row["drop_state_distribution"]["BROWSE"] is None
    assert parsed_row["architect_scores"]["PricingArchitect"] is None

    csv_text = cluster_run_summary_to_csv(export, metadata=_metadata())
    assert "NaN" not in csv_text
    assert "Infinity" not in csv_text
    assert "null" in csv_text


def test_json_helper_sanitises_non_finite_values_directly() -> None:
    text = cluster_run_summary_to_json(
        {
            "simulation_id": 1,
            "project_id": 2,
            "status": "COMPLETED",
            "rows": [
                {
                    "architect_scores": {"PricingArchitect": float("nan")},
                    "drop_state_distribution": {"ARRIVE": float("inf")},
                }
            ],
        }
    )

    parsed = _strict_json_loads(text)
    parsed_row = parsed["cluster_run_summaries"]["rows"][0]
    assert parsed_row["architect_scores"]["PricingArchitect"] is None
    assert parsed_row["drop_state_distribution"]["ARRIVE"] is None


def test_build_payload_accepts_orm_like_objects() -> None:
    class Row:
        id = 5
        cluster_id = "metro_power_professional"
        agents_assigned = 500
        agents_converted = 25
        conversion_rate = 0.05
        drop_state_distribution = {"ARRIVE": 500}
        mean_drop_state = "BROWSE"
        architect_scores = {}
        primary_drop_trigger = "trust"
        signal_quality = 0.5
        claim_confidence_distribution = None
        product_type = "saas"
        created_at = "2026-08-01T00:00:00+00:00"

    export = build_cluster_run_summary_export(
        [Row()],
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
    )

    assert export["rows"][0]["cluster_id"] == "metro_power_professional"
    assert export["rows"][0]["agents_assigned"] == 500
    assert export["rows"][0]["conversion_rate"] == 0.05


def test_build_payload_renders_datetimes_as_iso8601() -> None:
    row = _row()
    row["created_at"] = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    export = build_cluster_run_summary_export(
        [row],
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        created_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
    )

    assert export["created_at"] == "2026-08-12T08:00:00+00:00"
    assert export["rows"][0]["created_at"] == "2026-08-12T09:00:00+00:00"


def test_csv_contains_metadata_summary_header_and_nested_json() -> None:
    export = build_cluster_run_summary_export(
        [_row()],
        simulation_id=7,
        project_id=9,
        status="COMPLETED",
        cluster_names={"metro_power_professional": "Metro Power Professional"},
        created_at="2026-08-12T09:00:00+00:00",
    )
    csv_text = cluster_run_summary_to_csv(export, metadata=_metadata())

    assert csv_text.startswith("\ufeff")
    assert "generated_at,2026-08-12T12:00:00+00:00" in csv_text
    assert "user_id,42" in csv_text
    assert "simulation_id,7" in csv_text
    assert "project_id,9" in csv_text
    assert "section,Cluster Run Summary" in csv_text
    assert "total_clusters,1" in csv_text
    assert "total_agents_assigned,1000" in csv_text
    assert "total_agents_converted,40" in csv_text
    assert "agents_weighted_conversion_rate,0.04" in csv_text
    assert "section,Cluster Run Rows" in csv_text
    assert ",".join(
        [
            "id",
            "cluster_id",
            "cluster_name",
            "agents_assigned",
            "agents_converted",
            "conversion_rate",
            "mean_drop_state",
            "primary_drop_trigger",
            "drop_state_distribution",
            "architect_scores",
            "signal_quality",
            "claim_confidence_distribution",
            "product_type",
            "created_at",
        ]
    ) in csv_text
    # CSV quoting doubles embedded quotes in JSON cells.
    assert '""ARRIVE"":1000,""BROWSE"":600,""CONSIDER"":200' in csv_text
    assert '""PricingArchitect"":0.62,""TrustArchitect"":0.48' in csv_text
    assert "price_sensitivity" in csv_text


def test_csv_neutralises_formula_injection() -> None:
    row = _row(cluster_id="=SUM(A1:A9)")
    export = build_cluster_run_summary_export(
        [row],
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        cluster_names={"=SUM(A1:A9)": "=HYPERLINK(\"x\")"},
    )
    csv_text = cluster_run_summary_to_csv(export)
    parsed = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))

    cells = [cell for row in parsed for cell in row]
    assert "'=SUM(A1:A9)" in cells
    assert "'=HYPERLINK(\"x\")" in cells
    # The raw formula must never appear as an unguarded cell.
    assert "=SUM(A1:A9)" not in csv_text.replace("'=SUM(A1:A9)", "")


def test_csv_handles_empty_rows_gracefully() -> None:
    export = build_cluster_run_summary_export(
        [],
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
    )
    csv_text = cluster_run_summary_to_csv(export, metadata=_metadata())

    assert "total_clusters,0" in csv_text
    assert "total_agents_assigned,0" in csv_text
    assert "total_agents_converted,0" in csv_text
    assert "agents_weighted_conversion_rate," in csv_text
    assert "section,Cluster Run Rows" in csv_text


def test_json_round_trips_nested_non_latin_data() -> None:
    export = build_cluster_run_summary_export(
        [
            _row(cluster_id="都市通勤族", cluster_name="都市通勤族")
        ],
        simulation_id=7,
        project_id=9,
        status="COMPLETED",
        created_at="2026-08-12T09:00:00+00:00",
    )
    text = cluster_run_summary_to_json(export, metadata=_metadata())

    assert text.endswith("\n")
    assert "都市通勤族" in text
    assert "\\u" not in text
    parsed = json.loads(text)
    assert parsed["metadata"]["simulation_id"] == 7
    body = parsed["cluster_run_summaries"]
    assert body["total_clusters"] == 1
    assert body["rows"][0]["architect_scores"]["PricingArchitect"] == 0.62


def test_json_accepts_empty_payload() -> None:
    text = cluster_run_summary_to_json(
        {
            "simulation_id": 1,
            "project_id": 2,
            "status": "COMPLETED",
            "rows": [],
        }
    )
    parsed = json.loads(text)
    assert parsed["cluster_run_summaries"]["rows"] == []
