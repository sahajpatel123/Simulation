"""Tests for the evidence-verdicts CSV/JSON/Markdown exports.

The exporters reuse the exact payload produced by the verdicts builder;
these tests pin the multi-section CSV layout (native numeric cells, no
formula injection), the stable JSON envelope, and the founder-facing
Markdown brief, plus the export route's format validation and wiring.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.evidence_verdicts import build_evidence_verdicts
from app.simulation.evidence_verdicts_export import (
    FORMAT_VERSION,
    evidence_verdicts_to_csv,
    evidence_verdicts_to_json,
    evidence_verdicts_to_markdown,
)

_METADATA = {
    "generated_at": "2026-08-23T09:15:00+00:00",
    "user_id": 42,
    "project_id": 5,
    "format_version": FORMAT_VERSION,
}


def _asm(id_: int, text: str, category: str = "PRICING"):
    from types import SimpleNamespace

    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(assumption_id: int, *, id_: int, result: str, method: str,
        observed_metric: float | None):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    return SimpleNamespace(
        assumption_id=assumption_id,
        id=id_,
        result=result,
        method=method,
        observed_metric=observed_metric,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _card() -> dict:
    """One on-track pricing claim + one killed demand claim."""
    assumptions = [
        _asm(1, "Users will pay ₹999", "PRICING"),
        _asm(2, "Landing converts", "DEMAND"),
    ]
    evidence = [
        _ev(
            1,
            id_=1,
            result="PASS",
            method="WILLINGNESS_TO_PAY_SURVEY",
            observed_metric=0.42,
        ),
        _ev(
            2,
            id_=2,
            result="FAIL",
            method="LANDING_PAGE_SMOKE_TEST",
            observed_metric=0.01,
        ),
    ]
    return build_evidence_verdicts(
        project_id=5, assumptions=assumptions, evidence=evidence
    )


def test_format_version_is_stable() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_sections_and_native_negative_numbers() -> None:
    text = evidence_verdicts_to_csv(_card(), metadata=_METADATA)
    lines = text.splitlines()

    assert lines[0] == "generated_at,2026-08-23T09:15:00+00:00"
    assert lines[1] == "user_id,42"
    assert lines[2] == "project_id,5"
    assert lines[3] == "format_version,1"
    assert lines[4] == ""

    assert "Verdict Summary" in lines
    assert "on_track_count,1" in lines
    assert "killed_count,1" in lines
    assert "Assumption Verdicts" in lines
    assert "Next Action" in lines
    assert "hit a kill bar" in text
    assert "Verdicts Meta" in lines

    # The killed row's margin stays a native negative number — the formula
    # guard must not apostrophe-escape it into spreadsheet text.
    assert ",-2.0," in text
    assert "'-2.0" not in text


def test_csv_guards_formula_leading_assumption_text() -> None:
    hostile = build_evidence_verdicts(
        project_id=5,
        assumptions=[_asm(9, "=cmd|' /C calc", "PRICING")],
        evidence=[
            _ev(
                9,
                id_=9,
                result="PASS",
                method="WILLINGNESS_TO_PAY_SURVEY",
                observed_metric=0.5,
            )
        ],
    )
    guarded = evidence_verdicts_to_csv(hostile, metadata=_METADATA)
    assert "'=cmd|' /C calc" in guarded


def test_json_envelope_is_strict_and_stable() -> None:
    parsed = json.loads(evidence_verdicts_to_json(_card(), metadata=_METADATA))

    assert set(parsed) == {"metadata", "evidence_verdicts"}
    body = parsed["evidence_verdicts"]
    assert body["total_assumptions"] == 2
    # Attention order: the kill lands first.
    assert body["rows"][0]["verdict"] == "KILLED"
    assert parsed["metadata"]["format_version"] == "1"


def test_markdown_brief_tables_and_footer() -> None:
    md = evidence_verdicts_to_markdown(_card(), metadata=_METADATA)

    assert md.startswith("# Evidence Verdicts")
    assert "| On track | 1 |" in md
    assert (
        "| 1 | Landing converts | DEMAND | 1 | FAIL "
        "| Landing-page smoke test | 3.0% | 1.0% | -2.00pp | KILLED |"
    ) in md
    assert (
        "| 2 | Users will pay ₹999 | PRICING | 1 | PASS "
        "| Willingness-to-pay survey | 30.0% | 42.0% | +12.00pp | ON_TRACK |"
    ) in md
    assert "**2 assumption(s) hit a kill bar" in md
    assert md.rstrip().endswith(
        "*Evidence verdicts · Project 5 · Generated 2026-08-23T09:15:00+00:00*"
    )


def test_markdown_handles_empty_payload() -> None:
    empty = build_evidence_verdicts(project_id=5, assumptions=[], evidence=[])
    md = evidence_verdicts_to_markdown(empty, metadata=dict(_METADATA))
    assert "# Evidence Verdicts" in md
    assert "## Verdicts" not in md
    assert "**Import or create assumptions to start validating.**" in md


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
    path = "/projects/{project_id}/evidence-verdicts/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_round_trip_all_formats(monkeypatch) -> None:
    from app.schemas.evidence_verdicts import EvidenceVerdictsOut
    from app.api.v1 import assumption_evidence as ev_mod

    captured: dict = {}

    def _fake_verdicts(**kwargs):
        captured.update(kwargs)
        return EvidenceVerdictsOut(**_card())

    monkeypatch.setattr(ev_mod, "get_evidence_verdicts", _fake_verdicts)

    for fmt, media, suffix in (
        ("csv", "text/csv", ".csv"),
        ("json", "application/json", ".json"),
        ("md", "text/markdown", ".md"),
    ):
        response = ev_mod.export_evidence_verdicts(
            project_id=5,
            format=fmt,
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
        assert media in response.media_type
        assert (
            f'filename="evidence-verdicts-5{suffix}"'
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

    monkeypatch.setattr(ev_mod, "get_evidence_verdicts", _fail)

    with pytest.raises(HTTPException) as exc:
        ev_mod.export_evidence_verdicts(
            project_id=5,
            format="xlsx",
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
    assert called["n"] == 0
