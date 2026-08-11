"""Pure-helper tests for the go/no-go CSV/JSON export module."""

from __future__ import annotations

import csv
import io
import json

from app.schemas.go_no_go import GoNoGoOut
from app.simulation.go_no_go_export import (
    go_no_go_to_csv,
    go_no_go_to_json,
)


def _payload() -> dict:
    return {
        "project_id": 10,
        "latest_simulation_id": 7,
        "go_no_go_score": 82,
        "verdict": "GO",
        "verdict_label": "Signals support launch",
        "pillars": [
            {
                "key": "readiness",
                "label": "Launch readiness",
                "score": 88,
                "verdict": "STRONG",
                "weight": 0.2,
                "evidence": [
                    "Launch-checklist readiness 88/100 (READY)",
                    "Top recommendation: Close the top gap",
                ],
                "summary": "Launch signals are ready",
            },
            {
                "key": "premortem",
                "label": "Risk posture",
                "score": 74,
                "verdict": "MODERATE",
                "weight": 0.25,
                "evidence": ["1 CRITICAL failure mode"],
                "summary": "Risk posture is bounded",
            },
        ],
        "gates": [
            {
                "id": "readiness_gate",
                "label": "Launch readiness is strong enough",
                "evaluated": True,
                "passed": True,
                "detail": "Launch-checklist readiness must reach 80/100",
            },
            {
                "id": "risk_gate",
                "label": "Premortem risk is bounded",
                "evaluated": True,
                "passed": True,
                "detail": "At most one CRITICAL premortem failure mode",
            },
        ],
        "strengths": ["Readiness is strong", "No critical risks"],
        "risks": ["Coverage is thin"],
        "top_actions": ["Close the top launch-checklist gap"],
        "narrative": (
            "Signals support launch (go/no-go 82/100); 2 gates passed."
        ),
        "meta": {
            "total_pillars": 2,
            "scored_pillars": 2,
        },
    }


def _metadata() -> dict:
    return {
        "generated_at": "2026-08-12T12:00:00+00:00",
        "project_id": 10,
        "user_id": 42,
        "format_version": "1",
    }


def test_csv_contains_metadata_and_summary() -> None:
    csv_text = go_no_go_to_csv(_payload(), metadata=_metadata())

    assert csv_text.startswith("\ufeff")
    assert "generated_at,2026-08-12T12:00:00+00:00" in csv_text
    assert "project_id,10" in csv_text
    assert "user_id,42" in csv_text
    assert "format_version,1" in csv_text
    assert "section,Go/No-Go Summary" in csv_text
    assert "go_no_go_score,82" in csv_text
    assert "verdict,GO" in csv_text
    assert "verdict_label,Signals support launch" in csv_text
    assert "pillar_count,2" in csv_text
    assert "gate_count,2" in csv_text
    assert "strengths_count,2" in csv_text
    assert "risks_count,1" in csv_text
    assert "action_count,1" in csv_text
    assert "narrative,Signals support launch (go/no-go 82/100)" in csv_text


def test_csv_renders_pillars_gates_and_action_lists() -> None:
    csv_text = go_no_go_to_csv(_payload())

    assert "section,Pillars" in csv_text
    assert (
        "key,label,score,verdict,weight,summary,evidence" in csv_text
    )
    assert "readiness,Launch readiness,88,STRONG,0.2" in csv_text
    assert "Close the top gap" in csv_text
    assert "section,Launch Gates" in csv_text
    assert "id,label,evaluated,passed,detail" in csv_text
    assert "readiness_gate,Launch readiness is strong enough,True,True" in csv_text
    assert "section,Strengths" in csv_text
    assert "Readiness is strong" in csv_text
    assert "section,Risks" in csv_text
    assert "Coverage is thin" in csv_text
    assert "section,Top Actions" in csv_text
    assert "1,Close the top launch-checklist gap" in csv_text
    assert "section,Meta" in csv_text
    assert "total_pillars,2" in csv_text


def test_csv_empty_payload_keeps_sections_and_headers() -> None:
    csv_text = go_no_go_to_csv(
        {
            "project_id": 7,
            "latest_simulation_id": None,
            "go_no_go_score": None,
            "verdict": "INSUFFICIENT_DATA",
            "verdict_label": "Insufficient data",
            "pillars": [],
            "gates": [],
            "strengths": [],
            "risks": [],
            "top_actions": [],
            "narrative": "",
            "meta": {},
        }
    )

    assert "section,Go/No-Go Summary" in csv_text
    assert "go_no_go_score,\n" in csv_text
    assert "pillar_count,0" in csv_text
    assert "section,Pillars" in csv_text
    assert "key,label,score,verdict,weight,summary,evidence" in csv_text
    assert "section,Launch Gates" in csv_text
    assert "id,label,evaluated,passed,detail" in csv_text
    assert "section,Strengths" in csv_text
    assert "section,Risks" in csv_text
    assert "section,Top Actions" in csv_text
    assert "section,Meta" in csv_text


def test_csv_neutralizes_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["narrative"] = '=HYPERLINK("http://evil")'
    payload["top_actions"] = ["  +SUM(A1:A9)"]

    csv_text = go_no_go_to_csv(payload)

    assert "'=HYPERLINK(" in csv_text
    assert "'  +SUM(A1:A9)" in csv_text
    assert "http://evil" in csv_text


def test_csv_skips_malformed_pillar_and_gate_rows() -> None:
    payload = _payload()
    payload["pillars"] = [None, "junk", payload["pillars"][0]]
    payload["gates"] = [None, payload["gates"][0]]

    csv_text = go_no_go_to_csv(payload)

    assert "junk" not in csv_text
    assert "readiness,Launch readiness,88,STRONG,0.2" in csv_text
    assert "readiness_gate,Launch readiness is strong enough,True,True" in csv_text


def test_csv_counts_match_rendered_rows_when_items_are_malformed() -> None:
    payload = _payload()
    payload["pillars"] = [
        None,
        "junk",
        payload["pillars"][0],
        payload["pillars"][1],
    ]
    payload["gates"] = {"readiness_gate": payload["gates"][0]}

    csv_text = go_no_go_to_csv(payload)

    # Only renderable items are counted, so the summary never promises
    # rows the sections do not actually contain.
    assert "pillar_count,2" in csv_text
    assert "gate_count,0" in csv_text
    assert "junk" not in csv_text


def test_csv_drops_non_string_list_items() -> None:
    payload = _payload()
    payload["strengths"] = [
        "Readiness is strong",
        {"key": "value"},
        ["nested"],
        None,
    ]
    payload["risks"] = ["Coverage is thin", 3]

    csv_text = go_no_go_to_csv(payload)
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))

    assert "strengths_count,1" in csv_text
    assert "risks_count,2" in csv_text
    assert "'key': 'value'" not in csv_text
    assert "['nested']" not in csv_text

    in_strengths = False
    strength_cells: list[str] = []
    for row in rows:
        if row and row[0] == "section":
            in_strengths = row[1] == "Strengths"
            continue
        if in_strengths:
            if not row:
                break
            if row[0] == "strength":
                continue
            strength_cells.append(row[0])
    assert strength_cells == ["Readiness is strong"]


def test_csv_metadata_none_values_render_empty() -> None:
    csv_text = go_no_go_to_csv(
        _payload(),
        metadata={
            "generated_at": None,
            "project_id": 10,
            "user_id": None,
            "format_version": None,
        },
    )

    assert "generated_at,\n" in csv_text
    assert "user_id,\n" in csv_text
    assert "format_version,\n" in csv_text


def test_json_round_trips_pydantic_payload() -> None:
    model = GoNoGoOut(**_payload())

    json_text = go_no_go_to_json(model, metadata=_metadata())
    parsed = json.loads(json_text)

    assert parsed["metadata"]["user_id"] == 42
    go_no_go = parsed["go_no_go"]
    assert go_no_go["go_no_go_score"] == 82
    assert go_no_go["verdict"] == "GO"
    assert len(go_no_go["pillars"]) == 2
    assert go_no_go["gates"][0]["passed"] is True
    assert go_no_go["top_actions"][0] == "Close the top launch-checklist gap"


def test_json_preserves_unicode_and_ends_with_newline() -> None:
    payload = _payload()
    payload["narrative"] = "⚠️ 高风险合规"

    json_text = go_no_go_to_json(payload)

    assert json_text.endswith("\n")
    assert "⚠️ 高风险合规" in json_text
    parsed = json.loads(json_text)
    assert parsed["go_no_go"]["narrative"] == "⚠️ 高风险合规"
