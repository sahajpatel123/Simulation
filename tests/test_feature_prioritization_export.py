"""Tests for the feature-prioritization export serializers and route."""
from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

from app.schemas.feature_prioritization import (
    SEGMENT_ADVANCED,
    TIER_BUILD_FIRST,
    VERDICT_FOCUSED,
    BriefFeatureScore,
    ClusterFeatureProfile,
    FeatureDimension,
    FeaturePrioritizationOut,
)
from app.simulation.feature_prioritization_export import (
    feature_prioritization_to_csv,
    feature_prioritization_to_json,
    feature_prioritization_to_markdown,
)

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _payload() -> FeaturePrioritizationOut:
    return FeaturePrioritizationOut(
        simulation_id=1,
        project_id=2,
        status="COMPLETED",
        product_type="saas",
        verdict=VERDICT_FOCUSED,
        dimensions=[
            FeatureDimension(
                key="integration_adoption_rate",
                label="Integrations",
                adoption_rate=0.35,
                reach_weight=0.9,
                upside=0.585,
                priority_score=0.1,
                priority_tier=TIER_BUILD_FIRST,
                recommendation=(
                    "Invest next in Integrations: 35% adoption leaves "
                    "59% of the covered market unserved (reach 90%)."
                ),
            ),
            FeatureDimension(
                key="api_adoption_rate",
                label="API / developer usage",
                adoption_rate=0.12,
                reach_weight=0.9,
                upside=0.79,
                priority_score=0.01,
                priority_tier="DEPRIORITIZE",
                recommendation=(
                    "Deprioritize API / developer usage for now: 12% "
                    "adoption and limited validated upside."
                ),
            ),
        ],
        cluster_profiles=[
            ClusterFeatureProfile(
                cluster_id="c1",
                cluster_name="Power Pros",
                population_weight=0.3,
                feature_depth=0.7,
                core_dau_rate=0.6,
                power_discovery_rate=0.4,
                abandonment_rate=0.1,
                segment_tier=SEGMENT_ADVANCED,
            )
        ],
        brief_features=[
            BriefFeatureScore(
                feature="Slack integration",
                dimension_key="integration_adoption_rate",
                dimension_label="Integrations",
                adoption_rate=0.35,
                priority_tier=TIER_BUILD_FIRST,
                note=(
                    "Maps to Integrations (35% adoption, BUILD_FIRST)."
                ),
            )
        ],
        flags=["shallow_adoption_risk", "power_discovery_gap"],
        recommendations=[
            (
                "Start with Integrations — highest validated upside "
                "(35% adoption, 59% headroom)."
            ),
            "Focus onboarding on power features before adding new ones.",
        ],
        meta={
            "signal_quality": 0.62,
            "total_clusters": 52,
            "covered_clusters": 52,
            "covered_weight": 0.98,
            "top_dimension": "integration_adoption_rate",
            "top_priority_score": 0.1,
            "product_type_supported": True,
        },
    )


def test_csv_has_summary_dimensions_profiles_and_recommendations() -> None:
    csv_text = feature_prioritization_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-08T00:00:00Z",
            "user_id": 42,
            "format_version": "1",
            "simulation_id": 1,
            "project_id": 2,
        },
    )

    assert "generated_at,2026-08-08T00:00:00Z" in csv_text
    assert "user_id,42" in csv_text
    assert "simulation_id,1" in csv_text
    assert "project_id,2" in csv_text
    assert "section,Feature Prioritization Summary" in csv_text
    assert "verdict,FOCUSED" in csv_text
    assert "top_dimension,integration_adoption_rate" in csv_text
    assert "section,Prioritized Dimensions" in csv_text
    assert "Integrations,0.35,0.9,0.585,0.1,BUILD_FIRST" in csv_text
    assert "section,Cluster Feature Profiles" in csv_text
    assert "Power Pros,0.3,0.7,0.6,0.4,0.1,ADVANCED" in csv_text
    assert "section,Brief Feature Mapping" in csv_text
    assert "Slack integration,integration_adoption_rate,Integrations" in csv_text
    assert "section,Flags" in csv_text
    assert "shallow_adoption_risk" in csv_text
    assert "section,Recommendations" in csv_text
    assert "Start with Integrations" in csv_text


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = feature_prioritization_to_csv(
        FeaturePrioritizationOut(
            simulation_id=0,
            project_id=0,
            verdict="INSUFFICIENT_DATA",
        )
    )

    assert "section,Feature Prioritization Summary" in csv_text
    assert "section,Prioritized Dimensions" in csv_text
    assert "section,Cluster Feature Profiles" in csv_text
    assert "section,Brief Feature Mapping" in csv_text
    assert "section,Flags" in csv_text
    assert "section,Recommendations" in csv_text
    assert "key,label,adoption_rate,reach_weight,upside,priority_score" in csv_text


def test_csv_handles_missing_optional_blocks() -> None:
    csv_text = feature_prioritization_to_csv(
        {
            "simulation_id": 7,
            "project_id": 8,
            "status": "COMPLETED",
            "dimensions": [],
            "cluster_profiles": [],
            "brief_features": [],
            "flags": [],
            "recommendations": [],
        }
    )

    assert "simulation_id,7" in csv_text
    assert "section,Prioritized Dimensions" in csv_text
    assert "section,Flags" in csv_text
    assert "section,Recommendations" in csv_text


@pytest.mark.parametrize(
    "malicious",
    ["=HYPERLINK('http://evil')", "+cmd", "-cmd", "@cmd", "\tcmd", "\rcmd"],
)
def test_csv_neutralises_formula_injection(malicious: str) -> None:
    payload = _payload()
    payload.dimensions[0].label = malicious
    payload.recommendations = [malicious]

    csv_text = feature_prioritization_to_csv(payload)

    assert f"'{malicious}" in csv_text


def test_json_round_trips_payload() -> None:
    json_text = feature_prioritization_to_json(
        _payload(),
        metadata={"format_version": "1"},
    )
    parsed = json.loads(json_text)

    assert parsed["metadata"]["format_version"] == "1"
    assert parsed["feature_prioritization"]["simulation_id"] == 1
    assert parsed["feature_prioritization"]["project_id"] == 2
    assert parsed["feature_prioritization"]["verdict"] == "FOCUSED"
    assert len(parsed["feature_prioritization"]["dimensions"]) == 2


def test_markdown_includes_summary_dimensions_and_recommendations() -> None:
    md = feature_prioritization_to_markdown(
        _payload(),
        simulation_id=1,
        project_id=2,
        project_name="Test Project",
        metadata={"generated_at": "2026-08-08T00:00:00Z"},
    )

    assert "# Test Project — Feature Prioritization" in md
    assert "## Summary" in md
    assert "## Prioritized Dimensions" in md
    assert "## Cluster Feature Profiles" in md
    assert "## Brief Feature Mapping" in md
    assert "## Flags" in md
    assert "## Recommendations" in md
    assert "Start with Integrations" in md
    assert "Simulation: 1" in md
    assert "Project: 2" in md


def test_markdown_escapes_pipe_characters() -> None:
    payload = _payload()
    payload.dimensions[0].label = "Results | payload"
    payload.recommendations = ["Recommendation | pipe"]

    md = feature_prioritization_to_markdown(payload)

    assert "Results \\| payload" in md
    assert "Recommendation \\| pipe" in md


def test_markdown_handles_empty_items() -> None:
    md = feature_prioritization_to_markdown(
        {
            "simulation_id": 1,
            "project_id": 2,
            "dimensions": [],
            "cluster_profiles": [],
            "brief_features": [],
            "flags": [],
            "recommendations": [],
        }
    )

    assert "## Prioritized Dimensions" in md
    assert "No modeled feature dimensions are available." in md
    assert "No risk flags detected." in md
    assert "No recommendations are currently available." in md


def test_csv_ignores_scalar_list_sections() -> None:
    """Scalar section values must not be iterated as if they were lists."""
    csv_text = feature_prioritization_to_csv(
        {
            "simulation_id": 1,
            "project_id": 2,
            "dimensions": "not-a-list",
            "cluster_profiles": None,
            "brief_features": 42,
            "flags": "risky",
            "recommendations": "build now",
        }
    )

    assert "flags_count,0" in csv_text
    assert "recommendations_count,0" in csv_text
    assert "dimension_count,0" in csv_text
    assert "section,Flags" in csv_text
    assert "section,Recommendations" in csv_text
    # Scalar values must not be split into per-character rows.
    assert "r,risky" not in csv_text
    assert "b,build" not in csv_text
    assert "d,not-a-list" not in csv_text


def test_markdown_ignores_scalar_list_sections() -> None:
    """Markdown serialization must tolerate malformed scalar sections."""
    md = feature_prioritization_to_markdown(
        {
            "simulation_id": 1,
            "project_id": 2,
            "dimensions": "not-a-list",
            "flags": "risky",
            "recommendations": "build now",
        }
    )

    assert "No modeled feature dimensions are available." in md
    assert "No risk flags detected." in md
    assert "No recommendations are currently available." in md
    assert "r,risky" not in md
    assert "b,build" not in md


def test_markdown_renders_zero_ids() -> None:
    """A simulation/project id of 0 must be shown, not collapsed to '—'."""
    md = feature_prioritization_to_markdown(
        {
            "simulation_id": 0,
            "project_id": 0,
            "dimensions": [],
            "cluster_profiles": [],
            "brief_features": [],
            "flags": [],
            "recommendations": [],
        },
        simulation_id=0,
        project_id=0,
    )

    assert "- Simulation: 0" in md
    assert "- Project: 0" in md
    assert "- Simulation: —" not in md


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def _import_simulations_module():
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub
    from app.api.v1 import simulations as sim_mod

    return sim_mod


async def _collect(resp: Any) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp: Any) -> bytes:
    return asyncio.run(_collect(resp))


class _FakeProject:
    def __init__(self) -> None:
        self.id = 2
        self.title = "Test Project"


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeProject()]

    def filter(self, *args: object, **kwargs: object) -> _FakeQuery:
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def query(self, model: object, *args: object, **kwargs: object) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery()
        return _FakeQuery([])


def _call_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    simulation_id: int = 1,
    format: str = "csv",
    payload: FeaturePrioritizationOut | None = None,
):
    sim_mod = _import_simulations_module()
    fake_payload = payload if payload is not None else _payload()

    def _fake_get_feature_prioritization(**kwargs: object) -> FeaturePrioritizationOut:
        return fake_payload

    monkeypatch.setattr(
        sim_mod,
        "get_feature_prioritization",
        _fake_get_feature_prioritization,
    )
    return sim_mod.export_feature_prioritization(
        simulation_id=simulation_id,
        format=format,
        db=_FakeSession(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_returns_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch)

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="feature-prioritization-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "section,Feature Prioritization Summary" in body
    assert "section,Prioritized Dimensions" in body
    assert "section,Cluster Feature Profiles" in body
    assert "Start with Integrations" in body


def test_export_route_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    assert 'filename="feature-prioritization-1.json"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert '"metadata"' in body
    assert '"feature_prioritization"' in body
    assert '"verdict": "FOCUSED"' in body


def test_export_route_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _call_route(monkeypatch, format="md")

    assert resp.media_type == "text/markdown; charset=utf-8"
    assert 'filename="feature-prioritization-1.md"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "## Prioritized Dimensions" in body
    assert "## Recommendations" in body


def test_export_route_rejects_unknown_format(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(monkeypatch, format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_unknown_format_fails_before_payload_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported format must not pay for the expensive payload build."""
    sim_mod = _import_simulations_module()
    calls: list[object] = []

    def _forbidden_get(**kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError("payload builder should not run for bad format")

    monkeypatch.setattr(sim_mod, "get_feature_prioritization", _forbidden_get)

    with pytest.raises(HTTPException) as exc_info:
        sim_mod.export_feature_prioritization(
            simulation_id=1,
            format="yaml",
            db=_FakeSession(),  # type: ignore[arg-type]
            current_user=type("U", (), {"id": 42})(),
        )

    assert exc_info.value.status_code == 400
    assert calls == []
