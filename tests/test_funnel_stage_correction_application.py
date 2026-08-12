"""Tests for applying learned stage corrections to Markov matrices."""

from __future__ import annotations

import math

import numpy as np

from app.simulation.conductor import Conductor, ConductorResult
from app.simulation.funnel_stage_calibration import (
    STAGE_TRANSITIONS,
    transition_corrections,
)
from app.simulation.markov import MarkovBehaviourModel
from app.simulation.product_type import ProductType
from app.tasks import simulation_tasks as tasks_mod


class _StubArchitectOutput:
    def __init__(self, cluster_id: str = "metro_power_professional") -> None:
        self.cluster_id = cluster_id

    def transition_overrides(self, output) -> dict[tuple[str, str], float]:
        return {("BROWSE", "CONSIDER"): 0.95}


class _StubCluster:
    cluster_id = "metro_power_professional"


def _base_result() -> object:
    model = MarkovBehaviourModel()
    return model.build_for_cluster(
        cluster=_StubCluster(),  # type: ignore[arg-type]
        architect_outputs={"PricingArchitect": _StubArchitectOutput()},
        env_params={},
        seed=42,
    )


def test_markov_without_corrections_is_unchanged() -> None:
    base = _base_result()
    empty = MarkovBehaviourModel().build_for_cluster(
        cluster=_StubCluster(),  # type: ignore[arg-type]
        architect_outputs={"PricingArchitect": _StubArchitectOutput()},
        env_params={},
        seed=42,
        transition_corrections={},
    )
    np.testing.assert_allclose(base.matrix, empty.matrix, atol=1e-12)
    assert base.conversion_estimate == empty.conversion_estimate


def test_markov_applies_forward_transition_corrections() -> None:
    model = MarkovBehaviourModel()
    base = model.build_for_cluster(
        cluster=_StubCluster(),  # type: ignore[arg-type]
        architect_outputs={"PricingArchitect": _StubArchitectOutput()},
        env_params={},
        seed=42,
    )
    corrected = model.build_for_cluster(
        cluster=_StubCluster(),  # type: ignore[arg-type]
        architect_outputs={"PricingArchitect": _StubArchitectOutput()},
        env_params={},
        seed=42,
        transition_corrections={
            ("BROWSE", "CONSIDER"): 1.2,
            ("CONSIDER", "DECIDE"): 0.8,
            ("DECIDE", "PURCHASE"): 1.5,
        },
    )
    np.testing.assert_allclose(
        corrected.matrix.sum(axis=1), np.ones(7), atol=1e-9
    )
    assert corrected.matrix[1, 2] > base.matrix[1, 2]
    assert corrected.matrix[2, 3] < base.matrix[2, 3]
    assert corrected.matrix[3, 4] > base.matrix[3, 4]


def test_markov_build_factory_passes_corrections_through() -> None:
    corrected = MarkovBehaviourModel.build(
        env_params={},
        assumptions=[],
        seed=42,
        cluster=_StubCluster(),  # type: ignore[arg-type]
        architect_outputs={"PricingArchitect": _StubArchitectOutput()},
        transition_corrections={("BROWSE", "CONSIDER"): 1.25},
    )
    base = _base_result()
    assert isinstance(corrected, object)
    assert corrected.matrix[1, 2] > base.matrix[1, 2]  # type: ignore[attr-defined]


def test_conductor_loads_stage_corrections_from_db() -> None:
    class _Mappings:
        def __init__(self, rows: list[dict]) -> None:
            self._rows = rows

        def all(self) -> list[dict]:
            return self._rows

    class _Result:
        def __init__(self, rows: list[dict]) -> None:
            self._rows = rows

        def mappings(self) -> _Mappings:
            return _Mappings(self._rows)

    class _Db:
        def __init__(self, rows: list[dict]) -> None:
            self._rows = rows

        def execute(self, *args, **kwargs) -> _Result:
            return _Result(self._rows)

    rows = [
        {"stage": "BROWSE", "correction_scalar": 1.2, "confidence_weight": 0.9},
        {"stage": "DECIDE", "correction_scalar": 0.7, "confidence_weight": 0.1},
        {"stage": "NOPE", "correction_scalar": 1.2, "confidence_weight": 0.9},
    ]
    assert Conductor()._load_stage_corrections(_Db(rows), "saas") == {
        "BROWSE": 1.2
    }
    assert Conductor()._load_stage_corrections(None, "saas") == {}


def test_conductor_load_stage_corrections_survives_db_failure() -> None:
    class _BoomDb:
        def execute(self, *args, **kwargs):
            raise RuntimeError("table missing")

    assert Conductor()._load_stage_corrections(_BoomDb(), "saas") == {}


def test_conductor_estimate_cluster_conversion_uses_corrections() -> None:
    outputs = {"PricingArchitect": _StubArchitectOutput()}
    base = Conductor()._estimate_cluster_conversion(outputs)
    lifted = Conductor()._estimate_cluster_conversion(
        outputs,
        stage_corrections={"BROWSE": 1.5},
    )
    assert base > 0.0
    assert lifted > base


def test_conductor_result_exposes_corrections_for_transparency() -> None:
    result = ConductorResult(
        product_type=ProductType.SAAS,
        cluster_results={},
        population_weighted_conversion=0.1,
        domain_reports=[],
        cluster_breakdown={},
        architect_accountability={},
        per_cluster_matrices={},
        funnel_stage_corrections={"BROWSE": 1.1, "DECIDE": 0.9},
    )
    assert result.funnel_stage_corrections == {
        "BROWSE": 1.1,
        "DECIDE": 0.9,
    }
    assert transition_corrections(result.funnel_stage_corrections) == {
        ("BROWSE", "CONSIDER"): 1.1,
        ("DECIDE", "PURCHASE"): 0.9,
    }


def test_derive_chain_scalars_applies_corrections() -> None:
    result = ConductorResult(
        product_type=ProductType.SAAS,
        cluster_results={},
        population_weighted_conversion=0.1,
        domain_reports=[],
        cluster_breakdown={"c1": 0.2},
        architect_accountability={},
        per_cluster_matrices={
            "c1": {
                ("ARRIVE", "BROWSE"): 0.9,
                ("BROWSE", "CONSIDER"): 0.9,
                ("CONSIDER", "DECIDE"): 0.9,
                ("DECIDE", "PURCHASE"): 0.9,
            }
        },
        funnel_stage_corrections={"BROWSE": 1.2},
    )
    scalars = tasks_mod._derive_chain_scalars(result)
    # BROWSE→CONSIDER derived scalar 0.9 × 1.2 = 1.08 → clamped to 1.0.
    assert scalars[1] == 1.0
    assert scalars[0] == 0.9
    assert scalars[2] == 0.9
    assert scalars[3] == 0.9


def test_stage_transitions_cover_three_reported_stages() -> None:
    assert set(STAGE_TRANSITIONS) == {"BROWSE", "CONSIDER", "DECIDE"}
    assert all(
        isinstance(value, tuple) and len(value) == 2
        for value in STAGE_TRANSITIONS.values()
    )
    assert math.isfinite(Conductor()._estimate_cluster_conversion({}))
