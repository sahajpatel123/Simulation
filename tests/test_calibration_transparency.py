"""Tests for the per-simulation calibration transparency feature.

Covers the pure aggregation helper (``build_calibration_transparency``)
and the route wiring for
``GET /api/v1/simulations/{simulation_id}/calibration-transparency``.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.calibration_transparency import (  # noqa: E402
    CalibrationTransparencyOut,
)
from app.simulation.calibration_transparency import (  # noqa: E402
    build_calibration_transparency,
    coerce_recorded_applied_corrections,
)


def _row(
    *,
    architect_name: str = "PricingArchitect",
    cluster_id: str = "ALL",
    scalar: float = 0.8,
    confidence: float = 0.9,
    samples: float = 20.0,
) -> dict[str, Any]:
    return {
        "architect_name": architect_name,
        "product_type": "saas",
        "product_attribute": "ALL",
        "cluster_id": cluster_id,
        "correction_scalar": scalar,
        "confidence_weight": confidence,
        "effective_sample_count": samples,
        "scope": "CATEGORY_GLOBAL",
    }


def _clusters() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(cluster_id="c1", name="Cluster one"),
        SimpleNamespace(cluster_id="c2", name="Cluster two"),
    ]


# ---------------------------------------------------------------------------
# Pure aggregation helper
# ---------------------------------------------------------------------------


def test_builder_empty_input_returns_zeroed_payload() -> None:
    out = build_calibration_transparency(
        [],
        product_type="saas",
        clusters=[],
        architect_names=[],
        simulation_id=1,
        project_id=10,
    )

    assert out["simulation_id"] == 1
    assert out["project_id"] == 10
    assert out["product_type"] == "saas"
    assert out["eligible_pairs"] == 0
    assert out["corrected_pairs"] == 0
    assert out["coverage_pct"] == 0.0
    assert out["available_correction_rows"] == 0
    assert out["by_architect"] == []
    assert out["by_cluster"] == []
    assert out["corrections"] == []


def test_builder_rolls_up_global_and_cluster_specific_corrections() -> None:
    rows = [
        _row(
            architect_name="PricingArchitect",
            cluster_id="ALL",
            scalar=0.8,
            confidence=0.9,
            samples=20.0,
        ),
        _row(
            architect_name="TrustArchitect",
            cluster_id="c1",
            scalar=1.2,
            confidence=0.8,
            samples=10.0,
        ),
    ]
    out = build_calibration_transparency(
        rows,
        product_type="saas",
        clusters=_clusters(),
        architect_names=["PricingArchitect", "TrustArchitect"],
        simulation_id=1,
        project_id=10,
        corrections_limit=50,
    )

    assert out["eligible_pairs"] == 4
    assert out["corrected_pairs"] == 3
    assert out["coverage_pct"] == 75.0
    assert out["available_correction_rows"] == 2
    assert out["cluster_count"] == 2
    assert out["architect_stack_size"] == 2

    by_architect = {row["architect_name"]: row for row in out["by_architect"]}
    pricing = by_architect["PricingArchitect"]
    assert pricing["corrected_clusters"] == 2
    assert pricing["coverage_pct"] == 100.0
    assert pricing["avg_scalar"] == 0.8
    assert pricing["max_abs_drift"] == 0.2
    assert pricing["sample_sum"] == 40.0
    assert pricing["direction"] == "LOWERS"

    trust = by_architect["TrustArchitect"]
    assert trust["corrected_clusters"] == 1
    assert trust["coverage_pct"] == 50.0
    assert trust["avg_scalar"] == 1.2
    assert trust["max_abs_drift"] == 0.2
    assert trust["direction"] == "RAISES"

    by_cluster = {row["cluster_id"]: row for row in out["by_cluster"]}
    assert by_cluster["c1"]["corrected_architects"] == 2
    assert by_cluster["c1"]["coverage_pct"] == 100.0
    assert by_cluster["c1"]["avg_scalar"] == 1.0
    assert by_cluster["c1"]["most_corrected_architect"] == "PricingArchitect"
    assert by_cluster["c2"]["corrected_architects"] == 1
    assert by_cluster["c2"]["coverage_pct"] == 50.0
    assert by_cluster["c2"]["avg_scalar"] == 0.8

    assert len(out["corrections"]) == 3
    validated = CalibrationTransparencyOut(**out)
    assert validated.corrected_pairs == 3
    assert validated.by_cluster[0].cluster_id == "c1"


def test_builder_reports_strongest_architect_per_cluster() -> None:
    rows = [
        _row(
            architect_name="PricingArchitect",
            cluster_id="ALL",
            scalar=1.1,
            confidence=0.9,
        ),
        _row(
            architect_name="TrustArchitect",
            cluster_id="c1",
            scalar=1.4,
            confidence=0.9,
        ),
    ]
    out = build_calibration_transparency(
        rows,
        product_type="saas",
        clusters=_clusters(),
        architect_names=["PricingArchitect", "TrustArchitect"],
        simulation_id=1,
        project_id=10,
    )

    by_cluster = {row["cluster_id"]: row for row in out["by_cluster"]}
    # TrustArchitect has the larger |scalar - 1| drift on c1, so it must be
    # reported as the most-corrected architect, not PricingArchitect.
    assert by_cluster["c1"]["most_corrected_architect"] == "TrustArchitect"
    assert by_cluster["c2"]["most_corrected_architect"] == "PricingArchitect"


def test_coerce_recorded_applied_corrections_accepts_only_whole_counts() -> None:
    cases: list[tuple[Any, int | None]] = [
        (3, 3),
        (3.0, 3),
        ("3", 3),
        ("3.0", 3),
        (True, None),
        (False, None),
        (-1, None),
        (-1.0, None),
        ("-2", None),
        (3.5, None),
        ("3.5", None),
        (float("nan"), None),
        ("not-a-count", None),
        (None, None),
        ([], None),
    ]
    for value, expected in cases:
        assert coerce_recorded_applied_corrections(value) == expected


def test_builder_ignores_low_confidence_and_other_product_types() -> None:
    rows = [
        _row(cluster_id="ALL", confidence=0.1),
        _row(architect_name="TrustArchitect", cluster_id="ALL", confidence=0.9),
        {
            **_row(
                architect_name="PricingArchitect",
                cluster_id="ALL",
                confidence=0.9,
            ),
            "product_type": "marketplace",
        },
    ]
    out = build_calibration_transparency(
        rows,
        product_type="saas",
        clusters=_clusters(),
        architect_names=["PricingArchitect", "TrustArchitect"],
        simulation_id=1,
        project_id=10,
    )

    # Only the TrustArchitect ALL row clears the confidence + product gate.
    assert out["corrected_pairs"] == 2
    assert out["available_correction_rows"] == 1
    assert all(
        row["architect_name"] == "TrustArchitect"
        for row in out["corrections"]
    )


def test_builder_respects_corrections_limit() -> None:
    rows = [
        _row(
            architect_name="PricingArchitect",
            cluster_id="ALL",
            scalar=0.7,
            confidence=0.9,
        ),
        _row(
            architect_name="TrustArchitect",
            cluster_id="ALL",
            scalar=1.1,
            confidence=0.9,
        ),
    ]
    out = build_calibration_transparency(
        rows,
        product_type="saas",
        clusters=_clusters(),
        architect_names=["PricingArchitect", "TrustArchitect"],
        simulation_id=1,
        project_id=10,
        corrections_limit=1,
    )

    assert out["corrected_pairs"] == 4
    assert out["corrections_returned"] == 1
    assert out["corrections"][0]["architect_name"] == "PricingArchitect"


def test_builder_handles_plain_string_clusters() -> None:
    out = build_calibration_transparency(
        [_row(cluster_id="ALL", scalar=0.9)],
        product_type="saas",
        clusters=["c1", "c2"],
        architect_names=["PricingArchitect"],
        simulation_id=1,
        project_id=10,
    )

    assert out["corrected_pairs"] == 2
    assert out["by_cluster"][0]["cluster_name"] == "c1"


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class _FakeSimulation:
    def __init__(
        self,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = 1
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.results_json = (
            results
            if results is not None
            else {
                "product_type_detected": "saas",
                "conductor_diagnostics": {"applied_corrections": 3},
            }
        )


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeDB:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[object, dict[str, Any] | None]] = []

    def execute(
        self,
        statement: object,
        params: dict[str, Any] | None = None,
    ) -> _FakeResult:
        self.calls.append((statement, params))
        return _FakeResult(self.rows)


def test_route_returns_calibration_transparency_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation()
    monkeypatch.setattr(
        sim_mod,
        "_get_owned_simulation",
        lambda simulation_id, user_id, db: sim,
    )
    db = _FakeDB(
        [
            _row(architect_name="PricingArchitect", cluster_id="ALL", scalar=0.8),
            _row(
                architect_name="TrustArchitect",
                cluster_id="metro_power_professional",
                scalar=1.2,
            ),
        ]
    )

    out = sim_mod.get_calibration_transparency(
        simulation_id=1,
        corrections_limit=10,
        db=db,
        current_user=SimpleNamespace(id=42),
    )

    assert isinstance(out, CalibrationTransparencyOut)
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.recorded_applied_corrections == 3
    assert out.corrected_pairs > 0
    assert out.coverage_pct > 0.0
    assert out.corrections_limit == 10
    assert len(db.calls) == 1
    assert db.calls[0][1] == {"pt": "saas"}


def test_route_rejects_non_completed_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import simulations as sim_mod

    for status, expected in (
        ("FAILED", 422),
        ("PENDING", 409),
    ):
        sim = _FakeSimulation(status=status, error_message="boom")
        monkeypatch.setattr(
            sim_mod,
            "_get_owned_simulation",
            lambda simulation_id, user_id, db, sim=sim: sim,
        )
        with pytest.raises(HTTPException) as exc:
            sim_mod.get_calibration_transparency(
                simulation_id=1,
                corrections_limit=10,
                db=_FakeDB([]),
                current_user=SimpleNamespace(id=42),
            )
        assert exc.value.status_code == expected


def test_route_rejects_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation(results={})
    monkeypatch.setattr(
        sim_mod,
        "_get_owned_simulation",
        lambda simulation_id, user_id, db: sim,
    )

    with pytest.raises(HTTPException) as exc:
        sim_mod.get_calibration_transparency(
            simulation_id=1,
            corrections_limit=10,
            db=_FakeDB([]),
            current_user=SimpleNamespace(id=42),
        )
    assert exc.value.status_code == 422


def test_route_tolerates_malformed_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation(
        results={
            "product_type_detected": "saas",
            "conductor_diagnostics": ["not-a-dict"],
        }
    )
    monkeypatch.setattr(
        sim_mod,
        "_get_owned_simulation",
        lambda simulation_id, user_id, db: sim,
    )

    out = sim_mod.get_calibration_transparency(
        simulation_id=1,
        corrections_limit=10,
        db=_FakeDB([_row(cluster_id="ALL", scalar=0.9)]),
        current_user=SimpleNamespace(id=42),
    )

    assert out.recorded_applied_corrections is None
    assert out.corrected_pairs > 0


def test_route_coerces_recorded_applied_corrections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import simulations as sim_mod

    for recorded, expected in (
        (3.0, 3),
        ("3", 3),
        (-2, None),
        (2.5, None),
    ):
        sim = _FakeSimulation(
            results={
                "product_type_detected": "saas",
                "conductor_diagnostics": {"applied_corrections": recorded},
            }
        )
        monkeypatch.setattr(
            sim_mod,
            "_get_owned_simulation",
            lambda simulation_id, user_id, db, sim=sim: sim,
        )

        out = sim_mod.get_calibration_transparency(
            simulation_id=1,
            corrections_limit=10,
            db=_FakeDB([_row(cluster_id="ALL", scalar=0.9)]),
            current_user=SimpleNamespace(id=42),
        )

        assert out.recorded_applied_corrections == expected


def test_route_is_registered_and_uses_response_model() -> None:
    source = Path("backend/app/api/v1/simulations.py").read_text(
        encoding="utf-8"
    )
    assert '"/{simulation_id}/calibration-transparency"' in source
    assert "def get_calibration_transparency(" in source
    assert "response_model=CalibrationTransparencyOut" in source
    assert "build_calibration_transparency(" in source
