"""Tests for the recovery-plan CSV/JSON/Markdown exports.

The exporters reuse the exact payload produced by the recovery planner;
these tests pin the multi-section CSV layout (native numeric cells, no
formula injection, flattened play rows), the stable JSON envelope, and
the founder-facing Markdown brief, plus the export route's format
validation and wiring.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.recovery_planner import build_recovery_plan
from app.simulation.recovery_planner_export import (
    FORMAT_VERSION,
    recovery_plan_to_csv,
    recovery_plan_to_json,
    recovery_plan_to_markdown,
)

_METADATA = {
    "generated_at": "2026-08-23T10:05:00+00:00",
    "user_id": 42,
    "project_id": 5,
    "format_version": FORMAT_VERSION,
}


def _asm(id_: int, text: str, category: str = "Pricing"):
    return SimpleNamespace(id=id_, text=text, category=category)


def _ev(
    assumption_id: int,
    *,
    id_: int = 1,
    result: str = "FAIL",
    method: str = "WILLINGNESS_TO_PAY_SURVEY",
    observed_metric: float | None = 0.10,
):
    return SimpleNamespace(
        assumption_id=assumption_id,
        id=id_,
        result=result,
        method=method,
        observed_metric=observed_metric,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _plan() -> dict:
    """One killed pricing claim + one inconsistent demand claim."""
    assumptions = [
        _asm(1, "Users will pay ₹999 monthly", "Pricing"),
        _asm(2, "=cmd hostile landing", "Demand"),
    ]
    evidence = [
        _ev(1, id_=1, result="FAIL", observed_metric=0.10),
        _ev(
            2,
            id_=2,
            result="PASS",
            method="LANDING_PAGE_SMOKE_TEST",
            observed_metric=0.01,
        ),
    ]
    return build_recovery_plan(
        project_id=5, assumptions=assumptions, evidence=evidence
    )


def test_format_version_is_stable() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_sections_flattened_plays_and_native_numbers() -> None:
    text = recovery_plan_to_csv(_plan(), metadata=_METADATA)
    lines = text.splitlines()

    assert lines[0] == "generated_at,2026-08-23T10:05:00+00:00"
    assert lines[2] == "project_id,5"

    assert "section,Recovery Summary" in lines
    assert "attention_count,2" in lines
    assert "theme:pricing,1" in lines
    assert "theme:demand,1" in lines

    # Plays are flattened: killed row has 3 plays, audited row has 2.
    plays = text.split("section,Recovery Plays")[1].split("section,")[0]
    play_lines = [line for line in plays.splitlines()[2:] if line]
    assert len(play_lines) == 5

    # Durations stay native numbers (no apostrophe escaping).
    assert ",14," in text
    assert "',14" not in text

    assert "section,Next Steps" in lines
    assert "need recovery" in text
    assert "section,Recovery Meta" in lines


def test_csv_guards_formula_leading_text() -> None:
    text = recovery_plan_to_csv(_plan(), metadata=_METADATA)
    assert "'=cmd hostile landing" in text


def test_json_envelope_is_strict_and_stable() -> None:
    parsed = json.loads(recovery_plan_to_json(_plan(), metadata=_METADATA))

    assert set(parsed) == {"metadata", "recovery_plan"}
    body = parsed["recovery_plan"]
    assert body["attention_count"] == 2
    assert body["rows"][0]["trigger"] == "KILLED"
    assert parsed["metadata"]["format_version"] == "1"


def test_markdown_brief_tables_and_footer() -> None:
    md = recovery_plan_to_markdown(_plan(), metadata=_METADATA)

    assert md.startswith("# Assumption Recovery Plan")
    assert "| Killed | 1 |" in md
    assert "| Pricing claims | 1 |" in md
    assert "| 1 | Users will pay ₹999 monthly | KILLED | pricing " in md
    assert "Audit the recorded result against its metric" in md
    assert "**3 killed and 0 inconsistent assumption(s)" in md or (
        "need recovery" in md
    )
    assert md.rstrip().endswith(
        "*Recovery plan · Project 5 · Generated 2026-08-23T10:05:00+00:00*"
    )


def test_markdown_handles_empty_payload() -> None:
    empty = build_recovery_plan(project_id=5, assumptions=[], evidence=[])
    md = recovery_plan_to_markdown(empty, metadata=dict(_METADATA))
    assert "# Assumption Recovery Plan" in md
    assert "## Recovery Plays" not in md
    assert "**Nothing needs recovery" in md


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
    path = "/projects/{project_id}/assumption-recovery-plan/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_round_trip_all_formats(monkeypatch) -> None:
    from app.api.v1 import assumption_evidence as ev_mod
    from app.schemas.recovery_plan import RecoveryPlanOut

    captured: dict = {}

    def _fake_plan(**kwargs):
        captured.update(kwargs)
        return RecoveryPlanOut(**_plan())

    monkeypatch.setattr(ev_mod, "get_assumption_recovery_plan", _fake_plan)

    for fmt, media, suffix in (
        ("csv", "text/csv", ".csv"),
        ("json", "application/json", ".json"),
        ("md", "text/markdown", ".md"),
    ):
        response = ev_mod.export_assumption_recovery_plan(
            project_id=5,
            format=fmt,
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
        assert media in response.media_type
        assert (
            f'filename="recovery-plan-5{suffix}"'
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

    monkeypatch.setattr(ev_mod, "get_assumption_recovery_plan", _fail)

    with pytest.raises(HTTPException) as exc:
        ev_mod.export_assumption_recovery_plan(
            project_id=5,
            format="xlsx",
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
    assert called["n"] == 0
