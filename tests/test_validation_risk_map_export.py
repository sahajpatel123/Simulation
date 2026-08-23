"""Tests for the validation risk-map CSV/JSON/Markdown exports.

The exporters reuse the exact payload produced by the risk-map builder;
these tests pin the multi-section CSV layout (native numeric cells, no
formula injection, flattened scoring meta), the stable JSON envelope,
and the founder-facing Markdown brief, plus the export route's format
validation and wiring.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.validation_risk_map import build_validation_risk_map
from app.simulation.validation_risk_map_export import (
    FORMAT_VERSION,
    validation_risk_map_to_csv,
    validation_risk_map_to_json,
    validation_risk_map_to_markdown,
)

_METADATA = {
    "generated_at": "2026-08-23T14:05:00+00:00",
    "user_id": 42,
    "project_id": 5,
    "format_version": FORMAT_VERSION,
}

_NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _asm(id_: int, text: str, category: str | None = "Pricing"):
    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(
    assumption_id: int,
    *,
    id_: int = 1,
    result: str = "PASS",
    method: str = "CONCIERGE_MVP",
    observed_metric: float | None = 0.65,
    age_days: int = 1,
):
    return SimpleNamespace(
        assumption_id=assumption_id,
        id=id_,
        result=result,
        method=method,
        observed_metric=observed_metric,
        created_at=_NOW - timedelta(days=age_days),
    )


def _card() -> dict:
    """One risky pricing category + one healthy demand category."""
    assumptions = [
        _asm(1, "=cmd hostile pricing claim", "Pricing"),
        _asm(2, "Users want this workflow", "Demand"),
        _asm(3, "Churn stays under 5%", "Pricing"),
    ]
    evidence = [
        _ev(
            1,
            id_=1,
            result="FAIL",
            method="WILLINGNESS_TO_PAY_SURVEY",
            observed_metric=0.10,
        ),
        _ev(2, id_=2),
    ]
    return build_validation_risk_map(
        project_id=5, assumptions=assumptions, evidence=evidence, now=_NOW
    )


def test_format_version_is_stable() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_sections_summary_and_ranked_rows() -> None:
    text = validation_risk_map_to_csv(_card(), metadata=_METADATA)
    lines = text.splitlines()

    assert lines[0] == "generated_at,2026-08-23T14:05:00+00:00"
    assert lines[2] == "project_id,5"

    assert "section,Risk Summary" in lines
    assert "killed_count,1" in lines
    assert "untested_count,1" in lines
    assert "riskiest_category,Pricing" in lines

    assert "section,Category Risk" in lines
    # Highest-risk category sorts first in the table too.
    table = text.split("section,Category Risk")[1].split("section,")[0]
    first_data = table.splitlines()[2]
    assert first_data.startswith("Pricing,")

    assert "section,Narrative" in lines


def test_csv_meta_flattens_weights_and_sources() -> None:
    text = validation_risk_map_to_csv(_card(), metadata=_METADATA)
    lines = text.splitlines()

    assert "section,Risk Map Meta" in lines
    assert "model,validation_risk_map_v1" in lines
    assert "risk_weights.killed,1.0" in lines
    assert "risk_weights.untested,0.5" in lines
    assert "sources,evidence_verdicts_v1; evidence_quality_v1" in lines
    # Nested structures must never be dumped as one ugly repr cell.
    assert not any("risk_weights,{'" in line for line in lines)


def test_csv_keeps_numerics_native_and_guards_text() -> None:
    text = validation_risk_map_to_csv(_card(), metadata=_METADATA)

    # Scores and counts stay real numbers so spreadsheets can compute
    # (risk_score is the row's final column)…
    assert "'0.8" not in text
    assert ",0.8\n" in text
    # …while hostile free-form text is neutralised.
    assert "'=cmd hostile pricing claim" in text


def test_json_envelope_is_strict_and_stable() -> None:
    parsed = json.loads(
        validation_risk_map_to_json(_card(), metadata=_METADATA)
    )

    assert set(parsed) == {"metadata", "validation_risk_map"}
    body = parsed["validation_risk_map"]
    assert body["riskiest_category"] == "Pricing"
    assert body["categories"][0]["category"] == "Pricing"
    assert parsed["metadata"]["format_version"] == "1"


def test_markdown_brief_tables_and_footer() -> None:
    md = validation_risk_map_to_markdown(_card(), metadata=_METADATA)

    assert md.startswith("# Validation Risk Map")
    assert "| Riskiest category | Pricing |" in md
    assert "| Killed | 1 |" in md
    assert "## Category Risk" in md
    assert "| Mean Quality | Risk |" in md
    assert "**Pricing carries the most validation risk:" in md
    assert md.rstrip().endswith(
        "*Validation risk map · Project 5 · "
        "Generated 2026-08-23T14:05:00+00:00*"
    )


def test_markdown_handles_empty_payload() -> None:
    empty = build_validation_risk_map(
        project_id=5, assumptions=[], evidence=[]
    )
    md = validation_risk_map_to_markdown(empty, metadata=dict(_METADATA))
    assert "# Validation Risk Map" in md
    assert "## Category Risk" not in md
    assert "**No assumptions to map yet.**" in md


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


async def _drain(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_export_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/validation-risk-map/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_round_trip_all_formats(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod
    from app.schemas.validation_risk_map import ValidationRiskMapOut

    captured: dict = {}

    def _fake_map(**kwargs):
        captured.update(kwargs)
        return ValidationRiskMapOut(**_card())

    monkeypatch.setattr(ev_mod, "get_validation_risk_map", _fake_map)

    for fmt, media, suffix in (
        ("csv", "text/csv", ".csv"),
        ("json", "application/json", ".json"),
        ("md", "text/markdown", ".md"),
    ):
        response = ev_mod.export_validation_risk_map(
            project_id=5,
            format=fmt,
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
        assert media in response.media_type
        assert (
            f'filename="validation-risk-map-5{suffix}"'
            in response.headers["Content-Disposition"]
        )
        assert int(response.headers["Content-Length"]) > 0
        body = asyncio.run(_drain(response))
        if fmt == "json":
            json.loads(body.decode())
        else:
            assert len(body) > 0

    assert captured["project_id"] == 5


def test_export_route_rejects_unknown_format(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api.v1 import assumption_evidence as ev_mod

    called = {"n": 0}

    def _fail(**kwargs):
        called["n"] += 1
        raise AssertionError("builder must not run before validation")

    monkeypatch.setattr(ev_mod, "get_validation_risk_map", _fail)

    with pytest.raises(HTTPException) as exc:
        ev_mod.export_validation_risk_map(
            project_id=5,
            format="xlsx",
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
    assert called["n"] == 0
