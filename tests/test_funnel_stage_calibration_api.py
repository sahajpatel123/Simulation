"""Route-level tests for the Layer 6 admin visibility endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


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


def _row() -> dict:
    return {
        "id": 7,
        "product_type": "saas",
        "stage": "BROWSE",
        "cluster_id": "ALL",
        "from_state": "BROWSE",
        "to_state": "CONSIDER",
        "correction_scalar": 1.25,
        "confidence_weight": 0.8,
        "effective_sample_count": 12.0,
        "sample_count": 4,
        "mean_bias": -0.05,
        "scope": "FUNNEL_STAGE_GLOBAL",
        "last_updated": None,
    }


def test_admin_endpoint_lists_corrections() -> None:
    from app.api.v1 import calibration as cal_mod

    with (
        patch.object(cal_mod, "_table_exists", return_value=True),
        patch.object(cal_mod, "_require_admin"),
    ):
        out = cal_mod.get_funnel_stage_corrections(
            db=_Db([_row()]),
            current_user=SimpleNamespace(id=1),
        )

    assert out.count == 1
    assert out.corrections[0].stage == "BROWSE"
    assert out.corrections[0].correction_scalar == 1.25
    assert out.corrections[0].to_state == "CONSIDER"
    assert out.corrections[0].scope == "FUNNEL_STAGE_GLOBAL"


def test_admin_endpoint_returns_empty_when_table_missing() -> None:
    from app.api.v1 import calibration as cal_mod

    with (
        patch.object(cal_mod, "_table_exists", return_value=False),
        patch.object(cal_mod, "_require_admin"),
    ):
        out = cal_mod.get_funnel_stage_corrections(
            db=_Db([]),
            current_user=SimpleNamespace(id=1),
        )

    assert out.count == 0
    assert out.corrections == []
