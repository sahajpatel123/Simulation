"""Route and serialization tests for validation-momentum exports.

Covers CSV, JSON, and Markdown rendering of the momentum payload,
format validation, and that the ``target_de_risked_pct`` query parameter
flows through to the momentum builder.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.validation_momentum import ValidationMomentumOut


def _payload() -> ValidationMomentumOut:
    return ValidationMomentumOut.model_validate(
        {
            "project_id": 7,
            "counts": {
                "total_assumptions": 2,
                "total_evidence_rows": 3,
                "assumptions_with_evidence": 1,
                "de_risked_count": 1,
                "challenged_count": 0,
                "inconclusive_count": 0,
                "pending_count": 1,
                "evidence_coverage_pct": 0.5,
                "validation_score": 0.5,
            },
            "velocity": {
                "trend": "STEADY",
                "overall_events_per_week": 2.1,
                "recent_events_per_week": 2.4,
                "recent_window_days": 28,
                "events_last_28_days": 3,
                "first_evidence_at": "2026-08-01T00:00:00+00:00",
                "latest_evidence_at": "2026-08-12T00:00:00+00:00",
                "evidence_span_days": 11.0,
                "coverage_velocity_per_week": 0.7,
                "de_risk_velocity_per_week": 0.5,
            },
            "forecast": {
                "target_de_risked_pct": 1.0,
                "target_de_risked_count": 2,
                "remaining_for_coverage": 1,
                "remaining_for_target": 1,
                "weeks_to_full_coverage": 1.43,
                "projected_full_coverage_at": "2026-08-22T00:00:00+00:00",
                "weeks_to_de_risked_target": 2.0,
                "projected_de_risked_at": "2026-08-26T00:00:00+00:00",
                "confident": True,
                "caveats": [],
            },
            "insights": ["Keep the current cadence."],
            "meta": {"model": "validation_momentum_v1"},
        }
    )


async def _collect(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_collect(response))


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    format: str = "csv",
    target_de_risked_pct: float = 1.0,
    payload: ValidationMomentumOut | None = None,
) -> Any:
    from app.api.v1 import assumption_evidence as ev_mod

    fake_payload = payload if payload is not None else _payload()
    monkeypatch.setattr(
        ev_mod,
        "get_validation_momentum",
        lambda **kwargs: fake_payload,
    )
    return ev_mod.export_validation_momentum(
        project_id=7,
        format=format,
        target_de_risked_pct=target_de_risked_pct,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_registered() -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    methods_by_path: dict[str, set[str]] = {}
    for route in ev_mod.router.routes:
        methods_by_path.setdefault(route.path, set()).update(
            route.methods or set()
        )
    path = "/projects/{project_id}/validation-momentum/export"
    assert "GET" in methods_by_path.get(path, set())


def test_export_route_returns_csv_with_all_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch)

    assert response.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="validation-momentum-7.csv"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response)
    text = body.decode("utf-8")
    assert "section,Momentum Counts" in text
    assert "section,Velocity" in text
    assert "section,Forecast" in text
    assert "section,Insights" in text
    assert "de_risked_count,1" in text
    assert "evidence_coverage_pct,0.5" in text
    assert "trend,STEADY" in text
    assert "weeks_to_full_coverage,1.43" in text
    assert "Keep the current cadence." in text
    assert int(response.headers["Content-Length"]) == len(body)


def test_csv_guards_formula_leading_insights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    payload.insights = ["=SUM(A1:A2) looks safe"]
    text = _body(_call_route(monkeypatch, payload=payload)).decode("utf-8")
    assert "'=SUM(A1:A2) looks safe" in text


def test_export_route_returns_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="json")

    assert response.media_type == "application/json; charset=utf-8"
    assert (
        'filename="validation-momentum-7.json"'
        in response.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(response).decode("utf-8"))
    assert parsed["metadata"]["project_id"] == 7
    assert parsed["metadata"]["format_version"] == "1"
    momentum = parsed["validation_momentum"]
    assert momentum["project_id"] == 7
    assert momentum["counts"]["de_risked_count"] == 1
    assert momentum["forecast"]["remaining_for_target"] == 1


def test_export_forwards_target_to_momentum_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    seen: dict[str, Any] = {}

    def fake_momentum(**kwargs: Any) -> ValidationMomentumOut:
        seen.update(kwargs)
        return _payload()

    monkeypatch.setattr(ev_mod, "get_validation_momentum", fake_momentum)
    ev_mod.export_validation_momentum(
        project_id=7,
        format="csv",
        target_de_risked_pct=0.75,
        db=object(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )

    assert seen["target_de_risked_pct"] == 0.75
    assert seen["project_id"] == 7


def test_export_rejects_unknown_format_before_building_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import assumption_evidence as ev_mod

    calls: list[dict[str, Any]] = []

    def forbidden_momentum(**kwargs: Any) -> ValidationMomentumOut:
        calls.append(kwargs)
        raise AssertionError("momentum should not build for an invalid format")

    monkeypatch.setattr(ev_mod, "get_validation_momentum", forbidden_momentum)
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail
    assert calls == []


def test_export_route_returns_markdown_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _call_route(monkeypatch, format="md")

    assert response.media_type == "text/markdown; charset=utf-8"
    assert (
        'filename="validation-momentum-7.md"'
        in response.headers["Content-Disposition"]
    )
    assert response.headers["Cache-Control"] == "no-store"
    body = _body(response).decode("utf-8")
    assert "# Validation Momentum" in body
    assert "## Counts" in body
    assert "## Velocity" in body
    assert "## Forecast" in body
    assert "| Coverage | 50.0% |" in body
    assert "| Validation score | 50.0% |" in body
    assert "| De-risk target share | 100.0% |" in body
    assert "| Cadence trend | STEADY |" in body
    assert "- Keep the current cadence." in body
    # No raw snake_case keys leak into the founder-facing tables.
    assert "| evidence_coverage_pct |" not in body
    assert int(response.headers["Content-Length"]) == len(body.encode("utf-8"))


def test_markdown_escapes_pipe_in_insights() -> None:
    """A pipe inside an insight cannot break the brief."""
    from app.simulation.validation_momentum_export import (
        validation_momentum_to_markdown,
    )

    body = validation_momentum_to_markdown(
        {
            "project_id": 7,
            "counts": {},
            "velocity": {},
            "forecast": {},
            "insights": ["Coverage | velocity gap is widening"],
        }
    )
    insight_line = next(
        line for line in body.splitlines() if "widening" in line
    )
    assert insight_line == "- Coverage \\| velocity gap is widening"


def test_csv_includes_forecast_caveats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-empty forecast caveats get their own CSV section."""
    payload = _payload()
    payload.forecast.caveats = ["Velocity estimated from 3 events"]
    text = _body(_call_route(monkeypatch, payload=payload)).decode("utf-8")
    assert "section,Forecast Caveats" in text
    assert "Velocity estimated from 3 events" in text


def test_csv_omits_caveat_section_when_empty() -> None:
    """No caveats means no stray section header."""
    from app.simulation.validation_momentum_export import (
        validation_momentum_to_csv,
    )

    text = validation_momentum_to_csv(_payload())
    assert "Forecast Caveats" not in text


def test_markdown_lists_caveats_after_forecast() -> None:
    """Caveats render as bullets directly under the Forecast table."""
    from app.simulation.validation_momentum_export import (
        validation_momentum_to_markdown,
    )

    payload = _payload()
    payload.forecast.caveats = ["Cadence | thin sample"]
    lines = validation_momentum_to_markdown(payload).splitlines()

    forecast_idx = lines.index("## Forecast")
    caveats_idx = lines.index("### Forecast Caveats")
    insights_idx = lines.index("## Insights")
    assert forecast_idx < caveats_idx < insights_idx
    caveat_line = next(line for line in lines if "thin sample" in line)
    assert caveat_line == "- Cadence \\| thin sample"


def test_markdown_omits_caveats_heading_when_empty() -> None:
    from app.simulation.validation_momentum_export import (
        validation_momentum_to_markdown,
    )

    body = validation_momentum_to_markdown(_payload())
    assert "Forecast Caveats" not in body


def test_markdown_handles_missing_sections_gracefully() -> None:
    """An empty momentum still renders a complete brief."""
    from app.simulation.validation_momentum_export import (
        validation_momentum_to_markdown,
    )

    body = validation_momentum_to_markdown({"project_id": 9})
    assert "# Validation Momentum" in body
    assert "| Metric | Value |" in body
