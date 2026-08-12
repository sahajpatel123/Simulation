"""Tests for the outcome-gaps digest export serializers."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas.outcome_gaps import (
    ProjectOutcomeGapsOut,
    ProjectOutcomeGapsSummary,
    SimulationOutcomeGapItem,
)
from app.schemas.portfolio_outcome_gaps import (
    PortfolioOutcomeGapItem,
    PortfolioOutcomeGapProject,
    PortfolioOutcomeGapsOut,
    PortfolioOutcomeGapsSummary,
)
from app.simulation.outcome_gaps_export import (
    outcome_gaps_to_csv,
    outcome_gaps_to_json,
    outcome_gaps_to_markdown,
)

_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
_METADATA = {
    "generated_at": "2026-08-12T12:00:00+00:00",
    "user_id": 42,
    "format_version": "1",
    "project_id": 7,
}


def _project_payload() -> ProjectOutcomeGapsOut:
    return ProjectOutcomeGapsOut(
        project_id=7,
        generated_at=_NOW.isoformat(),
        summary=ProjectOutcomeGapsSummary(
            total_completed=10,
            scored=4,
            unscored=6,
            coverage_rate_pct=40.0,
            learning_eligible_unscored=2,
            oldest_unscored_age_days=40,
            narrative=(
                "Only 4 of 10 completed runs have outcome feedback (40.0%). "
                "6 unscored run(s) remain; 2 would feed calibration."
            ),
        ),
        items=[
            SimulationOutcomeGapItem(
                simulation_id=7,
                created_at=_NOW - timedelta(days=45),
                age_days=45,
                signal_quality=0.6,
                predicted_conversion_rate=0.042,
                product_type_detected="saas",
                primary_failure_domain="pricing",
                has_results=True,
                learning_eligible=True,
                urgency="HIGH",
                recommendation=(
                    "Score this run now — it is 45 days old and would feed "
                    "calibration."
                ),
            )
        ],
        limit=50,
        has_more=False,
    )


def _portfolio_payload() -> PortfolioOutcomeGapsOut:
    return PortfolioOutcomeGapsOut(
        user_id=42,
        generated_at=_NOW.isoformat(),
        summary=PortfolioOutcomeGapsSummary(
            project_count=2,
            projects_with_gaps=1,
            total_completed=12,
            scored=7,
            unscored=5,
            coverage_rate_pct=58.33,
            learning_eligible_unscored=3,
            high_priority_unscored=1,
            oldest_unscored_age_days=40,
            narrative=(
                "Across 2 project(s), only 7 of 12 completed runs have "
                "outcome feedback (58.3%)."
            ),
        ),
        projects=[
            PortfolioOutcomeGapProject(
                project_id=7,
                total_completed=10,
                scored=4,
                unscored=6,
                coverage_rate_pct=40.0,
                learning_eligible_unscored=2,
                high_priority_unscored=1,
                oldest_unscored_age_days=40,
            ),
            PortfolioOutcomeGapProject(
                project_id=9,
                total_completed=2,
                scored=2,
                unscored=0,
                coverage_rate_pct=100.0,
                learning_eligible_unscored=0,
                high_priority_unscored=0,
                oldest_unscored_age_days=None,
            ),
        ],
        items=[
            PortfolioOutcomeGapItem(
                project_id=7,
                simulation_id=7,
                created_at=_NOW - timedelta(days=45),
                age_days=45,
                signal_quality=0.6,
                predicted_conversion_rate=0.042,
                product_type_detected="saas",
                primary_failure_domain="pricing",
                has_results=True,
                learning_eligible=True,
                urgency="HIGH",
                recommendation=(
                    "Score this run now — it is 45 days old and would feed "
                    "calibration."
                ),
            )
        ],
        limit=50,
        has_more=False,
        learning_eligible_only=False,
    )


def _rows_from_csv(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


def _strict_json_loads(text: str) -> Any:
    """Parse JSON, rejecting the non-standard NaN/Infinity tokens."""

    def _reject_constant(token: str) -> None:
        raise AssertionError(f"non-finite JSON token emitted: {token}")

    return json.loads(text, parse_constant=_reject_constant)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_csv_renders_project_metadata_summary_and_items() -> None:
    csv_text = outcome_gaps_to_csv(
        _project_payload(),
        metadata=_METADATA,
    )

    assert "user_id,42" in csv_text
    assert "project_id,7" in csv_text
    assert "section,Outcome Feedback Gaps Summary" in csv_text
    assert "total_completed,10" in csv_text
    assert "coverage_rate_pct,40.0" in csv_text
    assert "oldest_unscored_age_days,40" in csv_text
    assert "section,Unscored Simulations" in csv_text
    assert "simulation_id,created_at,age_days" in csv_text
    assert "simulation_id,project_id,created_at" not in csv_text
    assert "7,2026-06-28T12:00:00+00:00,45,0.6,0.042,saas,pricing" in csv_text
    assert ",yes,yes,HIGH," in csv_text


def test_csv_portfolio_includes_project_id_and_portfolio_summary() -> None:
    csv_text = outcome_gaps_to_csv(
        _portfolio_payload(),
        metadata={**_METADATA, "project_id": None},
    )

    assert "project_count,2" in csv_text
    assert "projects_with_gaps,1" in csv_text
    assert "high_priority_unscored,1" in csv_text
    assert "learning_eligible_only,false" in csv_text
    assert "simulation_id,project_id,created_at" in csv_text
    assert "7,7,2026-06-28T12:00:00+00:00,45,0.6,0.042,saas,pricing" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = outcome_gaps_to_csv({})

    assert "section,Outcome Feedback Gaps Summary" in csv_text
    assert "section,Unscored Simulations" in csv_text
    assert "key,value" in csv_text
    assert "simulation_id,created_at,age_days" in csv_text


def test_csv_preserves_zero_coverage_rate() -> None:
    payload = _project_payload()
    payload.summary.scored = 0
    payload.summary.coverage_rate_pct = 0.0

    csv_text = outcome_gaps_to_csv(payload)

    # A real 0% coverage rate must survive the export; only missing or
    # non-finite values render as blank cells.
    assert "coverage_rate_pct,0.0" in csv_text
    assert "coverage_rate_pct,\n" not in csv_text


def test_csv_neutralises_spreadsheet_formula_injection() -> None:
    payload = _project_payload()
    payload.summary.narrative = "-2+3"
    payload.items[0].recommendation = "=HYPERLINK('https://evil.example')"
    payload.items[0].product_type_detected = " @saas"

    csv_text = outcome_gaps_to_csv(
        payload,
        metadata={**_METADATA, "generated_at": "=NOW()"},
    )

    assert "'-2+3" in csv_text
    assert "'=HYPERLINK" in csv_text
    assert "' @saas" in csv_text
    assert "'=NOW()" in csv_text
    parsed_rows = _rows_from_csv(csv_text)
    assert not any(
        cell.lstrip().startswith(("=", "+", "-", "@"))
        or cell[:1] in ("\t", "\r", "\n")
        for row in parsed_rows
        for cell in row
    )


def test_csv_tolerates_malformed_rows_and_non_finite_numbers() -> None:
    payload: dict[str, Any] = {
        "project_id": 7,
        "generated_at": _NOW.isoformat(),
        "summary": {
            "total_completed": "oops",
            "scored": 1,
            "unscored": 2,
            "coverage_rate_pct": float("nan"),
            "learning_eligible_unscored": 0,
            "oldest_unscored_age_days": None,
            "narrative": None,
        },
        "items": [
            None,
            {
                "simulation_id": 3,
                "created_at": None,
                "age_days": "oops",
                "signal_quality": float("nan"),
                "predicted_conversion_rate": None,
                "product_type_detected": None,
                "primary_failure_domain": None,
                "has_results": None,
                "learning_eligible": False,
                "urgency": None,
                "recommendation": None,
            },
        ],
        "limit": 50,
        "has_more": False,
    }

    csv_text = outcome_gaps_to_csv(payload)
    parsed_rows = _rows_from_csv(csv_text)
    assert "coverage_rate_pct," in csv_text
    item_row = next(
        row for row in parsed_rows if row and row[0] == "3"
    )
    assert item_row[1] == ""  # created_at blank
    assert item_row[3] == ""  # non-finite signal blank
    assert item_row[4] == ""  # missing predicted blank
    assert item_row[7] == ""  # has_results missing → blank
    assert item_row[8] == "no"  # learning_eligible false


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_envelope_is_strict_and_deterministic() -> None:
    payload = _portfolio_payload()
    first = outcome_gaps_to_json(payload, metadata=_METADATA)
    second = outcome_gaps_to_json(payload, metadata=_METADATA)

    assert first == second
    parsed = _strict_json_loads(first)
    assert parsed["metadata"]["user_id"] == 42
    assert parsed["metadata"]["format_version"] == "1"
    gaps = parsed["outcome_gaps"]
    assert gaps["user_id"] == 42
    assert gaps["summary"]["project_count"] == 2
    assert len(gaps["items"]) == 1
    assert gaps["items"][0]["project_id"] == 7


def test_json_renders_non_finite_floats_as_null() -> None:
    payload = {
        "project_id": 7,
        "generated_at": _NOW.isoformat(),
        "summary": {
            "coverage_rate_pct": float("nan"),
            "narrative": "x",
        },
        "items": [
            {
                "simulation_id": 1,
                "signal_quality": float("inf"),
                "predicted_conversion_rate": 0.1,
                "has_results": True,
                "learning_eligible": False,
            }
        ],
        "limit": 50,
        "has_more": False,
    }

    parsed = _strict_json_loads(outcome_gaps_to_json(payload))
    assert parsed["outcome_gaps"]["summary"]["coverage_rate_pct"] is None
    assert parsed["outcome_gaps"]["items"][0]["signal_quality"] is None


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_renders_project_brief() -> None:
    text = outcome_gaps_to_markdown(
        _project_payload(),
        metadata=_METADATA,
    )

    assert text.startswith("# Outcome Feedback Gaps")
    assert "## Summary" in text
    assert "## Unscored Simulations" in text
    assert "| Simulation | Created | Age (days) |" in text
    assert "| Simulation | Project |" not in text
    assert "| Completed simulations | 10 |" in text
    assert "| Coverage rate | 40.0% |" in text
    assert "Only 4 of 10 completed runs" in text
    assert "| 7 | 2026-06-28T12:00:00+00:00 | 45 | 60.00% | 4.20% |" in text
    assert "Project 7" in text


def test_markdown_portfolio_includes_project_column_and_footer() -> None:
    text = outcome_gaps_to_markdown(
        _portfolio_payload(),
        metadata={**_METADATA, "project_id": None},
    )

    assert "| Simulation | Project | Created | Age (days) |" in text
    assert "| 7 | 7 | 2026-06-28T12:00:00+00:00 | 45 |" in text
    assert "| Projects | 2 |" in text
    assert "User 42" in text
    assert "Project 7" not in text


def test_markdown_escapes_pipes_in_cells() -> None:
    payload = _project_payload()
    payload.items[0].recommendation = "pricing | trust trade-off"

    text = outcome_gaps_to_markdown(payload)

    assert "pricing \\| trust trade-off" in text


def test_markdown_empty_payload_renders_sections() -> None:
    text = outcome_gaps_to_markdown({})

    assert text.startswith("# Outcome Feedback Gaps")
    assert "## Summary" in text
    assert "## Unscored Simulations" in text
    assert "| Metric | Value |" in text
    assert "| ---: | --- |" in text
    # Missing identifiers must not be invented as "Project 0" / "User 0".
    assert "Project 0" not in text
    assert "User 0" not in text
