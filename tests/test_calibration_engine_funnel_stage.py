"""Tests for the CalibrationEngine Layer 6 stage-funnel update.

``update_funnel_stage_calibration`` reads validated founder outcomes with
per-stage actual drop-offs, pairs them with the drop-offs their simulations
predicted, and upserts one pass-through correction per (product type,
stage). These tests pin the query gates, product-type grouping, malformed
payload handling, single-commit batching, and the outcome-feedback
readiness gate.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.simulation.calibration_engine import CalibrationEngine
from app.simulation.funnel_stage_calibration import (
    MAX_OUTCOMES,
    MIN_SAMPLE_COUNT,
)


class _MappingsResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict]:
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    """Serves queued results and records every execute call."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []
        self.commits = 0

    def execute(self, statement: object, params: dict | None = None):
        self.calls.append((str(statement), params))
        value = self._responses.pop(0) if self._responses else []
        return _MappingsResult(value)

    def commit(self) -> None:
        self.commits += 1


def _results(product_type: str = "saas") -> dict:
    return {
        "product_type_detected": product_type,
        "stage_metrics": [
            {"state": "BROWSE", "drop_off_rate": 0.30},
            {"state": "CONSIDER", "drop_off_rate": 0.40},
            {"state": "DECIDE", "drop_off_rate": 0.50},
        ],
    }


def _outcome(
    *,
    browse: float | None = 0.10,
    consider: float | None = 0.40,
    decide: float | None = 0.50,
    weight: float = 2.0,
    product_type: str = "saas",
    results: dict | None = None,
) -> dict:
    return {
        "outcome_id": 1,
        "actual_drop_at_browse_pct": browse,
        "actual_drop_at_consider_pct": consider,
        "actual_drop_at_decide_pct": decide,
        "learning_weight": weight,
        "results_json": results if results is not None else _results(product_type),
    }


def test_no_rows_is_a_noop() -> None:
    db = _FakeDb([])
    CalibrationEngine().update_funnel_stage_calibration(db)
    assert db.calls and "LIMIT :limit" in db.calls[0][0]
    assert db.calls[0][1] == {"limit": MAX_OUTCOMES}
    assert db.commits == 0


def test_upserts_corrected_rows_and_commits_once() -> None:
    rows = [_outcome() for _ in range(MIN_SAMPLE_COUNT)]
    db = _FakeDb([rows])
    CalibrationEngine().update_funnel_stage_calibration(db)

    upserts = [
        (stmt, params)
        for stmt, params in db.calls
        if params is not None and "pt" in params
    ]
    assert len(upserts) == 3  # BROWSE + CONSIDER + DECIDE
    assert db.commits == 1

    by_stage = {params["stage"]: params for _, params in upserts}
    browse = by_stage["BROWSE"]
    assert browse["pt"] == "saas"
    assert browse["cluster_id"] == "ALL"
    assert browse["from_state"] == "BROWSE"
    assert browse["to_state"] == "CONSIDER"
    assert browse["scalar"] == round((1.0 - 0.10) / (1.0 - 0.30), 6)
    assert browse["scope"] == "FUNNEL_STAGE_GLOBAL"
    assert browse["sample_count"] == MIN_SAMPLE_COUNT
    assert browse["eff_count"] == round(MIN_SAMPLE_COUNT * 2.0, 4)
    assert 0.0 < browse["confidence"] <= 1.0

    # CONSIDER / DECIDE actual == predicted → neutral scalar.
    assert by_stage["CONSIDER"]["scalar"] == 1.0
    assert by_stage["DECIDE"]["scalar"] == 1.0


def test_groups_by_product_type() -> None:
    rows = [
        _outcome(product_type="saas"),
        _outcome(product_type="saas"),
        _outcome(product_type="saas"),
        _outcome(product_type="marketplace", browse=0.05),
        _outcome(product_type="marketplace", browse=0.05),
        _outcome(product_type="marketplace", browse=0.05),
    ]
    db = _FakeDb([rows])
    CalibrationEngine().update_funnel_stage_calibration(db)
    upserts = [
        params
        for stmt, params in db.calls
        if params is not None and "pt" in params
    ]
    product_types = {params["pt"] for params in upserts}
    assert product_types == {"saas", "marketplace"}
    assert sum(1 for p in upserts if p["pt"] == "saas") == 3
    assert sum(1 for p in upserts if p["pt"] == "marketplace") == 3
    assert db.commits == 1


def test_skips_malformed_results_payloads() -> None:
    rows = [
        _outcome(results="not-json{{{"),
        _outcome(results=None),
        _outcome(results="{}"),
        _outcome(),
        _outcome(),
        _outcome(),
    ]
    db = _FakeDb([rows])
    CalibrationEngine().update_funnel_stage_calibration(db)
    upserts = [
        params
        for stmt, params in db.calls
        if params is not None and "pt" in params
    ]
    # Only the three well-formed outcomes contribute.
    assert len(upserts) == 3
    assert db.commits == 1


def test_string_results_json_is_parsed() -> None:
    rows = [
        _outcome(results=json.dumps(_results(product_type="saas")))
        for _ in range(MIN_SAMPLE_COUNT)
    ]
    db = _FakeDb([rows])
    CalibrationEngine().update_funnel_stage_calibration(db)
    upserts = [
        params
        for stmt, params in db.calls
        if params is not None and "pt" in params
    ]
    assert len(upserts) == 3
    assert db.commits == 1


def test_ready_gate_reports_presence_of_stage_evidence() -> None:
    ready_db = _FakeDb([[SimpleNamespace(ready=3)]])
    assert CalibrationEngine().funnel_stage_calibration_ready(ready_db) is True

    empty_db = _FakeDb([[SimpleNamespace(ready=0)]])
    assert CalibrationEngine().funnel_stage_calibration_ready(empty_db) is False

    none_db = _FakeDb([[None]])
    assert CalibrationEngine().funnel_stage_calibration_ready(none_db) is False
