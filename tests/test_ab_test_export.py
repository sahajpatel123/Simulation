"""Tests for the A/B experiment portfolio export serializers and route."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.ab_test import (
    AbTestAnalysisOut,
    AbTestExperimentOut,
    AbTestVariantOut,
)
from app.simulation.ab_test_export import (
    FORMAT_VERSION,
    ab_test_experiments_to_csv,
    ab_test_experiments_to_json,
    ab_test_experiments_to_markdown,
)


def _experiment(
    *,
    experiment_id: int = 1,
    name: str = "Headline test",
    hypothesis: str | None = "Clearer value prop lifts conversion",
    verdict: str = "SIGNIFICANT",
    significant: bool = True,
    winner: str | None = "New",
    relative_uplift_pct: float | None = 60.0,
    p_value: float | None = 0.000066,
) -> AbTestExperimentOut:
    return AbTestExperimentOut(
        id=experiment_id,
        project_id=10,
        name=name,
        hypothesis=hypothesis,
        verdict=verdict,
        significant=significant,
        winner=winner,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 2, tzinfo=UTC),
        analysis=AbTestAnalysisOut(
            variant_a=AbTestVariantOut(
                label="Control",
                visitors=1000,
                conversions=100,
                conversion_rate=0.1,
            ),
            variant_b=AbTestVariantOut(
                label="New",
                visitors=1000,
                conversions=160,
                conversion_rate=0.16,
            ),
            winner=winner,
            pooled_conversion_rate=0.13,
            absolute_uplift=0.06,
            relative_uplift_pct=relative_uplift_pct,
            z_score=3.9894,
            p_value=p_value,
            confidence_interval={"low": 0.0306, "high": 0.0894},
            verdict=verdict,
            significant=significant,
            confidence_level=0.95,
            visitors_needed_for_observed_uplift=3841,
            visitors_needed_for_mde=3841,
            narrative="winner",
            recommendations=["Adopt New", "Watch post-ship conversion"],
            key_signals=[
                {
                    "label": "verdict",
                    "value": "SIGNIFICANT",
                    "severity": "ok",
                }
            ],
            meta={"alpha": 0.05, "power": 0.8, "mde": 0.02},
        ),
    )


def _metadata() -> dict[str, Any]:
    return {
        "generated_at": "2026-08-10T00:00:00Z",
        "user_id": 42,
        "format_version": "1",
        "project_id": 10,
        "experiment_count": 1,
    }


def test_format_version_is_contract_constant() -> None:
    assert FORMAT_VERSION == "1"


def test_csv_has_metadata_summary_and_experiment_rows() -> None:
    csv_text = ab_test_experiments_to_csv(
        [_experiment()],
        project_id=10,
        metadata=_metadata(),
    )

    assert "generated_at,2026-08-10T00:00:00Z" in csv_text
    assert "user_id,42" in csv_text
    assert "project_id,10" in csv_text
    assert "experiment_count,1" in csv_text
    assert "section,A/B Experiment Portfolio Summary" in csv_text
    assert "total_experiments,1" in csv_text
    assert "significant_count,1" in csv_text
    assert "section,Experiments" in csv_text
    assert "1,Headline test,Clearer value prop lifts conversion" in csv_text
    assert "Control,1000,100,0.1" in csv_text
    assert "New,1000,160,0.16" in csv_text
    assert "SIGNIFICANT" in csv_text
    assert "0.000066" in csv_text
    assert "Adopt New; Watch post-ship conversion" in csv_text
    assert "recommendations_count,key_signals_count" in csv_text
    assert "Adopt New; Watch post-ship conversion,2,1" in csv_text


def test_csv_metadata_defaults_format_version_to_contract() -> None:
    csv_text = ab_test_experiments_to_csv(
        [],
        project_id=10,
        metadata={
            "generated_at": "2026-08-10T00:00:00Z",
            "user_id": 42,
        },
    )

    assert f"format_version,{FORMAT_VERSION}" in csv_text


def test_csv_empty_portfolio_still_renders_sections() -> None:
    csv_text = ab_test_experiments_to_csv([], project_id=10)

    assert "section,A/B Experiment Portfolio Summary" in csv_text
    assert "total_experiments,0" in csv_text
    assert "section,Experiments" in csv_text
    assert "id,name,hypothesis,created_at" in csv_text


@pytest.mark.parametrize(
    "malicious",
    ["=HYPERLINK('http://evil')", "+cmd", "-cmd", "@cmd", "\tcmd", "\rcmd"],
)
def test_csv_neutralises_formula_injection(malicious: str) -> None:
    csv_text = ab_test_experiments_to_csv(
        [
            _experiment(
                name=malicious,
                hypothesis="=SUM(A1:A2)",
            )
        ],
        project_id=10,
    )

    assert f"'{malicious}" in csv_text
    assert "'=SUM(A1:A2)" in csv_text


def test_json_round_trips_portfolio() -> None:
    json_text = ab_test_experiments_to_json(
        [_experiment()],
        project_id=10,
        metadata=_metadata(),
    )
    parsed = json.loads(json_text)

    assert parsed["metadata"]["format_version"] == "1"
    assert parsed["metadata"]["experiment_count"] == 1
    assert parsed["project_id"] == 10
    assert parsed["summary"]["total_experiments"] == 1
    assert parsed["summary"]["verdict_counts"]["SIGNIFICANT"] == 1
    assert parsed["experiments"][0]["name"] == "Headline test"
    assert parsed["experiments"][0]["analysis"]["variant_b"]["conversion_rate"] == 0.16
    assert parsed["experiments"][0]["created_at"].startswith("2026-08-01")


def test_json_empty_portfolio_is_valid() -> None:
    parsed = json.loads(
        ab_test_experiments_to_json([], project_id=10, metadata=_metadata())
    )

    assert parsed["summary"]["total_experiments"] == 0
    assert parsed["experiments"] == []


def test_markdown_includes_summary_experiments_and_next_action() -> None:
    md = ab_test_experiments_to_markdown(
        [_experiment()],
        project_id=10,
        project_name="Test Project",
        metadata=_metadata(),
    )

    assert "# Test Project — A/B Experiment Portfolio" in md
    assert "## Summary" in md
    assert "## Experiments" in md
    assert "## Next Action" in md
    assert "| 1 | Headline test | SIGNIFICANT | True | New |" in md
    assert "| 2000 | 260 | 13.00% | +0.0600 | +60.00% | 0.000066 |" in md
    assert "Project: 10" in md
    assert "Generated: 2026-08-10T00:00:00Z" in md


def test_markdown_escapes_pipe_characters() -> None:
    md = ab_test_experiments_to_markdown(
        [_experiment(name="Results | payload")],
        project_id=10,
        project_name="Test | Project",
    )

    assert "# Test \\| Project — A/B Experiment Portfolio" in md
    assert "Results \\| payload" in md


def test_markdown_handles_empty_portfolio() -> None:
    md = ab_test_experiments_to_markdown(
        [],
        project_id=10,
        project_name="Test Project",
    )

    assert "## Experiments" in md
    assert "No experiments logged yet." in md
    assert "Total Experiments" in md


def test_markdown_blanks_missing_p_value_and_uplift() -> None:
    md = ab_test_experiments_to_markdown(
        [
            _experiment(
                verdict="INSUFFICIENT_DATA",
                significant=False,
                winner=None,
                relative_uplift_pct=None,
                p_value=None,
            )
        ],
        project_id=10,
    )

    assert "| 1 | Headline test | INSUFFICIENT_DATA | False |  |" in md
    assert "0.000000" not in md
    assert "| — |" in md


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


async def _collect(resp: Any) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp: Any) -> bytes:
    return asyncio.run(_collect(resp))


class _FakeProject:
    def __init__(self, project_id: int = 10, user_id: int = 42) -> None:
        self.id = project_id
        self.user_id = user_id
        self.title = "Test Project"


class _FakeExperiment:
    def __init__(
        self,
        experiment_id: int,
        *,
        name: str = "Headline test",
        verdict: str = "SIGNIFICANT",
        significant: bool = True,
        winner: str | None = "New",
    ) -> None:
        self.id = experiment_id
        self.project_id = 10
        self.name = name
        self.hypothesis = "Clearer value prop lifts conversion"
        self.variant_a_label = "Control"
        self.variant_b_label = "New"
        self.visitors_a = 1000
        self.conversions_a = 100
        self.visitors_b = 1000
        self.conversions_b = 160
        self.alpha = 0.05
        self.power = 0.8
        self.mde = 0.02
        self.verdict = verdict
        self.significant = significant
        self.winner = winner
        self.absolute_uplift = 0.06
        self.relative_uplift_pct = 60.0
        self.z_score = 3.9894
        self.p_value = 0.000066
        self.analysis_json = {
            "variant_a": {
                "label": "Control",
                "visitors": 1000,
                "conversions": 100,
                "conversion_rate": 0.1,
            },
            "variant_b": {
                "label": "New",
                "visitors": 1000,
                "conversions": 160,
                "conversion_rate": 0.16,
            },
            "winner": winner,
            "pooled_conversion_rate": 0.13,
            "absolute_uplift": 0.06,
            "relative_uplift_pct": 60.0,
            "z_score": 3.9894,
            "p_value": 0.000066,
            "confidence_interval": {"low": 0.0306, "high": 0.0894},
            "verdict": verdict,
            "significant": significant,
            "confidence_level": 0.95,
            "visitors_needed_for_observed_uplift": 3841,
            "visitors_needed_for_mde": 3841,
            "narrative": "winner",
            "recommendations": ["Adopt New"],
            "key_signals": [
                {
                    "label": "verdict",
                    "value": "SIGNIFICANT",
                    "severity": "ok",
                }
            ],
            "meta": {
                "alpha": 0.05,
                "power": 0.8,
                "mde": 0.02,
                "min_total_visitors": 40,
                "min_visitors_per_variant": 10,
            },
        }
        self.created_at = datetime(2026, 8, 1, tzinfo=UTC)
        self.updated_at = datetime(2026, 8, 2, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args: object, **kwargs: object) -> _FakeQuery:
        return self

    def order_by(self, *args: object, **kwargs: object) -> _FakeQuery:
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    _NO_PROJECT = object()

    def __init__(
        self,
        *,
        project: _FakeProject | object | None = None,
        experiments: list[_FakeExperiment] | None = None,
    ) -> None:
        self._no_project = project is self._NO_PROJECT
        self.project = (
            project
            if project is not None and project is not self._NO_PROJECT
            else _FakeProject()
        )
        self.experiments = experiments if experiments is not None else []

    def query(self, model: object, *args: object, **kwargs: object) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self._no_project:
                return _FakeQuery([])
            return _FakeQuery([self.project])
        if name == "AbTestExperiment":
            return _FakeQuery(self.experiments)
        return _FakeQuery([])


def _call_route(
    *,
    project_id: int = 10,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import experiments as mod

    return mod.export_ab_test_experiments(
        project_id=project_id,
        format=format,
        db=session if session is not None else _FakeSession(),  # type: ignore[arg-type]
        current_user=type("U", (), {"id": 42})(),
    )


def test_export_route_returns_csv() -> None:
    resp = _call_route(
        session=_FakeSession(experiments=[_FakeExperiment(1)])
    )

    assert resp.media_type == "text/csv; charset=utf-8"
    assert (
        'filename="ab-test-experiments-project-10.csv"'
        in resp.headers["Content-Disposition"]
    )
    body = _body(resp).decode("utf-8")
    assert "section,A/B Experiment Portfolio Summary" in body
    assert "section,Experiments" in body
    assert "Headline test" in body
    assert "Adopt New" in body


def test_export_route_returns_json() -> None:
    resp = _call_route(
        format="json",
        session=_FakeSession(experiments=[_FakeExperiment(1)]),
    )

    assert resp.media_type == "application/json; charset=utf-8"
    assert (
        'filename="ab-test-experiments-project-10.json"'
        in resp.headers["Content-Disposition"]
    )
    parsed = json.loads(_body(resp).decode("utf-8"))
    assert parsed["metadata"]["format_version"] == "1"
    assert parsed["summary"]["total_experiments"] == 1
    assert parsed["experiments"][0]["name"] == "Headline test"
    assert parsed["experiments"][0]["verdict"] == "SIGNIFICANT"


def test_export_route_returns_markdown() -> None:
    resp = _call_route(
        format="md",
        session=_FakeSession(experiments=[_FakeExperiment(1)]),
    )

    assert resp.media_type == "text/markdown; charset=utf-8"
    assert (
        'filename="ab-test-experiments-project-10.md"'
        in resp.headers["Content-Disposition"]
    )
    body = _body(resp).decode("utf-8")
    assert "# Test Project — A/B Experiment Portfolio" in body
    assert "## Summary" in body
    assert "## Experiments" in body
    assert "Adopt New" in body


def test_export_route_rejects_unknown_format() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(format="yaml")

    assert exc_info.value.status_code == 400
    assert "unsupported export format" in exc_info.value.detail


def test_export_route_unknown_format_fails_before_db_read() -> None:
    class _ExplodingSession:
        def query(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("bad format must not touch the database")

    with pytest.raises(HTTPException) as exc_info:
        _call_route(format="xml", session=_ExplodingSession())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 400


def test_export_route_requires_project_ownership() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _call_route(session=_FakeSession(project=_FakeSession._NO_PROJECT))

    assert exc_info.value.status_code == 404


def test_export_route_empty_portfolio_is_valid() -> None:
    resp = _call_route(session=_FakeSession(experiments=[]))

    body = _body(resp).decode("utf-8")
    assert "total_experiments,0" in body
    assert "section,Experiments" in body
