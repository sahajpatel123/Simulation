"""Tests for the refresh-token retention purge (app.tasks.maintenance_tasks).

The pure cutoff math and the task's DB contract are covered here; the SQL
itself is smoke-pinned by asserting its shape, following the same
mock-the-Session pattern as the auth route tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.tasks.maintenance_tasks import (
    REFRESH_TOKEN_RETENTION_DAYS,
    purge_cutoff,
    purge_stale_refresh_tokens,
)


def test_purge_cutoff_subtracts_retention_window() -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    assert purge_cutoff(now) == now - timedelta(days=90)


def test_retention_window_is_bounded() -> None:
    """Long enough for reuse-detection forensics, short enough that the
    table tracks live sessions rather than all-time history."""
    assert 7 <= REFRESH_TOKEN_RETENTION_DAYS <= 365


def test_purge_cutoff_coerces_naive_to_utc() -> None:
    cutoff = purge_cutoff(datetime(2026, 8, 25, 12, 0))
    assert cutoff.tzinfo is not None


def _db_session(rowcount: int = 0) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    session.execute.return_value = result
    return session


def test_purge_task_deletes_and_reports_rowcount() -> None:
    session = _db_session(rowcount=7)

    with patch("app.tasks.maintenance_tasks.SessionLocal", return_value=session):
        out = purge_stale_refresh_tokens()

    assert out == {"deleted": 7}
    sql = session.execute.call_args.args[0].text
    assert "DELETE FROM refresh_tokens" in sql
    # All three stale shapes are covered; live tokens match none of them.
    assert "revoked_at IS NOT NULL" in sql  # modern revoked rows
    assert "revoked_at IS NULL" in sql  # legacy rows pre-revoked_at column
    assert "revoked = FALSE AND expires_at <" in sql  # expired-unused rows
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_purge_task_rolls_back_and_reraises_on_failure() -> None:
    session = MagicMock()
    session.execute.side_effect = RuntimeError("db gone")

    with patch("app.tasks.maintenance_tasks.SessionLocal", return_value=session):
        with pytest.raises(RuntimeError, match="db gone"):
            purge_stale_refresh_tokens()

    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    session.close.assert_called_once()


def test_purge_task_is_registered_with_beat() -> None:
    """The sweep only runs if Celery knows the module and beat entry — pin
    both so the schedule cannot silently detach from the task."""
    from app.core.celery_app import celery_app

    assert "app.tasks.maintenance_tasks" in celery_app.conf.include

    entries = [
        entry["task"] for entry in celery_app.conf.beat_schedule.values() if isinstance(entry, dict)
    ]
    assert "maintenance.purge_stale_refresh_tokens" in entries
