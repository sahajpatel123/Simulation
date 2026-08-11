"""Tests for the project-comparison export serializers."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.schemas.project_comparison import ProjectComparisonOut
from app.simulation.project_comparison import build_project_comparison
from app.simulation.project_comparison_export import (
    project_comparison_to_csv,
    project_comparison_to_json,
    project_comparison_to_markdown,
)


def _row(
    project_id: int = 1,
    *,
    health_score: int = 70,
    conversion_rate: float | None = 0.04,
    confidence: float | None = 0.6,
    critical: int = 0,
    title: str = "",
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "title": title or f"Project {project_id}",
        "status": "ACTIVE",
        "simulation_count": 3,
        "assumption_count": 8,
        "outcome_count": 1,
        "pending_decision_count": 0,
        "critical_finding_count": critical,
        "weak_link_count": 1,
        "latest_conversion_rate": conversion_rate,
        "latest_confidence_score": confidence,
        "brief_completed": True,
        "primary_failure_domain": "pricing",
        "product_type_detected": "saas",
        "project_health_score": health_score,
        "project_health_verdict": "HEALTHY" if health_score >= 70 else "AT_RISK",
    }


def _comparison(
    *,
    a: dict[str, Any] | None = None,
    b: dict[str, Any] | None = None,
) -> ProjectComparisonOut:
    return build_project_comparison([
        a if a is not None else _row(1, health_score=72),
        b
        if b is not None
        else _row(2, health_score=45, conversion_rate=0.03, critical=2),
    ])


_METADATA = {
    "generated_at": "2026-08-12T00:00:00Z",
    "user_id": 42,
    "format_version": "1",
    "project_id": 1,
    "comparison_id": "abc123",
}


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


def _strict_json_loads(text: str) -> Any:
    """Parse JSON, rejecting the non-standard NaN/Infinity tokens."""

    def _reject_constant(token: str) -> None:
        raise AssertionError(f"non-finite JSON token emitted: {token}")

    return json.loads(text, parse_constant=_reject_constant)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_csv_has_summary_signals_projects_and_dimensions() -> None:
    csv_text = project_comparison_to_csv(_comparison(), metadata=_METADATA)

    assert "section,Project Comparison Summary" in csv_text
    assert "winner_project_id,1" in csv_text
    assert "winner_label,A" in csv_text
    assert "verdict,A_LEADS" in csv_text
    assert "section,Key Signals" in csv_text
    assert "Overall leader: Project A" in csv_text
    assert "section,Projects Compared" in csv_text
    assert "Project 1,ACTIVE,72" in csv_text
    assert "Project 2,ACTIVE,45" in csv_text
    assert "section,Dimension Comparison" in csv_text
    assert "latest_conversion_rate,Latest predicted conversion" in csv_text
    assert "0.04,0.03,4.00%,3.00%" in csv_text
    assert "abc123" in csv_text

    rows = _rows(csv_text)
    assert rows[0][0] == "generated_at"
    assert any(row and row[0] == "dimension" for row in rows)


def test_csv_neutralises_formula_injection() -> None:
    comparison = _comparison(
        a=_row(1, title="=HYPERLINK(https://example.com)"),
    )
    csv_text = project_comparison_to_csv(comparison)

    assert "'=HYPERLINK(https://example.com)" in csv_text
    # No cell may start with a raw formula character.
    assert not any(
        row and row[0].startswith("=") for row in _rows(csv_text)
    )


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = project_comparison_to_csv({})

    assert "section,Project Comparison Summary" in csv_text
    assert "section,Key Signals" in csv_text
    assert "section,Projects Compared" in csv_text
    assert "section,Dimension Comparison" in csv_text


def test_csv_handles_malformed_rows_without_raising() -> None:
    csv_text = project_comparison_to_csv(
        {
            "projects": [None, "not-a-dict"],
            "dimensions": [None, 3],
            "summary": {"key_signals": [None, {"label": "ok"}]},
        }
    )

    assert "section,Projects Compared" in csv_text
    assert "section,Dimension Comparison" in csv_text
    assert "label,value,severity,display" in csv_text


def test_csv_sanitises_nested_non_finite_values() -> None:
    comparison = _comparison()
    comparison.dimensions[0].a = {"score": float("nan")}
    comparison.dimensions[0].b = {"score": float("inf")}

    csv_text = project_comparison_to_csv(comparison, metadata=_METADATA)

    assert "NaN" not in csv_text
    assert "Infinity" not in csv_text
    assert any(
        cell == '{"score":null}'
        for row in _rows(csv_text)
        for cell in row
    )


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_envelope_includes_metadata_and_payload() -> None:
    text = project_comparison_to_json(_comparison(), metadata=_METADATA)
    parsed = json.loads(text)

    assert parsed["metadata"]["comparison_id"] == "abc123"
    assert parsed["metadata"]["project_id"] == 1
    comp = parsed["project_comparison"]
    assert comp["summary"]["verdict"] == "A_LEADS"
    assert len(comp["projects"]) == 2
    assert len(comp["dimensions"]) == 10
    assert comp["projects"][0]["title"] == "Project 1"


def test_json_export_sanitises_nested_non_finite_values() -> None:
    comparison = _comparison()
    comparison.dimensions[0].a = float("nan")
    comparison.dimensions[0].b = float("inf")
    comparison.dimensions[1].a = {
        "PricingArchitect": float("inf"),
        "TrustArchitect": 0.48,
    }
    comparison.dimensions[1].b = {"PricingArchitect": float("nan")}

    text = project_comparison_to_json(
        comparison,
        metadata={**_METADATA, "generated_at": float("nan")},
    )

    assert "NaN" not in text
    assert "Infinity" not in text
    parsed = _strict_json_loads(text)
    dims = parsed["project_comparison"]["dimensions"]
    assert dims[0]["a"] is None
    assert dims[0]["b"] is None
    assert dims[1]["a"] == {
        "PricingArchitect": None,
        "TrustArchitect": 0.48,
    }
    assert dims[1]["b"] == {"PricingArchitect": None}
    assert parsed["metadata"]["generated_at"] is None


def test_json_export_strict_for_direct_payload() -> None:
    text = project_comparison_to_json(
        {
            "comparison_id": "abc123",
            "generated_at": "2026-08-12T00:00:00Z",
            "summary": {},
            "projects": [],
            "dimensions": [
                {
                    "dimension": "nested",
                    "label": "Nested",
                    "higher_is_better": True,
                    "a": {"score": float("nan")},
                    "b": [float("inf")],
                    "winner": "TIE",
                    "display_a": "",
                    "display_b": "",
                }
            ],
        }
    )

    parsed = _strict_json_loads(text)
    dim = parsed["project_comparison"]["dimensions"][0]
    assert dim["a"] == {"score": None}
    assert dim["b"] == [None]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_brief_has_verdict_projects_and_dimensions() -> None:
    md = project_comparison_to_markdown(_comparison(), metadata=_METADATA)

    assert md.startswith("# Project Comparison")
    assert "## Verdict" in md
    assert "A_LEADS" in md
    assert "winner A (project 1)" in md
    assert "Project A leads on project health" in md
    assert "## Projects Compared" in md
    assert "| A | Project 1 | ACTIVE | 72 | 4.00% | 60.00% | yes | saas |" in md
    assert "## Dimension Comparison" in md
    assert "latest_conversion_rate" in md
    assert "| 4.00% | 3.00% | A |" in md
    assert "## Key Signals" in md
    assert "Overall leader: Project A" in md


def test_markdown_handles_empty_payload() -> None:
    md = project_comparison_to_markdown({})

    assert md.startswith("# Project Comparison")
    assert "No dimension comparison is available." in md
    assert "## Key Signals" not in md


def test_markdown_escapes_table_pipes_in_titles() -> None:
    comparison = _comparison(a=_row(1, title="Acme | Consumer"))
    md = project_comparison_to_markdown(comparison)

    assert "Acme \\| Consumer" in md
    assert "| Acme | Consumer |" not in md
