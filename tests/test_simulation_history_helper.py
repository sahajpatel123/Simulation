"""Pure-helper tests for the lightweight simulation-history payload."""
from __future__ import annotations

from datetime import datetime


def _row(
    sim_id: int,
    conversion_rate: float | None,
    *,
    status: str = "COMPLETED",
    signal_quality: float | None = 0.5,
    created_at: str | datetime = "2026-08-01T00:00:00",
) -> dict:
    return {
        "id": sim_id,
        "status": status,
        "signal_quality": signal_quality,
        "conversion_rate": conversion_rate,
        "created_at": created_at,
    }


def test_empty_rows_produce_empty_history() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history([], project_id=7)
    assert out == {
        "project_id": 7,
        "total_runs": 0,
        "history": [],
        "best_run_id": None,
    }


def test_history_deltas_and_directions_match_previous_run() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [
            _row(1, 0.04),
            _row(2, 0.06),
            _row(3, 0.05),
        ],
        project_id=7,
    )
    assert out["total_runs"] == 3
    history = out["history"]
    assert history[0]["delta_from_prev"] is None
    assert history[0]["direction"] is None
    assert history[1]["delta_from_prev"] == 0.02
    assert history[1]["direction"] == "UP"
    assert history[2]["delta_from_prev"] == -0.01
    assert history[2]["direction"] == "DOWN"


def test_flat_delta_is_tagged_flat() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [_row(1, 0.05), _row(2, 0.05)],
        project_id=7,
    )
    assert out["history"][1]["delta_from_prev"] == 0.0
    assert out["history"][1]["direction"] == "FLAT"


def test_best_run_id_uses_highest_conversion_rate() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [
            _row(10, 0.02),
            _row(11, 0.09),
            _row(12, 0.04),
        ],
        project_id=7,
    )
    assert out["best_run_id"] == 11


def test_missing_conversion_rate_falls_back_to_zero() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [_row(1, None), _row(2, 0.03)],
        project_id=7,
    )
    assert out["history"][0]["conversion_rate"] == 0.0
    assert out["history"][0]["direction"] is None
    assert out["history"][1]["delta_from_prev"] == 0.03
    assert out["best_run_id"] == 2


def test_numeric_string_conversion_rate_is_parsed() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [_row(1, "0.05")],
        project_id=7,
    )
    assert out["history"][0]["conversion_rate"] == 0.05


def test_non_numeric_conversion_rate_falls_back_to_zero() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [_row(1, "oops")],
        project_id=7,
    )
    assert out["history"][0]["conversion_rate"] == 0.0
    assert out["best_run_id"] == 1


def test_zero_conversion_rate_is_kept_as_primary_value() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [_row(1, 0.0), _row(2, 0.05)],
        project_id=7,
    )
    assert out["history"][0]["conversion_rate"] == 0.0
    assert out["history"][1]["delta_from_prev"] == 0.05
    assert out["best_run_id"] == 2


def test_missing_signal_quality_is_omitted_not_crashing() -> None:
    from app.simulation.simulation_history import build_simulation_history

    row = _row(1, 0.04)
    row.pop("signal_quality")
    out = build_simulation_history([row], project_id=7)
    assert out["history"][0]["signal_quality"] is None


def test_datetime_created_at_serialised_to_isoformat() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [_row(1, 0.04, created_at=datetime(2026, 8, 1, 12, 30))],
        project_id=7,
    )
    assert out["history"][0]["created_at"] == "2026-08-01T12:30:00"


def test_input_order_is_preserved() -> None:
    from app.simulation.simulation_history import build_simulation_history

    out = build_simulation_history(
        [
            _row(7, 0.07, created_at="2026-07-01T00:00:00"),
            _row(2, 0.02, created_at="2026-06-01T00:00:00"),
            _row(5, 0.05, created_at="2026-05-01T00:00:00"),
        ],
        project_id=7,
    )
    assert [h["simulation_id"] for h in out["history"]] == [7, 2, 5]


def test_helper_is_pure() -> None:
    import inspect

    from app.simulation import simulation_history

    source = inspect.getsource(simulation_history)
    forbidden = ("sqlalchemy", "SessionLocal", "get_db")
    for token in forbidden:
        assert token.lower() not in source.lower(), (
            f"simulation_history.py must not depend on {token}"
        )
