"""Tests for the one-call per-project overview endpoint.

Covers the pure composition builder in ``app.simulation.project_overview``
(verdict rollups, panel normalisation, headline/narrative composition) and
the route contract that wires the eight existing per-project digests into it.
These run without a live database, Redis or Celery worker.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.api.v1 import project_overview as project_overview_module  # noqa: E402
from app.schemas.project_overview import ProjectOverviewOut  # noqa: E402
from app.simulation.project_overview import (  # noqa: E402
    PANEL_ORDER,
    VERDICT_CRITICAL,
    VERDICT_EMPTY,
    VERDICT_HEALTHY,
    VERDICT_WATCH,
    build_project_overview,
)


def _panel(
    *,
    severity: str = "ok",
    narrative: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key_signals": [
            {"label": "signal", "value": severity, "severity": severity}
        ],
        "narrative": narrative,
    }
    if extra:
        payload.update(extra)
    return payload


def _panels(
    *,
    status: str = "ok",
    latest: str = "ok",
    confidence: str = "ok",
    next_action: str = "ok",
    stale: str = "ok",
    convergence: str = "ok",
    health: str = "ok",
    outcomes: str = "ok",
) -> dict[str, dict[str, Any]]:
    return {
        "status_banner": _panel(severity=status, narrative="Project status ok"),
        "latest_snapshot": _panel(
            severity=latest, narrative="Latest activity ok"
        ),
        "confidence_explainer": _panel(
            severity=confidence, narrative="Confidence ok"
        ),
        "next_action": _panel(
            severity=next_action,
            extra={"title": "Run a re-simulation", "action": "RE-RUN"},
        ),
        "stale_check": _panel(severity=stale, narrative="Data is fresh"),
        "convergence": _panel(
            severity=convergence, narrative="Predictions converged"
        ),
        "health": _panel(severity=health, narrative="Health is good"),
        "outcomes_digest": _panel(
            severity=outcomes, narrative="Calibration is healthy"
        ),
    }


def _build(
    panels: dict[str, dict[str, Any] | None] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return build_project_overview(
        project_id=42,
        generated_at="2026-08-11T00:00:00+00:00",
        panels=panels if panels is not None else _panels(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Overall verdicts
# ---------------------------------------------------------------------------


def test_all_ok_panels_produce_healthy_overview_and_schema() -> None:
    payload = _build()

    assert payload["overall_verdict"] == VERDICT_HEALTHY
    assert payload["healthy"] is True
    assert payload["unhealthy_components"] == []
    assert [row["key"] for row in payload["subsystems"]] == list(PANEL_ORDER)
    assert all(row["healthy"] for row in payload["subsystems"])
    assert isinstance(ProjectOverviewOut(**payload), ProjectOverviewOut)


def test_empty_panels_produce_empty_healthy_overview() -> None:
    payload = build_project_overview(
        project_id=1,
        generated_at="now",
        panels={},
    )

    assert payload["overall_verdict"] == VERDICT_EMPTY
    assert payload["healthy"] is True
    assert payload["headline"].startswith("No project data yet")
    # No panels → nothing to judge, but the canonical rows still render as
    # "Not available / healthy" so the dashboard layout never shifts.
    assert len(payload["subsystems"]) == len(PANEL_ORDER)
    assert all(row["healthy"] for row in payload["subsystems"])
    assert all(row["summary"] == "Not available" for row in payload["subsystems"])
    assert isinstance(ProjectOverviewOut(**payload), ProjectOverviewOut)


def test_none_panels_are_healthy_missing_signals() -> None:
    payload = _build(panels={})

    assert payload["overall_verdict"] == VERDICT_EMPTY
    assert payload["healthy"] is True

    payload = _build(panels={key: None for key in PANEL_ORDER})
    # A digest that could not be produced is "nothing to judge", not a
    # broken signal — mirroring the system overview's NO_DATA semantics.
    assert payload["overall_verdict"] == VERDICT_HEALTHY
    assert payload["healthy"] is True


def test_watch_panel_marks_overall_watch() -> None:
    payload = _build(panels=_panels(stale="watch"))

    assert payload["overall_verdict"] == VERDICT_WATCH
    assert payload["healthy"] is False
    assert payload["unhealthy_components"] == ["stale_check"]


def test_critical_panel_wins_over_watch() -> None:
    payload = _build(
        panels=_panels(stale="watch", convergence="critical")
    )

    assert payload["overall_verdict"] == VERDICT_CRITICAL
    assert payload["healthy"] is False
    assert sorted(payload["unhealthy_components"]) == [
        "convergence",
        "stale_check",
    ]


# ---------------------------------------------------------------------------
# Panel normalisation
# ---------------------------------------------------------------------------


def test_next_action_drives_headline_when_present() -> None:
    payload = _build()

    assert payload["headline"] == "Run a re-simulation"


def test_health_narrative_fallback_headline() -> None:
    panels = _panels()
    panels["next_action"] = _panel(severity="ok", narrative="")
    payload = _build(panels=panels)

    assert payload["headline"] == "Health is good"


def test_status_banner_fallback_headline() -> None:
    panels = _panels()
    panels["next_action"] = _panel(severity="ok", narrative="")
    panels["health"] = _panel(severity="ok", narrative="")
    panels["status_banner"] = _panel(
        severity="ok",
        narrative="",
        extra={"status": "Healthy"},
    )
    payload = _build(panels=panels)

    assert payload["headline"] == "Project status: Healthy"


def test_panel_summaries_and_headlines() -> None:
    panels = _panels()
    panels["health"] = _panel(
        severity="watch",
        narrative="",
        extra={"project_health_score": 64, "verdict": "NEEDS_ATTENTION"},
    )
    panels["stale_check"] = _panel(
        severity="critical",
        narrative="",
        extra={"stale_count": 2, "sources_checked": 6},
    )
    panels["outcomes_digest"] = _panel(
        severity="watch",
        narrative="",
        extra={
            "outcome_count": 4,
            "usable_count": 4,
            "mean_abs_variance": 0.06,
            "bias_direction": "BALANCED",
            "accuracy_trend": "STABLE",
        },
    )
    panels["convergence"] = _panel(
        severity="watch",
        narrative="",
        extra={"sim_count": 5, "mean_pcr": 0.04, "cv": 0.12},
    )
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["health"]["summary"] == (
        "Score 64/100 (NEEDS_ATTENTION)"
    )
    assert by_key["health"]["headline"] == {
        "project_health_score": 64,
        "verdict": "NEEDS_ATTENTION",
    }
    assert by_key["stale_check"]["summary"] == "2 of 6 data source(s) stale"
    assert by_key["stale_check"]["headline"] == {
        "stale_count": 2,
        "sources_checked": 6,
    }
    assert by_key["outcomes_digest"]["summary"] == (
        "Mean |variance| 6.0%, BALANCED"
    )
    assert by_key["outcomes_digest"]["headline"] == {
        "outcome_count": 4,
        "usable_count": 4,
        "mean_abs_variance": 0.06,
        "accuracy_trend": "STABLE",
    }
    assert by_key["convergence"]["headline"] == {
        "sim_count": 5,
        "mean_pcr": 0.04,
        "cv": 0.12,
        "verdict": "",
    }


def test_unknown_panel_keys_are_ignored() -> None:
    panels = _panels()
    panels["mystery_digest"] = _panel(severity="critical")
    payload = _build(panels=panels)

    assert payload["overall_verdict"] == VERDICT_HEALTHY
    assert "mystery_digest" not in payload["panels"]


def test_malformed_panel_severities_default_to_ok() -> None:
    panels = _panels()
    panels["health"] = {"key_signals": [{"severity": "banana"}]}
    payload = _build(panels=panels)

    health_row = next(
        row for row in payload["subsystems"] if row["key"] == "health"
    )
    assert health_row["verdict"] == VERDICT_HEALTHY
    assert health_row["healthy"] is True


def test_health_verdict_field_fallback() -> None:
    panels = _panels()
    panels["health"] = {
        "key_signals": [],
        "project_health_score": 30,
        "verdict": "AT_RISK",
    }
    payload = _build(panels=panels)

    health_row = next(
        row for row in payload["subsystems"] if row["key"] == "health"
    )
    assert health_row["verdict"] == VERDICT_CRITICAL


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


_LOADER_ATTRS: dict[str, str] = {
    "status_banner": "get_status_banner",
    "latest_snapshot": "get_latest_snapshot",
    "confidence_explainer": "get_confidence_explainer",
    "next_action": "get_next_action",
    "stale_check": "get_stale_check",
    "convergence": "get_convergence_check",
    "health": "get_project_health",
    "outcomes_digest": "get_outcomes_digest",
}


def _fake_model(payload: dict[str, Any]) -> Any:
    return types.SimpleNamespace(
        model_dump=lambda: dict(payload),
    )


def _fake_panels() -> dict[str, dict[str, Any]]:
    return _panels()


def test_project_overview_route_composes_all_panels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_cache: dict[str, Any] = {}
    fake_panels = _fake_panels()
    loaders = {
        key: _fake_model(payload)
        for key, payload in fake_panels.items()
    }

    monkeypatch.setattr(
        project_overview_module,
        "get_owned_project",
        lambda db, user_id, project_id: None,
    )
    monkeypatch.setattr(
        project_overview_module,
        "cache_get_json",
        lambda **kwargs: None,
    )

    def recording_cache_set_json(**kwargs: Any) -> None:
        captured_cache.update(kwargs)

    monkeypatch.setattr(
        project_overview_module,
        "cache_set_json",
        recording_cache_set_json,
    )

    for key, model in loaders.items():
        monkeypatch.setattr(
            project_overview_module,
            _LOADER_ATTRS[key],
            lambda project_id, db, current_user, _model=model: _model,
        )

    user = types.SimpleNamespace(id=7)
    payload = project_overview_module.get_project_overview(
        project_id=1,
        db=object(),
        current_user=user,
    )

    assert payload.overall_verdict == VERDICT_HEALTHY
    assert payload.healthy is True
    assert [row.key for row in payload.subsystems] == list(PANEL_ORDER)
    assert set(payload.panels) == set(PANEL_ORDER)
    assert captured_cache["namespace"] == "project-overview"
    assert captured_cache["params"] == {"project_id": 1}
    assert captured_cache["user_id"] == 7
    assert isinstance(payload, ProjectOverviewOut)


def test_project_overview_route_cache_hit_skips_loaders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached = _build(panels=_panels(stale="watch"))
    monkeypatch.setattr(
        project_overview_module,
        "get_owned_project",
        lambda db, user_id, project_id: None,
    )
    monkeypatch.setattr(
        project_overview_module,
        "cache_get_json",
        lambda **kwargs: cached,
    )

    def unexpected_loader(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("loader should not run on cache hit")

    for key in PANEL_ORDER:
        monkeypatch.setattr(
            project_overview_module,
            _LOADER_ATTRS[key],
            unexpected_loader,
        )

    payload = project_overview_module.get_project_overview(
        project_id=1,
        db=object(),
        current_user=types.SimpleNamespace(id=7),
    )

    assert payload.overall_verdict == VERDICT_WATCH
    assert isinstance(payload, ProjectOverviewOut)


def test_project_overview_route_fails_open_on_broken_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_panels = _fake_panels()
    loaders = {
        key: _fake_model(payload)
        for key, payload in fake_panels.items()
    }
    monkeypatch.setattr(
        project_overview_module,
        "get_owned_project",
        lambda db, user_id, project_id: None,
    )
    monkeypatch.setattr(
        project_overview_module,
        "cache_get_json",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        project_overview_module,
        "cache_set_json",
        lambda **kwargs: None,
    )

    def broken_loader(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("digest down")

    for key in PANEL_ORDER:
        loader = (
            broken_loader
            if key == "stale_check"
            else lambda project_id, db, current_user, _model=loaders[key]: _model
        )
        monkeypatch.setattr(
            project_overview_module,
            _LOADER_ATTRS[key],
            loader,
        )

    payload = project_overview_module.get_project_overview(
        project_id=1,
        db=object(),
        current_user=types.SimpleNamespace(id=7),
    )

    assert "stale_check" not in payload.panels
    stale_row = next(
        row for row in payload.subsystems if row.key == "stale_check"
    )
    assert stale_row.verdict == VERDICT_HEALTHY
    assert stale_row.summary == "Not available"
    assert payload.overall_verdict == VERDICT_HEALTHY
    assert isinstance(payload, ProjectOverviewOut)
