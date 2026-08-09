"""Integration tests for the Conductor's learned-correction wiring.

The Conductor is the single place where ``architect_corrections`` rows
finally reach a running simulation: it loads them once per run and
applies them to each architect output before the Markov funnel is
built. These tests pin that wiring, the fail-open behaviour when the DB
read breaks, and the diagnostics counter that makes the calibration
loop observable in the persisted result payload.
"""
from __future__ import annotations

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import Conductor
from app.simulation.correction_application import Correction
from app.simulation.product_type import ProductType


def _correction(
    *,
    architect_name: str = "PricingArchitect",
    cluster_id: str = "ALL",
    scalar: float = 0.5,
    confidence: float = 0.8,
) -> Correction:
    return Correction(
        architect_name=architect_name,
        product_type="saas",
        product_attribute="ALL",
        cluster_id=cluster_id,
        correction_scalar=scalar,
        confidence_weight=confidence,
        effective_sample_count=25.0,
        scope="CATEGORY_GLOBAL",
    )


def _run(conductor: Conductor, **kwargs: object) -> object:
    return conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999,
            "description": "A saas crm dashboard for small teams",
        },
        assumptions=[],
        product_type=ProductType.SAAS,
        **kwargs,
    )


def test_run_applies_learned_corrections_and_counts_them(monkeypatch: object) -> None:
    cluster_id = ClusterRegistry().all_clusters()[0].cluster_id
    baseline = _run(Conductor())
    corrections = {
        ("PricingArchitect", cluster_id): _correction(cluster_id=cluster_id)
    }
    monkeypatch.setattr(
        Conductor,
        "_load_corrections",
        lambda self, db, product_type: corrections,
    )

    corrected = _run(Conductor(), db=object())

    corrected_output = corrected.cluster_results[cluster_id]["PricingArchitect"]
    baseline_output = baseline.cluster_results[cluster_id]["PricingArchitect"]

    assert (
        corrected_output.metrics["will_pay_probability"]
        == baseline_output.metrics["will_pay_probability"] * 0.5
    )
    assert corrected.diagnostics.applied_corrections == 1
    assert corrected.diagnostics.to_dict()["applied_corrections"] == 1
    # The corrected metrics flow into the cluster conversion estimate.
    assert corrected.cluster_breakdown[cluster_id] != baseline.cluster_breakdown[
        cluster_id
    ]


def test_run_with_empty_corrections_applies_nothing(monkeypatch: object) -> None:
    monkeypatch.setattr(
        Conductor,
        "_load_corrections",
        lambda self, db, product_type: {},
    )

    result = _run(Conductor(), db=object())

    assert result.diagnostics.applied_corrections == 0
    assert result.diagnostics.to_dict()["applied_corrections"] == 0


def test_load_corrections_filters_rows_and_parses() -> None:
    class FakeResult:
        def __init__(self, rows: list[dict]) -> None:
            self._rows = rows

        def mappings(self) -> FakeResult:
            return self

        def all(self) -> list[dict]:
            return self._rows

    class FakeDb:
        def __init__(self, rows: list[dict]) -> None:
            self.rows = rows
            self.calls: list[tuple] = []

        def execute(self, statement: object, params: dict | None = None) -> FakeResult:
            self.calls.append((statement, params))
            return FakeResult(self.rows)

    rows = [
        {
            "architect_name": "PricingArchitect",
            "product_type": "saas",
            "product_attribute": "ALL",
            "cluster_id": "ALL",
            "correction_scalar": 0.9,
            "confidence_weight": 0.8,
            "effective_sample_count": 40.0,
            "scope": "CATEGORY_GLOBAL",
        },
        {
            "architect_name": "TrustArchitect",
            "product_type": "saas",
            "product_attribute": "ALL",
            "cluster_id": "ALL",
            "correction_scalar": 0.8,
            "confidence_weight": 0.1,  # below the gate -> excluded
            "effective_sample_count": 40.0,
            "scope": "CATEGORY_GLOBAL",
        },
    ]
    db = FakeDb(rows)

    corrections = Conductor()._load_corrections(db, "saas")

    assert list(corrections.keys()) == [("PricingArchitect", "ALL")]
    assert corrections[("PricingArchitect", "ALL")].correction_scalar == 0.9
    assert len(db.calls) == 1
    assert db.calls[0][1] == {"pt": "saas", "min_conf": 0.2}


def test_load_corrections_returns_none_without_db() -> None:
    assert Conductor()._load_corrections(None, "saas") is None


def test_load_corrections_failure_fails_open() -> None:
    class BrokenDb:
        def execute(self, statement: object, params: dict | None = None) -> object:
            raise RuntimeError("db unavailable")

    assert Conductor()._load_corrections(BrokenDb(), "saas") is None


def test_diagnostics_payload_includes_applied_correction_count() -> None:
    from app.simulation.conductor import ConductorDiagnostics

    diagnostics = ConductorDiagnostics()
    diagnostics.applied_corrections = 7

    assert diagnostics.to_dict()["applied_corrections"] == 7
