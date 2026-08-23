"""Unit tests for the batch what-if export rendering helpers."""
from __future__ import annotations

import csv
import io
import json

from app.schemas.what_if import WhatIfOut, WhatIfSummary
from app.schemas.what_if_batch import (
    WhatIfBatchOut,
    WhatIfBatchScenarioOut,
)
from app.simulation.what_if_batch_export import (
    what_if_batch_to_csv,
    what_if_batch_to_json,
    what_if_batch_to_markdown,
)


def _scenario(
    *,
    label: str,
    conversion_delta: float = 0.01,
    conversion_delta_pct: float = 1.5,
    categories: list[str] | None = None,
) -> WhatIfOut:
    return WhatIfOut(
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        base_conversion_rate=0.05,
        projected_conversion_rate=0.06,
        conversion_delta=conversion_delta,
        conversion_delta_pct=conversion_delta_pct,
        meta={
            "dominant_direction": "POSITIVE",
            "sensitivity_label": "HIGH",
            "matched_keyword_categories": categories or ["demand"],
        },
    )


def _batch(
    scenarios: list[tuple[str, WhatIfOut]],
    *,
    direction_breakdown: dict[str, int] | None = None,
) -> WhatIfBatchOut:
    ranked = [
        WhatIfBatchScenarioOut(rank=idx + 1, label=label, scenario=scenario)
        for idx, (label, scenario) in enumerate(scenarios)
    ]
    summary = WhatIfSummary(
        scenario_count=len(ranked),
        avg_delta=0.01,
        best_delta=0.01,
        worst_delta=-0.01,
        direction_breakdown=direction_breakdown
        or {"POSITIVE": 1, "NEGATIVE": 1},
        top_categories=[
            {"category": "demand", "count": 2},
            {"category": "pricing", "count": 1},
        ],
    )
    return WhatIfBatchOut(
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        summary=summary,
        scenarios=ranked,
        best_scenario=ranked[0] if ranked else None,
        worst_scenario=ranked[-1] if ranked else None,
        meta={"scenario_count": len(ranked)},
    )


def test_markdown_escapes_pipe_and_newline_in_table_cells() -> None:
    payload = _batch(
        [
            (
                "Pricing | Demand",
                _scenario(label="Pricing | Demand", categories=["pricing", "tiers | plans"]),
            )
        ]
    )

    body = what_if_batch_to_markdown(payload)

    assert "Pricing \\| Demand" in body
    assert "pricing, tiers \\| plans" in body


def test_markdown_summary_escapes_direction_and_category_pipes() -> None:
    payload = _batch(
        [("demand", _scenario(label="demand"))],
        direction_breakdown={"POSITIVE": 2, "NEGATIVE": 1},
    )

    body = what_if_batch_to_markdown(payload)

    assert "POSITIVE:2\\|NEGATIVE:1" in body
    assert "demand:2\\|pricing:1" in body


def test_markdown_empty_scenarios_render_placeholder() -> None:
    payload = _batch([])

    body = what_if_batch_to_markdown(payload)

    assert "_No scenarios returned._" in body
    assert "## Best Scenario" not in body
    assert "## Worst Scenario" not in body


def test_csv_guards_formula_injection_in_labels_and_categories() -> None:
    payload = _batch(
        [
            (
                "=SUM(A1)",
                _scenario(
                    label="=SUM(A1)",
                    categories=['=HYPERLINK("http://bad")'],
                ),
            )
        ]
    )

    body = what_if_batch_to_csv(payload)
    rows = list(csv.reader(io.StringIO(body)))
    cells = [cell for row in rows for cell in row]

    assert any(cell == "'=SUM(A1)" for cell in cells)
    assert any(cell == '\'=HYPERLINK("http://bad")' for cell in cells)


def test_csv_scenario_row_is_aligned_for_plain_dict_payload() -> None:
    payload = {
        "simulation_id": 1,
        "project_id": 10,
        "status": "COMPLETED",
        "summary": {
            "scenario_count": 1,
            "avg_delta": 0.01,
            "best_delta": 0.01,
            "worst_delta": 0.01,
            "direction_breakdown": {"POSITIVE": 1},
            "top_categories": [{"category": "demand", "count": 1}],
        },
        "scenarios": [
            {
                "rank": 1,
                "label": "demand",
                "scenario": {
                    "simulation_id": 1,
                    "project_id": 10,
                    "status": "COMPLETED",
                    "base_conversion_rate": 0.05,
                    "projected_conversion_rate": 0.06,
                    "conversion_delta": 0.01,
                    "conversion_delta_pct": 1.5,
                    "meta": {
                        "dominant_direction": "POSITIVE",
                        "sensitivity_label": "HIGH",
                        "matched_keyword_categories": ["demand", "pricing"],
                    },
                },
            }
        ],
        "best_scenario": None,
        "worst_scenario": None,
        "meta": {},
    }

    body = what_if_batch_to_csv(payload)
    rows = list(csv.reader(io.StringIO(body)))
    ranked_header_idx = next(
        idx for idx, row in enumerate(rows) if row == ["section", "Ranked Scenarios"]
    )
    header = rows[ranked_header_idx + 1]
    first_row = rows[ranked_header_idx + 2]

    assert header == [
        "rank",
        "label",
        "simulation_id",
        "project_id",
        "base_conversion_rate",
        "projected_conversion_rate",
        "conversion_delta",
        "conversion_delta_pct",
        "dominant_direction",
        "sensitivity_label",
        "matched_keyword_categories",
    ]
    assert len(first_row) == len(header)
    assert first_row == [
        "1",
        "demand",
        "1",
        "10",
        "0.05",
        "0.06",
        "0.01",
        "1.5",
        "POSITIVE",
        "HIGH",
        "demand|pricing",
    ]


def test_json_export_wraps_payload_with_metadata() -> None:
    payload = _batch([("demand", _scenario(label="demand"))])

    body = what_if_batch_to_json(payload, metadata={"simulation_id": 1})
    parsed = json.loads(body)

    assert parsed["metadata"] == {"simulation_id": 1}
    assert parsed["what_if_batch"]["summary"]["scenario_count"] == 1
    assert parsed["what_if_batch"]["scenarios"][0]["label"] == "demand"
