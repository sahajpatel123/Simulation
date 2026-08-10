"""Route-level tests for the persistent per-project A/B experiment registry.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.ab_test import (
    AbTestAnalysisIn,
    AbTestExperimentCreate,
    AbTestExperimentUpdate,
    AbTestVariantIn,
)


def _analysis(
    *,
    a_visitors: int = 1000,
    a_conversions: int = 100,
    b_visitors: int = 1000,
    b_conversions: int = 160,
) -> AbTestAnalysisIn:
    return AbTestAnalysisIn(
        variant_a=AbTestVariantIn(
            label="Control",
            visitors=a_visitors,
            conversions=a_conversions,
        ),
        variant_b=AbTestVariantIn(
            label="New",
            visitors=b_visitors,
            conversions=b_conversions,
        ),
    )


class _FakeProject:
    def __init__(self, project_id: int = 10, user_id: int = 42) -> None:
        self.id = project_id
        self.user_id = user_id


class _FakeExperiment:
    def __init__(
        self,
        experiment_id: int,
        *,
        name: str = "Headline test",
        hypothesis: str | None = "Clearer value prop lifts conversion",
        verdict: str = "SIGNIFICANT",
        significant: bool = True,
        winner: str | None = "New",
        analysis: dict | None = None,
    ) -> None:
        self.id = experiment_id
        self.project_id = 10
        self.name = name
        self.hypothesis = hypothesis
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
        self.analysis_json = analysis or {
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
            "winner": "New",
            "pooled_conversion_rate": 0.13,
            "absolute_uplift": 0.06,
            "relative_uplift_pct": 60.0,
            "z_score": 3.9894,
            "p_value": 0.000066,
            "confidence_interval": {"low": 0.0306, "high": 0.0894},
            "verdict": "SIGNIFICANT",
            "significant": True,
            "confidence_level": 0.95,
            "visitors_needed_for_observed_uplift": 3841,
            "visitors_needed_for_mde": 3841,
            "narrative": "winner",
            "recommendations": ["Adopt New"],
            "key_signals": [
                {"label": "verdict", "value": "SIGNIFICANT", "severity": "ok"}
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
        self.updated_at = datetime(2026, 8, 1, tzinfo=UTC)
        self.analysis_json["verdict"] = verdict
        self.analysis_json["significant"] = significant
        self.analysis_json["winner"] = winner


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
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
        self.added: list = []
        self.deleted: list = []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self._no_project:
                return _FakeQuery([])
            return _FakeQuery([self.project])
        if name == "AbTestExperiment":
            return _FakeQuery(self.experiments)
        return _FakeQuery([])

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 500
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime(2026, 8, 2, tzinfo=UTC)
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = datetime(2026, 8, 2, tzinfo=UTC)

    def refresh(self, obj) -> None:
        return None

    def delete(self, obj) -> None:
        self.deleted.append(obj)
        if obj in self.experiments:
            self.experiments.remove(obj)


def _call_create(
    *,
    project_id: int = 10,
    payload: AbTestExperimentCreate | None = None,
    session: _FakeSession | None = None,
):
    from app.api.v1 import experiments as mod

    db = session if session is not None else _FakeSession()
    return mod.create_ab_test_experiment(
        project_id=project_id,
        payload=payload
        or AbTestExperimentCreate(
            name="Headline test",
            hypothesis="Clearer value prop lifts conversion",
            analysis=_analysis(),
        ),
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


def _call_list(
    *,
    project_id: int = 10,
    session: _FakeSession | None = None,
):
    from app.api.v1 import experiments as mod

    return mod.list_ab_test_experiments(
        project_id=project_id,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )


def _call_get(
    *,
    experiment_id: int = 1,
    session: _FakeSession | None = None,
):
    from app.api.v1 import experiments as mod

    return mod.get_ab_test_experiment(
        project_id=10,
        experiment_id=experiment_id,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )


def _call_update(
    *,
    experiment_id: int = 1,
    payload: AbTestExperimentUpdate,
    session: _FakeSession | None = None,
):
    from app.api.v1 import experiments as mod

    return mod.update_ab_test_experiment(
        project_id=10,
        experiment_id=experiment_id,
        payload=payload,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )


def _call_delete(
    *,
    experiment_id: int = 1,
    session: _FakeSession | None = None,
):
    from app.api.v1 import experiments as mod

    return mod.delete_ab_test_experiment(
        project_id=10,
        experiment_id=experiment_id,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )


class TestCreate:
    def test_persists_analysis_snapshot(self) -> None:
        session = _FakeSession()
        out = _call_create(session=session)

        assert out.id == 500
        assert out.project_id == 10
        assert out.name == "Headline test"
        assert out.verdict == "SIGNIFICANT"
        assert out.significant is True
        assert out.winner == "New"
        assert out.analysis.winner == "New"
        assert out.analysis.variant_a.conversion_rate == pytest.approx(0.1)

        row = session.added[0]
        assert row.verdict == "SIGNIFICANT"
        assert row.significant is True
        assert row.visitors_a == 1000
        assert row.conversions_b == 160
        assert row.analysis_json["verdict"] == "SIGNIFICANT"
        assert row.analysis_json["meta"]["alpha"] == pytest.approx(0.05)

    def test_project_must_be_owned(self) -> None:
        session = _FakeSession(project=_FakeSession._NO_PROJECT)
        with pytest.raises(HTTPException) as exc:
            _call_create(session=session)
        assert exc.value.status_code == 404

    def test_schema_rejects_conversions_above_visitors(self) -> None:
        with pytest.raises(ValidationError):
            AbTestExperimentCreate(
                name="Bad",
                analysis=_analysis(a_visitors=10, a_conversions=20),
            )

    def test_schema_rejects_blank_name(self) -> None:
        with pytest.raises(ValidationError):
            AbTestExperimentCreate(name="   ", analysis=_analysis())


class TestListAndGet:
    def test_list_returns_all_experiments_with_snapshots(self) -> None:
        session = _FakeSession(
            experiments=[
                _FakeExperiment(1),
                _FakeExperiment(2, name="Pricing page test", verdict="TRENDING"),
            ]
        )
        out = _call_list(session=session)

        assert [item.name for item in out] == [
            "Headline test",
            "Pricing page test",
        ]
        assert out[0].verdict == "SIGNIFICANT"
        assert out[1].verdict == "TRENDING"
        assert out[1].analysis.verdict == "TRENDING"

    def test_list_requires_owned_project(self) -> None:
        session = _FakeSession(project=_FakeSession._NO_PROJECT)
        with pytest.raises(HTTPException) as exc:
            _call_list(session=session)
        assert exc.value.status_code == 404

    def test_get_returns_stored_experiment(self) -> None:
        session = _FakeSession(experiments=[_FakeExperiment(7)])
        out = _call_get(experiment_id=7, session=session)

        assert out.id == 7
        assert out.name == "Headline test"
        assert out.verdict == "SIGNIFICANT"
        assert out.analysis.recommendations == ["Adopt New"]

    def test_get_missing_experiment_raises_404(self) -> None:
        session = _FakeSession(experiments=[])
        with pytest.raises(HTTPException) as exc:
            _call_get(experiment_id=7, session=session)
        assert exc.value.status_code == 404


class TestUpdate:
    def test_analysis_recomputes_verdict(self) -> None:
        session = _FakeSession(
            experiments=[_FakeExperiment(3, verdict="INCONCLUSIVE")]
        )
        out = _call_update(
            experiment_id=3,
            payload=AbTestExperimentUpdate(analysis=_analysis()),
            session=session,
        )

        assert out.verdict == "SIGNIFICANT"
        assert out.significant is True
        assert out.winner == "New"
        row = session.experiments[0]
        assert row.verdict == "SIGNIFICANT"
        assert row.visitors_a == 1000
        assert row.conversions_b == 160
        assert row.analysis_json["verdict"] == "SIGNIFICANT"

    def test_name_only_update_keeps_verdict(self) -> None:
        session = _FakeSession(
            experiments=[_FakeExperiment(4, verdict="TRENDING")]
        )
        out = _call_update(
            experiment_id=4,
            payload=AbTestExperimentUpdate(name="Renamed test"),
            session=session,
        )

        assert out.name == "Renamed test"
        assert out.verdict == "TRENDING"
        assert session.experiments[0].verdict == "TRENDING"

    def test_hypothesis_null_clears_it(self) -> None:
        session = _FakeSession(experiments=[_FakeExperiment(5)])
        out = _call_update(
            experiment_id=5,
            payload=AbTestExperimentUpdate(hypothesis=None),
            session=session,
        )

        assert out.hypothesis is None
        assert session.experiments[0].hypothesis is None

    def test_empty_payload_rejected_by_schema(self) -> None:
        with pytest.raises(ValidationError):
            AbTestExperimentUpdate()

    def test_name_null_rejected_by_schema(self) -> None:
        with pytest.raises(ValidationError):
            AbTestExperimentUpdate(name=None)

    def test_missing_experiment_raises_404(self) -> None:
        session = _FakeSession(experiments=[])
        with pytest.raises(HTTPException) as exc:
            _call_update(
                experiment_id=9,
                payload=AbTestExperimentUpdate(name="nope"),
                session=session,
            )
        assert exc.value.status_code == 404


class TestDelete:
    def test_delete_removes_experiment(self) -> None:
        session = _FakeSession(experiments=[_FakeExperiment(6)])
        resp = _call_delete(experiment_id=6, session=session)

        assert resp.status_code == 204
        assert session.experiments == []
        assert [row.id for row in session.deleted] == [6]

    def test_delete_missing_experiment_raises_404(self) -> None:
        session = _FakeSession(experiments=[])
        with pytest.raises(HTTPException) as exc:
            _call_delete(experiment_id=6, session=session)
        assert exc.value.status_code == 404
