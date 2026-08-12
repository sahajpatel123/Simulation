"""Route-level tests for the Layer 5 cluster-trait calibration trigger.

``POST /projects/{id}/outcome-feedback`` must enqueue
``calibration.run_cluster_trait_calibration`` exactly when
``CalibrationEngine.clusters_ready_for_trait_calibration`` reports that at
least one cluster crossed the effective-sample gate, and must stay quiet
when no cluster is ready yet.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.schemas.outcome import OutcomeFeedbackRequest

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeSimulation:
    def __init__(self) -> None:
        self.id = 11
        self.project_id = 10
        self.results_json = {
            "mean_conversion_rate": 0.20,
            "product_type_detected": "saas",
        }
        self.signal_quality = 0.8


class _FakeQuery:
    def __init__(self, items: list[object] | None = None) -> None:
        self.items = items if items is not None else [SimpleNamespace(id=10)]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def fetchone(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def fetchall(self):
        if isinstance(self._value, list):
            return self._value
        return [] if self._value is None else [self._value]


class _FakeSession:
    """Serves queued execute() responses and records every call."""

    def __init__(self, execute_responses: list[object]) -> None:
        self._queue = list(execute_responses)
        self.calls: list[dict | None] = []
        self.commits = 0

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([_FakeSimulation()])
        return _FakeQuery([SimpleNamespace(id=10, user_id=42)])

    def execute(self, statement, params: dict | None = None):
        self.calls.append(params)
        value = self._queue.pop(0) if self._queue else None
        return _FakeResult(value)

    def commit(self) -> None:
        self.commits += 1


def _outcome_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        actual_conversion_rate=0.20,
        product_changed_since_sim=False,
        data_confidence="ESTIMATED",
    )


def _base_responses(ready: int = 1) -> list[object]:
    """Queue of execute() responses in call order for the happy path."""
    return [
        None,  # INSERT founder_outcomes
        _outcome_row(),  # SELECT founder_outcomes
        None,  # validate_outcome UPDATE
        [],  # cluster_run_summaries fetchall (Layer 4)
        [],  # user_simulation_accuracy_history fetchall (trend)
        None,  # INSERT user_simulation_accuracy_history
        SimpleNamespace(eff=0.0),  # Layer 2 effective-count query
        SimpleNamespace(ready=ready),  # Layer 5 readiness query
        SimpleNamespace(ready=ready),  # Layer 6 readiness query
        SimpleNamespace(accuracy_trend="INSUFFICIENT_DATA"),  # latest trend
    ]


def test_outcome_feedback_enqueues_cluster_trait_calibration_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)
    session = _FakeSession(_base_responses(ready=1))

    from app.api.v1 import outcomes as out_mod

    with (
        patch(
            "app.tasks.calibration_tasks.run_cluster_trait_calibration.delay"
        ) as trait_delay,
        patch(
            "app.tasks.calibration_tasks.run_systematic_bias_update.delay"
        ) as bias_delay,
        patch(
            "app.tasks.calibration_tasks.run_funnel_stage_calibration.delay"
        ) as stage_delay,
    ):
        out = out_mod.submit_outcome_feedback(
            project_id=10,
            body=OutcomeFeedbackRequest(
                simulation_id=11,
                actual_conversion_rate=0.20,
            ),
            db=session,
            current_user=SimpleNamespace(id=42),
        )

    trait_delay.assert_called_once_with()
    bias_delay.assert_not_called()
    stage_delay.assert_called_once_with()
    assert out["stored"] is True
    assert out["will_improve_model"] is True
    assert out["learning_weight"] == pytest.approx(0.48)
    gate_calls = [
        p for p in session.calls if p is not None and "min_eff" in p
    ]
    assert gate_calls, "expected a Layer 5 readiness query"
    assert gate_calls[0]["min_eff"] == 5.0


def test_outcome_feedback_skips_cluster_trait_calibration_when_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)
    session = _FakeSession(_base_responses(ready=0))

    with (
        patch(
            "app.tasks.calibration_tasks.run_cluster_trait_calibration.delay"
        ) as trait_delay,
        patch(
            "app.tasks.calibration_tasks.run_systematic_bias_update.delay"
        ) as bias_delay,
        patch(
            "app.tasks.calibration_tasks.run_funnel_stage_calibration.delay"
        ) as stage_delay,
    ):
        from app.api.v1 import outcomes as out_mod

        out_mod.submit_outcome_feedback(
            project_id=10,
            body=OutcomeFeedbackRequest(
                simulation_id=11,
                actual_conversion_rate=0.20,
            ),
            db=session,
            current_user=SimpleNamespace(id=42),
        )

    trait_delay.assert_not_called()
    bias_delay.assert_not_called()
    stage_delay.assert_not_called()
