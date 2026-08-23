"""Tests for the evidence-quality CSV/JSON/Markdown exports.

The exporters reuse the exact payload produced by the evidence-quality
grader; these tests pin the multi-section CSV layout (native numeric
cells, no formula injection, flattened scoring meta), the stable JSON
envelope, and the founder-facing Markdown brief, plus the export
route's format validation and wiring.
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

from app.simulation.evidence_quality import build_evidence_quality
from app.simulation.evidence_quality_export import (
    FORMAT_VERSION,
    evidence_quality_to_csv,
    evidence_quality_to_json,
    evidence_quality_to_markdown,
)

_METADATA = {
    "generated_at": "2026-08-23T10:05:00+00:00",
    "user_id": 42,
    "project_id": 5,
    "format_version": FORMAT_VERSION,
}

_NOW_ANCHOR = datetime(2026, 8, 23, tzinfo=UTC)


def _asm(id_: int, text: str, category: str = "Pricing"):
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
        created_at=_NOW_ANCHOR - timedelta(days=age_days),
    )


def _card() -> dict:
    """One high-trust pricing claim + one low-trust demand claim."""
    assumptions = [
        _asm(1, "Users will pay ₹999 monthly", "Pricing"),
        _asm(2, "=cmd flimsy claim", "Demand"),
    ]
    evidence = [
        _ev(1, id_=1),
        _ev(
            2,
            id_=2,
            result="INCONCLUSIVE",
            method="COMPETITIVE_DESK_RESEARCH",
            observed_metric=None,
            age_days=120,
        ),
    ]
    return build_evidence_quality(
        project_id=5, assumptions=assumptions, evidence=evidence
    )


def test_format_version_is_stable() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_sections_summary_and_rows() -> None:
    text = evidence_quality_to_csv(_card(), metadata=_METADATA)
    lines = text.splitlines()

    assert lines[0] == "generated_at,2026-08-23T10:05:00+00:00"
    assert lines[2] == "project_id,5"

    assert "section,Quality Summary" in lines
    assert "tested_count,2" in lines
    assert "untested_count,0" in lines
    index_row = next(
        line
        for line in lines
        if line.startswith("evidence_quality_index,")
    )
    assert float(index_row.split(",", 1)[1]) > 0

    assert "section,Assumption Quality" in lines
    # Lowest-quality assumption sorts first in the table too.
    table = text.split("section,Assumption Quality")[1].split("section,")[0]
    first_data = table.splitlines()[2]
    assert first_data.startswith("2,")

    assert "section,Weakest Link" in lines
    assert "Assumption ID,2" in text
    assert "section,Narrative" in lines


def test_csv_meta_is_flattened_with_dotted_keys() -> None:
    text = evidence_quality_to_csv(_card(), metadata=_METADATA)
    lines = text.splitlines()

    assert "section,Quality Meta" in lines
    assert "model,evidence_quality_v1" in lines
    assert "method_reliability.CONCIERGE_MVP,1.0" in lines
    assert "fresh_days,30" in lines
    # The nested dict must never be dumped as one ugly repr cell.
    assert not any(line.startswith("meta,") for line in lines)


def test_csv_keeps_numerics_native_and_guards_text() -> None:
    text = evidence_quality_to_csv(_card(), metadata=_METADATA)

    # Quality/reliability stay real numbers so spreadsheets can compute…
    assert "'1.0," not in text
    assert ",HIGH," in text
    # …while hostile free-form text is neutralised.
    assert "'=cmd flimsy claim" in text


def test_json_envelope_is_strict_and_stable() -> None:
    parsed = json.loads(evidence_quality_to_json(_card(), metadata=_METADATA))

    assert set(parsed) == {"metadata", "evidence_quality"}
    body = parsed["evidence_quality"]
    assert body["tested_count"] == 2
    assert body["rows"][0]["assumption_id"] == 2  # lowest quality first
    assert parsed["metadata"]["format_version"] == "1"


def test_markdown_brief_tables_weakest_link_and_footer() -> None:
    md = evidence_quality_to_markdown(_card(), metadata=_METADATA)

    assert md.startswith("# Evidence Quality")
    assert "| Tested | 2 |" in md
    assert "| Untested | 0 |" in md
    assert "## Weakest Link" in md
    assert "**“=cmd flimsy claim”**" in md
    assert "(LOW)" in md
    assert "## Assumption Quality" in md
    assert "| Reliability | Age (d) | Quality | Label |" in md
    assert md.rstrip().endswith(
        "*Evidence quality · Project 5 · Generated 2026-08-23T10:05:00+00:00*"
    )


def test_markdown_handles_empty_payload() -> None:
    empty = build_evidence_quality(project_id=5, assumptions=[], evidence=[])
    md = evidence_quality_to_markdown(empty, metadata=dict(_METADATA))
    assert "# Evidence Quality" in md
    assert "## Assumption Quality" not in md
    assert "## Weakest Link" not in md
    assert "**No experiments logged yet" in md


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
    path = "/projects/{project_id}/evidence-quality/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_round_trip_all_formats(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod
    from app.schemas.evidence_quality import EvidenceQualityOut

    captured: dict = {}

    def _fake_quality(**kwargs):
        captured.update(kwargs)
        return EvidenceQualityOut(**_card())

    monkeypatch.setattr(ev_mod, "get_evidence_quality", _fake_quality)

    for fmt, media, suffix in (
        ("csv", "text/csv", ".csv"),
        ("json", "application/json", ".json"),
        ("md", "text/markdown", ".md"),
    ):
        response = ev_mod.export_evidence_quality(
            project_id=5,
            format=fmt,
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
        assert media in response.media_type
        assert (
            f'filename="evidence-quality-5{suffix}"'
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

    monkeypatch.setattr(ev_mod, "get_evidence_quality", _fail)

    with pytest.raises(HTTPException) as exc:
        ev_mod.export_evidence_quality(
            project_id=5,
            format="xlsx",
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
    assert called["n"] == 0
