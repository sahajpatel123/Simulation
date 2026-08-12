"""Tests for the prediction-range coverage export serializers."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest

from app.schemas.prediction_range_coverage import (
    PredictionRangeCoverageOut,
    PredictionRangeCoverageRow,
)
from app.simulation.prediction_range_coverage_export import (
    prediction_range_coverage_to_csv,
    prediction_range_coverage_to_json,
    prediction_range_coverage_to_markdown,
)


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "simulation_id": 1,
            "project_id": 7,
            "predicted_conversion_rate": 0.10,
            "actual_conversion_rate": 0.09,
            "low": 0.05,
            "high": 0.15,
            "history_count": 3,
            "calibration_source": "project",
            "confidence_label": "WELL_CALIBRATED",
            "within": True,
            "margin": 0.0,
            "evaluated": True,
            "created_at": "2026-01-04T00:00:00+00:00",
        },
        {
            "simulation_id": 4,
            "project_id": 7,
            "predicted_conversion_rate": 0.10,
            "actual_conversion_rate": 0.40,
            "low": 0.05,
            "high": 0.15,
            "history_count": 3,
            "calibration_source": "project",
            "confidence_label": "NEEDS_ATTENTION",
            "within": False,
            "margin": 0.25,
            "evaluated": True,
            "created_at": "2026-01-04T00:00:00+00:00",
        },
    ]


def _payload(
    *,
    verdict: str = "NEEDS_ATTENTION",
    worst_miss: dict[str, Any] | None = None,
) -> PredictionRangeCoverageOut:
    return PredictionRangeCoverageOut(
        project_id=7,
        generated_at="2026-08-12T00:00:00+00:00",
        total_project_outcomes=6,
        evaluated_runs=2,
        within_range_count=1,
        coverage_rate=0.5,
        mean_margin=0.25,
        worst_miss=worst_miss
        or {
            "simulation_id": 4,
            "margin": 0.25,
            "actual_conversion_rate": 0.40,
            "low": 0.05,
            "high": 0.15,
        },
        verdict=verdict,
        narrative=(
            "Across 2 out-of-sample run(s), the prediction band contained "
            "actual conversion in 1 (50%)."
        ),
        key_signals=[
            {
                "label": "coverage_rate",
                "value": 0.5,
                "severity": "watch",
                "display": "Band contained actual conversion in 1/2 (50%)",
            },
            {
                "label": "worst_miss_simulation",
                "value": 4,
                "severity": "critical",
                "display": "Worst miss: sim 4",
            },
        ],
        rows=[PredictionRangeCoverageRow(**row) for row in _rows()],
    )


_METADATA = {
    "generated_at": "2026-08-12T00:00:00+00:00",
    "user_id": 42,
    "format_version": "1",
    "project_id": 7,
}


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


def test_csv_has_summary_signals_and_band_check_rows() -> None:
    csv_text = prediction_range_coverage_to_csv(
        _payload(),
        metadata=_METADATA,
    )

    assert "user_id,42" in csv_text
    assert "project_id,7" in csv_text
    assert "section,Prediction Range Coverage Summary" in csv_text
    assert "total_project_outcomes,6" in csv_text
    assert "evaluated_runs,2" in csv_text
    assert "within_range_count,1" in csv_text
    assert "coverage_rate,0.5" in csv_text
    assert "verdict,NEEDS_ATTENTION" in csv_text
    assert "Across 2 out-of-sample run(s)" in csv_text
    assert "section,Key Signals" in csv_text
    assert "coverage_rate,0.5,watch" in csv_text
    assert "section,Out-of-Sample Band Checks" in csv_text
    assert "simulation_id,project_id,predicted_conversion_rate" in csv_text
    assert "1,7,0.1,0.09,0.05,0.15,3,project" in csv_text
    assert "4,7,0.1,0.4,0.05,0.15,3,project" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = prediction_range_coverage_to_csv({})

    assert "section,Prediction Range Coverage Summary" in csv_text
    assert "section,Key Signals" in csv_text
    assert "section,Out-of-Sample Band Checks" in csv_text
    assert "key,value" in csv_text
    assert "label,value,severity,display" in csv_text


def test_csv_neutralises_spreadsheet_formula_injection() -> None:
    payload = _payload(
        verdict="=NEEDS_ATTENTION",
        worst_miss={"simulation_id": "=HYPERLINK(https://example.com)"},
    )
    payload.narrative = "-2+3"
    payload.key_signals[0].display = "=NOW()"
    payload.rows[0].calibration_source = " @project"

    csv_text = prediction_range_coverage_to_csv(
        payload,
        metadata={**_METADATA, "generated_at": "=NOW()"},
    )

    assert "'=NEEDS_ATTENTION" in csv_text
    assert "=HYPERLINK(https://example.com)" in csv_text
    assert "'-2+3" in csv_text
    assert "'=NOW()" in csv_text
    assert "' @project" in csv_text
    parsed_rows = _rows_from_csv(csv_text)
    # The nested formula stays intact inside the worst-miss JSON cell, but
    # that cell starts with ``{`` so it is not an executable formula and is
    # not prefixed.
    assert any(
        cell.startswith("{") and "=HYPERLINK" in cell
        for row in parsed_rows
        for cell in row
    )
    assert not any(
        cell.lstrip().startswith(("=", "+", "-", "@"))
        or cell[:1] in ("\t", "\r", "\n")
        for row in parsed_rows
        for cell in row
    )


@pytest.mark.parametrize(
    "malicious",
    [
        "=HYPERLINK('http://evil')",
        "+cmd",
        "-cmd",
        "@cmd",
        "\tcmd",
        "\rcmd",
        " =cmd",
        " \t=cmd",
        "\n=cmd",
        " \n@cmd",
    ],
)
def test_csv_neutralises_formula_hidden_behind_whitespace_and_controls(
    malicious: str,
) -> None:
    payload = _payload()
    payload.narrative = malicious

    csv_text = prediction_range_coverage_to_csv(payload)
    parsed_rows = _rows_from_csv(csv_text)

    assert any(
        malicious in cell
        for row in parsed_rows
        for cell in row
    )
    assert not any(
        cell.lstrip().startswith(("=", "+", "-", "@"))
        or cell[:1] in ("\t", "\r", "\n")
        for row in parsed_rows
        for cell in row
    )


def test_csv_leaves_embedded_equals_text_unquoted() -> None:
    payload = _payload()
    payload.narrative = "coverage = accuracy"
    payload.rows[0].calibration_source = "project=user"

    csv_text = prediction_range_coverage_to_csv(payload)

    assert "coverage = accuracy" in csv_text
    assert "project=user" in csv_text
    assert "'coverage = accuracy" not in csv_text
    assert "'project=user" not in csv_text


def test_csv_handles_malformed_rows_without_raising() -> None:
    csv_text = prediction_range_coverage_to_csv(
        {
            "rows": [None, "not-a-dict", {"simulation_id": 1}],
            "key_signals": [None, {"label": "ok"}],
        }
    )

    assert "section,Out-of-Sample Band Checks" in csv_text
    assert "simulation_id,project_id" in csv_text
    assert "1,0,,,,,0,,,,,no," in csv_text


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_envelope_includes_metadata_and_payload() -> None:
    text = prediction_range_coverage_to_json(_payload(), metadata=_METADATA)
    parsed = _strict_json_loads(text)

    assert parsed["metadata"]["project_id"] == 7
    assert parsed["metadata"]["user_id"] == 42
    coverage = parsed["prediction_range_coverage"]
    assert coverage["project_id"] == 7
    assert coverage["verdict"] == "NEEDS_ATTENTION"
    assert coverage["coverage_rate"] == 0.5
    assert len(coverage["rows"]) == 2
    assert coverage["rows"][1]["within"] is False


def test_json_export_sanitises_non_finite_values() -> None:
    payload = _payload()
    payload.coverage_rate = float("nan")
    payload.key_signals[0].value = float("inf")
    payload.rows[0].margin = float("nan")

    text = prediction_range_coverage_to_json(
        payload,
        metadata={**_METADATA, "generated_at": float("nan")},
    )

    assert "NaN" not in text
    assert "Infinity" not in text
    parsed = _strict_json_loads(text)
    coverage = parsed["prediction_range_coverage"]
    assert coverage["coverage_rate"] is None
    assert coverage["key_signals"][0]["value"] is None
    assert coverage["rows"][0]["margin"] is None
    assert parsed["metadata"]["generated_at"] is None


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_renders_verdict_summary_rows_and_signals() -> None:
    text = prediction_range_coverage_to_markdown(
        _payload(),
        metadata=_METADATA,
    )

    assert text.startswith("# Prediction Range Coverage")
    assert "## Verdict" in text
    assert "**NEEDS_ATTENTION**" in text
    assert "## Summary" in text
    assert "| Coverage rate | 50.00% |" in text
    assert "| Worst miss | Simulation 4 (margin 0.2500) |" in text
    assert "## Out-of-Sample Band Checks" in text
    assert "| 1 | 10.00% | 9.00% | 5.00% – 15.00% | yes |" in text
    assert "| 4 | 10.00% | 40.00% | 5.00% – 15.00% | no | 0.2500" in text
    assert "## Key Signals" in text
    assert "Worst miss: sim 4" in text


def test_markdown_escapes_pipes_and_newlines() -> None:
    payload = _payload(verdict="WATCH|OUT")
    payload.rows[0].calibration_source = "project | user"
    payload.narrative = "Line one\nLine two"

    text = prediction_range_coverage_to_markdown(payload)

    assert "WATCH\\|OUT" in text
    assert "project \\| user" in text
    assert "Line one Line two" in text
    assert "|" in text


def test_markdown_empty_payload_still_has_headers() -> None:
    text = prediction_range_coverage_to_markdown({})

    assert "## Verdict" in text
    assert "## Summary" in text
    assert "## Out-of-Sample Band Checks" in text
    assert "| Simulation | Predicted | Actual |" in text
