"""Tests for the run-comparison CSV/JSON/Markdown exports.

The exporter reuses the exact payload produced by the comparison builder;
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

from app.schemas.simulation_compare import SimulationRunDiffOut
from app.simulation.simulation_compare import build_simulation_comparison
from app.simulation.simulation_compare_export import (
    FORMAT_VERSION,
    simulation_compare_to_csv,
    simulation_compare_to_json,
    simulation_compare_to_markdown,
)

_METADATA = {
    "generated_at": "2026-08-23T07:30:00+00:00",
    "user_id": 42,
    "format_version": FORMAT_VERSION,
    "simulation_id": 20,
    "comparison_simulation_id": 20,
    "comparison_baseline_id": 10,
    "project_id": 5,
}


def _results(
    *,
    conv: float,
    stages: dict[str, float] | None = None,
    clusters: dict[str, float] | None = None,
) -> dict:
    return {
        "mean_conversion_rate": conv,
        "mean_revenue": 1500.0,
        "confidence_score": 0.72,
        "worst_drop_off_stage": "DECIDE",
        "stage_aggregations": [
            {"state": state, "mean_drop_off_rate": drop}
            for state, drop in (stages or {}).items()
        ],
        "cluster_breakdown": clusters or {},
    }


def _diff() -> SimulationRunDiffOut:
    return build_simulation_comparison(
        simulation_id=20,
        baseline_id=10,
        current_results=_results(
            conv=0.075,
            stages={"ARRIVE": 0.13, "BROWSE": 0.38},
            clusters={"metro_power_professional": 0.10},
        ),
        baseline_results=_results(
            conv=0.050,
            stages={"ARRIVE": 0.20},
            clusters={"tier3_first_time_app_user": -0.05},
        ),
        current_signal=0.81,
        baseline_signal=0.77,
        project_id=5,
    )


def test_format_version_is_stable() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_sections_and_native_negative_numbers() -> None:
    text = simulation_compare_to_csv(_diff(), metadata=_METADATA)
    lines = text.splitlines()

    assert lines[0] == "generated_at,2026-08-23T07:30:00+00:00"
    assert lines[2] == "simulation_id,20"
    assert "Headline" in lines
    assert "verdict,IMPROVED" in lines

    # Cluster movers keep negative deltas as native numbers — the formula
    # guard must not apostrophe-escape them into spreadsheet text.
    cluster_section = text.split("Cluster Movers")[1]
    tier3_row = next(
        line
        for line in cluster_section.splitlines()
        if line.startswith("tier3_first_time_app_user")
    )
    assert ",-0.05," in tier3_row
    assert "'-0.05" not in tier3_row

    # A formula-leading cluster id would be guarded.
    guarded = build_simulation_comparison(
        simulation_id=20,
        baseline_id=10,
        current_results=_results(conv=0.06, clusters={"=SUM(A1:A2)": 0.09}),
        baseline_results=_results(conv=0.05),
    )
    guard_text = simulation_compare_to_csv(guarded, metadata=_METADATA)
    assert "'=SUM(A1:A2)" in guard_text


def test_json_envelope_is_strict_and_stable() -> None:
    parsed = json.loads(simulation_compare_to_json(_diff(), metadata=_METADATA))

    assert set(parsed) == {"metadata", "simulation_comparison"}
    body = parsed["simulation_comparison"]
    assert body["headline"]["verdict"] == "IMPROVED"
    assert body["baseline_id"] == 10
    assert len(body["cluster_deltas"]) == 2
    assert parsed["metadata"]["format_version"] == "1"


def test_markdown_brief_has_verdict_callout_and_tables() -> None:
    md = simulation_compare_to_markdown(_diff(), metadata=_METADATA)

    assert md.startswith("# Run Comparison — Simulation 20 vs 10")
    assert "**Verdict: IMPROVED**" in md
    assert "7.50%" in md and "5.00%" in md
    assert "> Compared with simulation 10:" in md
    assert "| ARRIVE | 20.00% | 13.00% | -7.00pp |" in md
    # tier3 exists only in the baseline: before known, after missing.
    assert (
        "| tier3_first_time_app_user | -5.00% | — | +5.00pp | IMPROVED |" in md
    )
    assert md.rstrip().endswith(
        "*Run comparison · Simulation 20 vs 10 · Generated 2026-08-23*"
    )


def test_markdown_handles_empty_payload() -> None:
    empty = build_simulation_comparison(
        simulation_id=1, baseline_id=2, current_results={}, baseline_results={}
    )
    md = simulation_compare_to_markdown(empty, metadata=dict(_METADATA))
    assert "_No stage data._" in md
    assert "_No cluster movers returned._" in md


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


async def _drain(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_export_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in sim_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/simulations/{simulation_id}/compare/{baseline_id}/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_round_trip_all_formats(monkeypatch) -> None:
    from app.api.v1 import simulations as sim_mod

    captured: dict = {}

    def _fake_compare(**kwargs):
        captured.update(kwargs)
        return _diff()

    monkeypatch.setattr(sim_mod, "get_simulation_comparison", _fake_compare)

    for fmt, media, suffix in (
        ("csv", "text/csv", ".csv"),
        ("json", "application/json", ".json"),
        ("md", "text/markdown", ".md"),
    ):
        response = sim_mod.export_run_comparison(
            simulation_id=20,
            baseline_id=10,
            format=fmt,
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
        assert media in response.media_type
        assert (
            f'filename="run-compare-20-vs-10{suffix}"'
            in response.headers["Content-Disposition"]
        )
        assert int(response.headers["Content-Length"]) > 0
        body = asyncio.run(_drain(response))
        if fmt == "json":
            json.loads(body.decode())
        else:
            assert len(body) > 0

    assert captured["simulation_id"] == 20
    assert captured["baseline_id"] == 10


def test_export_route_rejects_unknown_format(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api.v1 import simulations as sim_mod

    called = {"n": 0}

    def _fail(**kwargs):
        called["n"] += 1
        raise AssertionError("builder must not run before validation")

    monkeypatch.setattr(sim_mod, "get_simulation_comparison", _fail)

    with pytest.raises(HTTPException) as exc:
        sim_mod.export_run_comparison(
            simulation_id=20,
            baseline_id=10,
            format="xlsx",
            db=None,  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail
    assert called["n"] == 0
