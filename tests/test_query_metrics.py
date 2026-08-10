"""Tests for the engine-level SQL query observability listener.

The listener attaches to a SQLAlchemy engine once per process and feeds
the in-process metrics registry (counters + latency histogram) plus a
bounded ring of the slowest statements. These tests pin statement
classification, idempotent installation, metric recording, slow-query
capture/trimming, error counting and the copy semantics of the snapshot.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, text

from app.core.metrics import metrics
from app.core.query_metrics import (
    KIND_DELETE,
    KIND_INSERT,
    KIND_OTHER,
    KIND_SELECT,
    KIND_UPDATE,
    QUERY_COUNTER,
    QUERY_DURATION_HISTOGRAM,
    QUERY_ERROR_COUNTER,
    SLOW_QUERY_COUNTER,
    classify_query_kind,
    clear_slow_queries,
    install_query_metrics,
    normalise_statement,
    slow_queries_snapshot,
)


@pytest.fixture(autouse=True)
def reset_observability_state() -> None:
    """Each test gets a fresh metrics registry and slow-query ring."""
    with metrics._lock:
        metrics._counters.clear()
        metrics._gauges.clear()
        metrics._histograms.clear()
    clear_slow_queries()
    yield
    clear_slow_queries()


def _counter_value(name: str, kind: str) -> float:
    key = (name, (("kind", kind),))
    return metrics._counters.get(key, 0.0)


def test_classify_query_kind_buckets_reads_writes_and_skips_transaction_noise() -> None:
    assert classify_query_kind("SELECT * FROM projects") == KIND_SELECT
    assert classify_query_kind("WITH x AS (SELECT 1) SELECT * FROM x") == KIND_SELECT
    assert classify_query_kind("SHOW search_path") == KIND_SELECT
    assert classify_query_kind("INSERT INTO projects (id) VALUES (1)") == KIND_INSERT
    assert classify_query_kind("UPDATE projects SET name = 'x'") == KIND_UPDATE
    assert classify_query_kind("DELETE FROM projects WHERE id = 1") == KIND_DELETE
    assert classify_query_kind("CREATE TABLE x (id int)") == KIND_OTHER
    assert classify_query_kind("/* explain */ SELECT 1") == KIND_SELECT
    assert classify_query_kind("BEGIN") is None
    assert classify_query_kind("COMMIT") is None
    assert classify_query_kind("ROLLBACK") is None
    assert classify_query_kind("SAVEPOINT s1") is None
    assert classify_query_kind("RELEASE SAVEPOINT s1") is None
    assert classify_query_kind("SET search_path = public") is None
    assert classify_query_kind("") is None
    assert classify_query_kind(None) is None


def test_normalise_statement_collapses_whitespace_and_truncates() -> None:
    assert normalise_statement("  SELECT  *\nFROM   projects ") == "SELECT * FROM projects"
    long_stmt = "SELECT " + ("a" * 2000)
    truncated = normalise_statement(long_stmt)
    assert len(truncated) <= 800
    assert truncated.endswith("…")
    assert normalise_statement(None) == ""


def test_install_records_counters_histogram_and_slow_entries() -> None:
    engine = create_engine("sqlite:///:memory:")
    assert install_query_metrics(engine) is True
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": "a"})
        conn.execute(text("SELECT * FROM t WHERE id = :id"), {"id": 1})
        conn.execute(text("UPDATE t SET name = :name WHERE id = :id"), {"name": "b", "id": 1})
        conn.execute(text("DELETE FROM t WHERE id = :id"), {"id": 1})

    assert _counter_value(QUERY_COUNTER, KIND_SELECT) == 1.0
    assert _counter_value(QUERY_COUNTER, KIND_INSERT) == 1.0
    assert _counter_value(QUERY_COUNTER, KIND_UPDATE) == 1.0
    assert _counter_value(QUERY_COUNTER, KIND_DELETE) == 1.0
    assert _counter_value(QUERY_COUNTER, KIND_OTHER) == 1.0  # CREATE TABLE

    snapshot = metrics.snapshot()
    histogram_key = (QUERY_DURATION_HISTOGRAM, (("kind", KIND_SELECT),))
    buckets, counts, total = snapshot["histograms"][histogram_key]
    assert counts[-1] == 1
    assert total > 0.0


def test_install_is_idempotent_per_engine() -> None:
    engine = create_engine("sqlite:///:memory:")
    assert install_query_metrics(engine) is True
    assert install_query_metrics(engine) is False
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
    assert _counter_value(QUERY_COUNTER, KIND_SELECT) == 1.0


def test_slow_ring_keeps_slowest_and_respects_bounded_limit() -> None:
    engine = create_engine("sqlite:///:memory:")
    install_query_metrics(engine, threshold_ms=0.0, max_entries=2)
    with engine.begin() as conn:
        for value in (10, 5, 1):
            conn.execute(text("SELECT :value"), {"value": value})

    entries = slow_queries_snapshot()
    assert len(entries) == 2
    assert entries[0]["duration_ms"] >= entries[1]["duration_ms"]
    assert all(entry["kind"] == KIND_SELECT for entry in entries)
    assert _counter_value(SLOW_QUERY_COUNTER, KIND_SELECT) == 3.0


def test_slow_ring_snapshot_returns_copies() -> None:
    engine = create_engine("sqlite:///:memory:")
    install_query_metrics(engine, threshold_ms=0.0, max_entries=5)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))

    first = slow_queries_snapshot()
    first[0]["statement"] = "mutated"
    second = slow_queries_snapshot()
    assert second[0]["statement"] != "mutated"


def test_failed_statements_count_errors_and_do_not_break_later_timing() -> None:
    engine = create_engine("sqlite:///:memory:")
    install_query_metrics(engine)
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text("SELECT * FROM missing_table"))

    assert _counter_value(QUERY_ERROR_COUNTER, KIND_SELECT) == 1.0
    # The failed statement must not have recorded a duration or a success.
    assert _counter_value(QUERY_COUNTER, KIND_SELECT) == 0.0

    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
    assert _counter_value(QUERY_COUNTER, KIND_SELECT) == 1.0


def test_snapshot_entries_include_only_safe_fields() -> None:
    engine = create_engine("sqlite:///:memory:")
    install_query_metrics(engine, threshold_ms=0.0)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
    entry: dict[str, Any] = slow_queries_snapshot()[0]
    assert set(entry) == {"kind", "statement", "duration_ms", "at"}
    assert entry["kind"] == KIND_SELECT
    assert entry["statement"] == "SELECT 1"
    assert entry["duration_ms"] >= 0.0
    assert entry["at"]
