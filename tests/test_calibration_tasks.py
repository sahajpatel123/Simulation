"""Tests for backend/app/tasks/calibration_tasks.py.

These guard the contract of the two calibration Celery tasks:

  run_systematic_bias_update
    - On success: iterates over every ProductType, calls
      CalibrationEngine.update_systematic_bias for each, logs INFO,
      and closes the DB session in the finally block.
    - On exception: catches broadly, logs via logger.exception (so the
      traceback is preserved), and still closes the DB session.

  run_structural_pattern_update
    - Same shape, but a single CalibrationEngine.update_structural_patterns
      call per invocation.

Celery is NOT configured with task_always_eager in this project, so calling
the decorated task object would try to publish to the broker. We invoke the
underlying function via Task.run() to bypass that and exercise the body
directly. SessionLocal and CalibrationEngine are patched at the import site
inside the task module so no real DB or engine code runs.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from app.simulation.product_type import ProductType


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock(name="mock_db_session")


@pytest.fixture
def mock_engine() -> MagicMock:
    return MagicMock(name="mock_calibration_engine")


def _import_tasks() -> tuple[object, object]:
    """Import the task module fresh; must be inside test so DATABASE_URL is set."""
    from app.tasks import calibration_tasks

    return (
        calibration_tasks.run_systematic_bias_update,
        calibration_tasks.run_structural_pattern_update,
    )


def test_systematic_bias_update_happy_path(
    mock_session: MagicMock,
    mock_engine: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bias_task, _ = _import_tasks()

    with (
        patch(
            "app.tasks.calibration_tasks.SessionLocal", return_value=mock_session
        ) as session_factory,
        patch(
            "app.tasks.calibration_tasks.CalibrationEngine", return_value=mock_engine
        ) as engine_factory,
    ):
        with caplog.at_level(logging.INFO, logger="app.tasks.calibration_tasks"):
            bias_task.run()

    session_factory.assert_called_once_with()
    engine_factory.assert_called_once_with()
    assert mock_engine.update_systematic_bias.call_count == len(list(ProductType))
    for pt in ProductType:
        mock_engine.update_systematic_bias.assert_any_call(pt.value, mock_session)
    mock_session.close.assert_called_once()

    info_records = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "Systematic bias update complete" in r.getMessage()
    ]
    assert info_records, "expected an INFO log with 'Systematic bias update complete'"
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_systematic_bias_update_logs_exception_and_closes_db(
    mock_session: MagicMock,
    mock_engine: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bias_task, _ = _import_tasks()
    boom = RuntimeError("simulated engine failure")
    mock_engine.update_systematic_bias.side_effect = boom

    with (
        patch("app.tasks.calibration_tasks.SessionLocal", return_value=mock_session),
        patch(
            "app.tasks.calibration_tasks.CalibrationEngine", return_value=mock_engine
        ),
    ):
        with caplog.at_level(logging.ERROR, logger="app.tasks.calibration_tasks"):
            bias_task.run()

    error_records = [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR and "Bias update error" in r.getMessage()
    ]
    assert error_records, "expected an ERROR log containing 'Bias update error'"
    assert error_records[0].exc_info is not None, (
        "logger.exception must attach traceback info"
    )
    assert error_records[0].exc_info[0] is RuntimeError
    mock_session.close.assert_called_once()


def test_structural_pattern_update_happy_path(
    mock_session: MagicMock,
    mock_engine: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, pattern_task = _import_tasks()

    with (
        patch("app.tasks.calibration_tasks.SessionLocal", return_value=mock_session),
        patch(
            "app.tasks.calibration_tasks.CalibrationEngine", return_value=mock_engine
        ),
    ):
        with caplog.at_level(logging.INFO, logger="app.tasks.calibration_tasks"):
            pattern_task.run()

    mock_engine.update_structural_patterns.assert_called_once_with(mock_session)
    mock_session.close.assert_called_once()

    info_records = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and "Structural pattern update complete" in r.getMessage()
    ]
    assert info_records, "expected an INFO log with 'Structural pattern update complete'"
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_structural_pattern_update_logs_exception_and_closes_db(
    mock_session: MagicMock,
    mock_engine: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, pattern_task = _import_tasks()
    boom = ValueError("bad config payload")
    mock_engine.update_structural_patterns.side_effect = boom

    with (
        patch("app.tasks.calibration_tasks.SessionLocal", return_value=mock_session),
        patch(
            "app.tasks.calibration_tasks.CalibrationEngine", return_value=mock_engine
        ),
    ):
        with caplog.at_level(logging.ERROR, logger="app.tasks.calibration_tasks"):
            pattern_task.run()

    error_records = [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR and "Pattern update error" in r.getMessage()
    ]
    assert error_records, "expected an ERROR log containing 'Pattern update error'"
    assert error_records[0].exc_info is not None, (
        "logger.exception must attach traceback info"
    )
    assert error_records[0].exc_info[0] is ValueError
    mock_session.close.assert_called_once()


def test_logger_is_module_scoped() -> None:
    """Guard against accidentally wiring a global logger; the tasks must log
    under their own module path so per-module log filters keep working."""
    from app.tasks import calibration_tasks

    expected_name = "app.tasks.calibration_tasks"
    assert calibration_tasks.logger.name == expected_name
    assert isinstance(calibration_tasks.logger, logging.Logger)
