"""Tests for the one-call per-project overview endpoint.

Covers the pure composition builder in ``app.simulation.project_overview``
(verdict rollups, panel normalisation, headline/narrative composition) and
the route contract that wires the ten existing per-project digests into it.
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
    simulation_quality: str = "ok",
    prediction_range: str = "ok",
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
        "simulation_quality": _panel(
            severity=simulation_quality,
            narrative="Simulation quality is healthy",
        ),
        "prediction_range": _panel(
            severity=prediction_range,
            narrative="Prediction range is calibrated",
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
    assert payload["narrative"] == payload["headline"]
    assert "Not available" not in payload["narrative"]
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


def test_worst_key_signal_severity_wins() -> None:
    panels = _panels()
    panels["outcomes_digest"] = {
        "key_signals": [
            {
                "label": "outcome_count",
                "value": 4,
                "severity": "ok",
            },
            {
                "label": "mean_abs_variance",
                "value": 0.12,
                "severity": "critical",
            },
        ],
        "narrative": "Calibration is poor",
    }
    payload = _build(panels=panels)

    outcomes_row = next(
        row
        for row in payload["subsystems"]
        if row["key"] == "outcomes_digest"
    )
    assert outcomes_row["verdict"] == VERDICT_CRITICAL
    assert payload["overall_verdict"] == VERDICT_CRITICAL
    assert payload["unhealthy_components"] == ["outcomes_digest"]


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


def test_trust_panels_summaries_and_headlines() -> None:
    panels = _panels()
    panels["simulation_quality"] = {
        "overall_verdict": "REVIEW",
        "mean_trust_score": 0.72,
        "pass_count": 1,
        "review_count": 2,
        "fail_count": 1,
        "evaluated_runs": 4,
    }
    panels["prediction_range"] = {
        "simulation_id": 12,
        "predicted_conversion_rate": 0.04,
        "low": 0.02,
        "high": 0.06,
        "confidence_label": "WELL_CALIBRATED",
        "calibration_sample_count": 8,
    }
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["simulation_quality"]["summary"] == (
        "4 run(s), mean trust 72% (REVIEW)"
    )
    assert by_key["simulation_quality"]["headline"] == {
        "overall_verdict": "REVIEW",
        "mean_trust_score": 0.72,
        "pass_count": 1,
        "review_count": 2,
        "fail_count": 1,
    }
    assert by_key["prediction_range"]["summary"] == (
        "Realistic range 2.0%–6.0% (WELL_CALIBRATED)"
    )
    assert by_key["prediction_range"]["headline"] == {
        "simulation_id": 12,
        "predicted_conversion_rate": 0.04,
        "low": 0.02,
        "high": 0.06,
        "confidence_label": "WELL_CALIBRATED",
        "calibration_sample_count": 8,
    }


def test_trust_panel_verdict_field_fallbacks() -> None:
    panels = _panels()
    panels["simulation_quality"] = {
        "key_signals": [],
        "overall_verdict": "FAIL",
    }
    panels["prediction_range"] = {
        "key_signals": [],
        "confidence_label": "POORLY_CALIBRATED",
    }
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["simulation_quality"]["verdict"] == VERDICT_CRITICAL
    assert by_key["prediction_range"]["verdict"] == VERDICT_CRITICAL
    assert payload["overall_verdict"] == VERDICT_CRITICAL
    assert sorted(payload["unhealthy_components"]) == [
        "prediction_range",
        "simulation_quality",
    ]


def test_insufficient_trust_panels_mark_watch() -> None:
    panels = _panels()
    panels["simulation_quality"] = {
        "key_signals": [],
        "overall_verdict": "INSUFFICIENT_DATA",
    }
    panels["prediction_range"] = {
        "key_signals": [],
        "confidence_label": "INSUFFICIENT_DATA",
    }
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["simulation_quality"]["verdict"] == VERDICT_WATCH
    assert by_key["prediction_range"]["verdict"] == VERDICT_WATCH
    assert payload["overall_verdict"] == VERDICT_WATCH


def test_prediction_range_label_overrides_granular_critical_signals() -> None:
    panels = _panels()
    panels["prediction_range"] = {
        "key_signals": [
            {"label": "calibration_sample_count", "severity": "critical"},
            {"label": "accuracy_adjusted_range", "severity": "critical"},
        ],
        "confidence_label": "INSUFFICIENT_DATA",
    }
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    # No calibration data yet is a normal young-project state (watch), not
    # a critical signal, so the digest's canonical label wins.
    assert by_key["prediction_range"]["verdict"] == VERDICT_WATCH
    assert payload["overall_verdict"] == VERDICT_WATCH


def test_prediction_range_well_calibrated_label_overrides_signals() -> None:
    panels = _panels()
    panels["prediction_range"] = {
        "key_signals": [
            {"label": "accuracy_adjusted_range", "severity": "critical"}
        ],
        "confidence_label": "WELL_CALIBRATED",
    }
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["prediction_range"]["verdict"] == VERDICT_HEALTHY
    assert payload["overall_verdict"] == VERDICT_HEALTHY


def test_prediction_range_missing_label_falls_back_to_signals() -> None:
    panels = _panels()
    panels["prediction_range"] = {
        "key_signals": [
            {"label": "calibration_sample_count", "severity": "critical"}
        ],
        "confidence_label": "",
    }
    payload = _build(panels=panels)
    by_key = {row["key"]: row for row in payload["subsystems"]}

    assert by_key["prediction_range"]["verdict"] == VERDICT_CRITICAL
    assert payload["overall_verdict"] == VERDICT_CRITICAL


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


def test_malformed_key_signal_does_not_mask_direct_verdict() -> None:
    panels = _panels()
    panels["health"] = {
        "key_signals": [{"severity": "banana"}],
        "project_health_score": 30,
        "verdict": "AT_RISK",
    }
    payload = _build(panels=panels)

    health_row = next(
        row for row in payload["subsystems"] if row["key"] == "health"
    )
    assert health_row["verdict"] == VERDICT_CRITICAL
    assert payload["overall_verdict"] == VERDICT_CRITICAL


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
    "simulation_quality": "get_project_simulation_quality",
    "prediction_range": "_latest_prediction_range_loader",
    "confidence_explainer": "get_confidence_explainer",
    "next_action": "get_next_action",
    "stale_check": "get_stale_check",
    "convergence": "get_convergence_check",
    "health": "get_project_health",
    "outcomes_digest": "get_outcomes_digest",
}


class _FakeQuery:
    """Minimal query-chain double for the latest-simulation loader."""

    def __init__(self, result: Any) -> None:
        self._result = result

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self._result


def _fake_model(payload: dict[str, Any]) -> Any:
    return types.SimpleNamespace(
        model_dump=lambda: dict(payload),
    )


def _fake_panels() -> dict[str, dict[str, Any]]:
    return _panels()


def test_latest_prediction_range_loader_uses_latest_completed_sim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_ids: list[int] = []

    def fake_get_prediction_range(
        simulation_id: int,
        db: Any,
        current_user: Any,
    ) -> Any:
        captured_ids.append(simulation_id)
        return _fake_model({"simulation_id": simulation_id})

    monkeypatch.setattr(
        project_overview_module,
        "get_prediction_range",
        fake_get_prediction_range,
    )
    fake_sim = types.SimpleNamespace(id=99)
    db = types.SimpleNamespace(
        query=lambda *args: _FakeQuery(fake_sim),
    )

    result = project_overview_module._latest_prediction_range_loader(
        project_id=1,
        db=db,
        current_user=types.SimpleNamespace(id=7),
    )

    assert captured_ids == [99]
    assert result.model_dump() == {"simulation_id": 99}


def test_latest_prediction_range_loader_returns_none_without_sim() -> None:
    db = types.SimpleNamespace(
        query=lambda *args: _FakeQuery(None),
    )

    result = project_overview_module._latest_prediction_range_loader(
        project_id=1,
        db=db,
        current_user=types.SimpleNamespace(id=7),
    )

    assert result is None


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


def test_project_overview_route_accepts_none_panel_loader(
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
    for key, model in loaders.items():
        monkeypatch.setattr(
            project_overview_module,
            _LOADER_ATTRS[key],
            lambda project_id, db, current_user, _model=model: _model,
        )
    monkeypatch.setattr(
        project_overview_module,
        "_latest_prediction_range_loader",
        lambda project_id, db, current_user: None,
    )

    payload = project_overview_module.get_project_overview(
        project_id=1,
        db=object(),
        current_user=types.SimpleNamespace(id=7),
    )

    assert payload.panels["prediction_range"] is None
    prediction_row = next(
        row for row in payload.subsystems if row.key == "prediction_range"
    )
    assert prediction_row.summary == "Not available"
    assert prediction_row.verdict == VERDICT_HEALTHY
    assert payload.overall_verdict == VERDICT_HEALTHY
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
