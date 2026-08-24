"""
Tests for the accuracy-adjusted prediction-range digest.

Covers the pure builder, the schema contract, and route-level behaviour
(ownership, status gates, calibration-source fallback, and edge cases).
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

# ``app.api.v1`` eagerly imports the billing router, which imports the
# razorpay SDK. In test environments without the package installed (or
# with a broken transitive dependency), stub it the same way the existing
# route-level tests do so we can import the simulations module.
if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


from app.schemas.prediction_range import (  # noqa: E402
    LABEL_INSUFFICIENT_DATA,
    LABEL_NEEDS_ATTENTION,
    LABEL_POORLY_CALIBRATED,
    LABEL_WELL_CALIBRATED,
    PredictionRangeOut,
)
from app.simulation.prediction_range import (  # noqa: E402
    DEFAULT_SPREAD,
    MIN_OUTCOMES_FOR_RANGE,
    build_prediction_range,
    extract_predicted_conversion,
)


def _results(cr: float | None = 0.08) -> dict:
    if cr is None:
        return {"raw_funnel": {"total_agents": 100}}
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "cluster_breakdown": {"metro_power_professional": 0.08},
    }


def _pairs(count: int, mae: float = 0.01) -> list[tuple[float, float]]:
    """Return ``count`` (predicted, actual) pairs with roughly ``mae`` error."""
    pairs: list[tuple[float, float]] = []
    for i in range(count):
        pred = 0.08
        actual = pred + mae if i % 2 == 0 else pred - mae
        pairs.append((pred, actual))
    return pairs


class _FakeProject:
    def __init__(self, pid: int) -> None:
        self.id = pid


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        project_id: int = 10,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.status = status
        self.error_message = error_message
        self.results_json = results if results is not None else _results()


class _FakeQuery:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self.rows = self.rows[:n]
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


def _is_outcome_query(args: tuple) -> bool:
    """True if the query targets the Outcome model or its columns."""
    for arg in args:
        cls = getattr(arg, "class_", None)
        if cls is not None and getattr(cls, "__name__", "") == "Outcome":
            return True
        if isinstance(arg, type) and getattr(arg, "__name__", "") == "Outcome":
            return True
    return False


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        *,
        project_pairs: list[tuple[float, float]] | None = None,
        user_pairs: list[tuple[float, float]] | None = None,
        owned_project_ids: list[int] | None = None,
    ) -> None:
        self.sim = sim or _FakeSimulation()
        self.project_pairs = project_pairs or []
        self.user_pairs = user_pairs or []
        self.owned_project_ids = owned_project_ids or [self.sim.project_id]
        self.outcome_calls = 0

    def query(self, *args, **kwargs):
        if _is_outcome_query(args):
            self.outcome_calls += 1
            if self.outcome_calls == 1:
                return _FakeQuery(list(self.project_pairs))
            return _FakeQuery(list(self.user_pairs))
        first = args[0]
        name = getattr(first, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim])
        if name == "Project":
            return _FakeQuery([_FakeProject(pid) for pid in self.owned_project_ids])
        return _FakeQuery([])


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
) -> PredictionRangeOut:
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_prediction_range(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


# ---------------------------------------------------------------------------
# Pure builder + extraction
# ---------------------------------------------------------------------------


def test_extract_predicted_conversion_handles_all_shapes() -> None:
    assert extract_predicted_conversion({"population_weighted_conversion": 0.08}) == pytest.approx(0.08)
    assert extract_predicted_conversion({"conversion_rate": 0.12}) == pytest.approx(0.12)
    assert extract_predicted_conversion({"mean_conversion_rate": 0.03}) == pytest.approx(0.03)
    assert extract_predicted_conversion(
        {"raw_funnel": {"conversion_rate": 0.07}}
    ) == pytest.approx(0.07)
    assert extract_predicted_conversion(_results(cr=None)) is None
    assert extract_predicted_conversion({}) is None
    assert extract_predicted_conversion(None) is None
    assert extract_predicted_conversion("not-a-dict") is None


def test_build_prediction_range_well_calibrated() -> None:
    pairs = _pairs(5, mae=0.01)
    payload = build_prediction_range(
        0.08,
        pairs,
        simulation_id=1,
        project_id=2,
        calibration_source="project",
    )

    assert payload["confidence_label"] == LABEL_WELL_CALIBRATED
    assert payload["calibration_sample_count"] == 5
    assert payload["low"] <= 0.08 <= payload["high"]
    assert payload["spread"] is not None
    assert payload["low"] >= 0.0
    assert payload["high"] <= 1.0
    assert any(s["label"] == "calibration_source" and s["value"] == "project" for s in payload["key_signals"])


def test_build_prediction_range_needs_attention() -> None:
    pairs = _pairs(5, mae=0.03)
    payload = build_prediction_range(
        0.08,
        pairs,
        simulation_id=1,
        project_id=2,
    )

    assert payload["confidence_label"] == LABEL_NEEDS_ATTENTION
    assert payload["mae"] == pytest.approx(0.03, abs=0.001)
    assert payload["spread"] is not None


def test_build_prediction_range_poorly_calibrated() -> None:
    pairs = _pairs(5, mae=0.07)
    payload = build_prediction_range(
        0.08,
        pairs,
        simulation_id=1,
        project_id=2,
    )

    assert payload["confidence_label"] == LABEL_POORLY_CALIBRATED
    assert payload["spread"] is not None
    assert payload["spread"] <= 0.30


def test_build_prediction_range_insufficient_data_keeps_conservative_band() -> None:
    payload = build_prediction_range(
        0.08,
        _pairs(2, mae=0.01),
        simulation_id=1,
        project_id=2,
    )

    assert payload["confidence_label"] == LABEL_INSUFFICIENT_DATA
    assert payload["calibration_sample_count"] == 2
    assert payload["low"] is not None
    assert payload["high"] is not None
    assert "conservative" in payload["narrative"]


def test_build_prediction_range_no_pairs_uses_default_spread() -> None:
    payload = build_prediction_range(
        0.08,
        [],
        simulation_id=1,
        project_id=2,
    )

    assert payload["confidence_label"] == LABEL_INSUFFICIENT_DATA
    assert payload["spread"] == pytest.approx(DEFAULT_SPREAD)
    assert payload["low"] == pytest.approx(max(0.0, 0.08 - DEFAULT_SPREAD))
    assert payload["high"] == pytest.approx(min(1.0, 0.08 + DEFAULT_SPREAD))


def test_build_prediction_range_filters_unusable_pairs() -> None:
    pairs: list[tuple[object, object]] = [
        (0.08, 0.06),        # usable
        (None, 0.05),        # missing prediction
        (0.08, None),        # missing actual
        ("not-a-rate", 0.05),  # non-numeric prediction
        (0.08, True),        # boolean actual
        (0.08, float("nan")),  # non-finite actual
    ]
    payload = build_prediction_range(
        0.08,
        pairs,  # type: ignore[arg-type]
        simulation_id=1,
        project_id=2,
    )

    assert payload["calibration_sample_count"] == 1
    assert payload["meta"]["raw_pairs_supplied"] == len(pairs)
    assert payload["meta"]["usable_pairs_used"] == 1
    assert payload["mae"] == pytest.approx(0.02, abs=0.001)
    assert payload["rmse"] == pytest.approx(0.02, abs=0.001)
    assert "Found 6 outcome row(s), but only 1 had a usable" in payload["narrative"]


def test_build_prediction_range_clamps_out_of_range_pairs() -> None:
    # A conversion rate outside [0, 1] is a data-entry error; clamp it so a
    # single bad row can't poison the whole calibration aggregate.
    payload = build_prediction_range(
        0.08,
        [(0.08, 2.0), (0.08, -1.0), (0.08, 0.06)],
        simulation_id=1,
        project_id=2,
    )

    assert payload["calibration_sample_count"] == 3
    assert payload["mae"] == pytest.approx(0.34, abs=0.001)
    assert payload["meta"]["raw_pairs_supplied"] == 3
    assert payload["meta"]["usable_pairs_used"] == 3


def test_build_prediction_range_enough_usable_pairs_still_calibrates() -> None:
    payload = build_prediction_range(
        0.08,
        [
            (None, 0.05),
            (0.08, 0.07),
            (0.08, 0.09),
            (0.08, 0.07),
            (0.08, 0.09),
        ],
        simulation_id=1,
        project_id=2,
    )

    assert payload["calibration_sample_count"] == 4
    assert payload["confidence_label"] == LABEL_WELL_CALIBRATED
    assert payload["meta"]["raw_pairs_supplied"] == 5
    assert payload["meta"]["usable_pairs_used"] == 4
    assert "Across 4 recorded outcome(s)" in payload["narrative"]
    assert "conservative" not in payload["narrative"]


def test_build_prediction_range_predicted_none() -> None:
    payload = build_prediction_range(
        None,
        _pairs(5, mae=0.01),
        simulation_id=1,
        project_id=2,
    )

    assert payload["predicted_conversion_rate"] is None
    assert payload["low"] is None
    assert payload["high"] is None
    assert payload["spread"] is None
    assert payload["confidence_label"] == LABEL_INSUFFICIENT_DATA
    assert "No predicted conversion rate" in payload["narrative"]


def test_build_prediction_range_clamps_to_unit_interval() -> None:
    # A near-100% prediction with a wide spread should not exceed 1.0.
    payload = build_prediction_range(
        0.98,
        [(0.90, 0.70), (0.95, 0.60), (0.99, 0.50)],
        simulation_id=1,
        project_id=2,
    )

    assert payload["high"] <= 1.0
    assert payload["low"] >= 0.0
    assert payload["low"] < payload["high"]


def test_schema_contract() -> None:
    payload = build_prediction_range(
        0.08,
        _pairs(4),
        simulation_id=1,
        project_id=2,
    )
    out = PredictionRangeOut(**payload)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.confidence_label in {
        LABEL_INSUFFICIENT_DATA,
        LABEL_WELL_CALIBRATED,
        LABEL_NEEDS_ATTENTION,
        LABEL_POORLY_CALIBRATED,
    }
    assert out.key_signals


# ---------------------------------------------------------------------------
# Route-level behaviour
# ---------------------------------------------------------------------------


def test_completed_simulation_returns_prediction_range_payload() -> None:
    out = _call_route(
        session=_FakeSession(
            _FakeSimulation(results=_results(0.08)),
            project_pairs=_pairs(4),
        )
    )

    assert isinstance(out, PredictionRangeOut)
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.predicted_conversion_rate == pytest.approx(0.08)
    assert out.low is not None
    assert out.high is not None
    assert out.low <= 0.08 <= out.high
    assert out.calibration_source == "project"


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(
        _FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_pending_simulation_raises_409() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_empty_results_raises_422() -> None:
    session = _FakeSession(_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_missing_predicted_rate_returns_insufficient_payload() -> None:
    out = _call_route(
        session=_FakeSession(
            _FakeSimulation(results=_results(cr=None)),
            project_pairs=_pairs(4),
        )
    )

    assert out.predicted_conversion_rate is None
    assert out.low is None
    assert out.high is None
    assert out.confidence_label == LABEL_INSUFFICIENT_DATA


def test_user_level_calibration_fallback_used() -> None:
    out = _call_route(
        session=_FakeSession(
            _FakeSimulation(results=_results(0.08)),
            project_pairs=_pairs(2),
            user_pairs=_pairs(4),
        )
    )

    assert out.calibration_source == "user"
    assert out.calibration_sample_count >= MIN_OUTCOMES_FOR_RANGE


def test_no_outcomes_returns_insufficient_and_source_none() -> None:
    out = _call_route(
        session=_FakeSession(
            _FakeSimulation(results=_results(0.08)),
            project_pairs=[],
            user_pairs=[],
        )
    )

    assert out.calibration_source == "none"
    assert out.confidence_label == LABEL_INSUFFICIENT_DATA
    assert out.low is not None
    assert out.high is not None


def test_prediction_range_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/{simulation_id}/prediction-range" in paths


def test_prediction_range_route_uses_get() -> None:
    from app.api.v1 import simulations as sim_mod

    for route in sim_mod.router.routes:
        if getattr(route, "path", "") == (
            "/simulations/{simulation_id}/prediction-range"
        ):
            assert "GET" in (route.methods or set())
            break
    else:
        raise AssertionError("prediction-range route not found")
