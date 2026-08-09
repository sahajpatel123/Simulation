"""Tests for the pure readings-export helper."""
from __future__ import annotations

import json

from app.simulation.readings_export import (
    readings_count_to_csv,
    readings_payload,
    readings_to_csv,
)


def test_readings_to_csv_contains_header_and_row() -> None:
    csv_text = readings_to_csv(
        {
            "project_id": 10,
            "readings_json": json.dumps(
                {
                    "readings": [
                        {"label": "WHAT IT IS", "body": "A lean tool"},
                        {"label": "HIDDEN TENSION", "body": "No pricing"},
                    ],
                    "ledger": {
                        "deck_line": "Small desk tool",
                        "section_rubric": "SaaS",
                    },
                }
            ),
        },
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,10" in csv_text
    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "format_version,2" in csv_text
    assert "index,label,body" in csv_text
    assert "1,WHAT IT IS,A lean tool" in csv_text
    assert "2,HIDDEN TENSION,No pricing" in csv_text
    assert "key,value" in csv_text
    assert "deck_line,Small desk tool" in csv_text
    assert "section_rubric,SaaS" in csv_text


def test_readings_to_csv_handles_missing_fields() -> None:
    csv_text = readings_to_csv({"project_id": 10})

    assert "project_id,10" in csv_text
    assert "index,label,body" in csv_text


def test_readings_to_csv_handles_legacy_bare_array() -> None:
    csv_text = readings_to_csv(
        {
            "project_id": 11,
            "readings_json": '[{"label":"WHAT IT IS","body":"Lean"}]',
        }
    )

    assert "1,WHAT IT IS,Lean" in csv_text
    assert "key,value" not in csv_text


def test_readings_to_csv_tolerates_malformed_json() -> None:
    csv_text = readings_to_csv(
        {"project_id": 12, "readings_json": "{not valid json"}
    )

    assert "project_id,12" in csv_text
    assert "index,label,body" in csv_text
    assert "1," not in csv_text
    assert "key,value" not in csv_text


def test_readings_to_csv_handles_none_payload() -> None:
    csv_text = readings_to_csv({"project_id": 13, "readings_json": None})

    assert "project_id,13" in csv_text
    assert "index,label,body" in csv_text


def test_readings_to_csv_handles_preparsed_list() -> None:
    csv_text = readings_to_csv(
        {
            "project_id": 14,
            "readings_json": [{"label": "UNTESTED CLAIM", "body": "Needs evidence"}],
        }
    )

    assert "1,UNTESTED CLAIM,Needs evidence" in csv_text


def test_readings_payload_normalises_legacy_bare_array() -> None:
    payload = readings_payload('[{"label":"WHAT IT IS","body":"Lean"}]')

    assert payload["readings"] == [{"label": "WHAT IT IS", "body": "Lean"}]
    assert payload["ledger"] == {}


def test_readings_payload_tolerates_malformed_json() -> None:
    payload = readings_payload("{not valid json")

    assert payload["readings"] == []
    assert payload["ledger"] == {}


def test_readings_payload_handles_none() -> None:
    payload = readings_payload(None)

    assert payload["readings"] == []
    assert payload["ledger"] == {}


def test_readings_payload_drops_fully_blank_entries() -> None:
    payload = readings_payload(
        {
            "readings": [
                {"label": "WHAT IT IS", "body": "Lean"},
                {"label": "   ", "body": ""},
                {"label": "", "body": "\n"},
                {"label": "HIDDEN TENSION", "body": ""},
                {"label": "", "body": "No pricing"},
                "not-a-dict",
                {"label": 5, "body": 6},
            ],
            "ledger": {"deck_line": "Small desk tool"},
        }
    )

    assert payload["readings"] == [
        {"label": "WHAT IT IS", "body": "Lean"},
        {"label": "HIDDEN TENSION", "body": ""},
        {"label": "", "body": "No pricing"},
    ]
    assert payload["ledger"] == {"deck_line": "Small desk tool"}


def test_readings_payload_drops_blank_entries_from_json_string() -> None:
    payload = readings_payload(
        '[{"label": " ", "body": " "}, {"label": "", "body": ""},'
        ' {"label": "ONLY LABEL", "body": ""}]'
    )

    assert payload["readings"] == [{"label": "ONLY LABEL", "body": ""}]


def test_readings_to_csv_skips_blank_entries() -> None:
    csv_text = readings_to_csv(
        {
            "project_id": 15,
            "readings_json": [
                {"label": " ", "body": ""},
                {"label": "REAL", "body": "Reading"},
            ],
        }
    )

    assert "1,REAL,Reading" in csv_text
    assert "1,," not in csv_text


def test_readings_count_to_csv_contains_header_and_row() -> None:
    csv_text = readings_count_to_csv(
        {"project_id": 10, "readings_count": 2},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,readings_count" in csv_text
    assert "10,2" in csv_text
    assert "generated_at,now" in csv_text
    assert "user_id,42" in csv_text
    assert "format_version,1" in csv_text
