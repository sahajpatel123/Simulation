"""Engine-level SQL query observability for the app engine.

The HTTP layer already records request counts and latency histograms
(``app.core.metrics`` + ``app.core.timing_middleware``), but the SQL
behind a slow endpoint was invisible: the only previous DB observability
was ``app.core.db_query_logger.QueryCounter``, a manual context manager
callers had to remember to use. This module closes that gap by attaching
SQLAlchemy event listeners to the shared engine once per process:

* every non-transactional statement is bucketed by kind
  (SELECT / INSERT / UPDATE / DELETE / OTHER) into a Prometheus-style
  counter and latency histogram;
* statements that exceed the slow threshold also bump a slow-query
  counter and land in a bounded, in-process ring of the slowest
  statements (never the bound parameters, so secrets cannot leak);
* ``handle_error`` counts failed executions per kind and clears any
  pending timing entry so failed statements do not leak memory.
  Transaction / session-control failures (BEGIN, COMMIT, ROLLBACK,
  SAVEPOINT, RELEASE, SET) are deliberately excluded from the query
  error counter — those statements never appear in ``QUERY_COUNTER``, so
  counting their failures there would inflate the digest's error rate
  (one failed COMMIT could turn a healthy process into a false
  DEGRADED verdict). They land in their own ``thecee_db_control_errors_total``
  counter so ops still see connection / commit failures on ``/metrics``.

The digest built on top (``app.core.query_health.build_query_health``)
is process-local, matching the existing request-health observability:
multi-worker deployments scrape each replica individually.

Transaction-control statements (BEGIN / COMMIT / ROLLBACK / SAVEPOINT /
RELEASE / SET) are intentionally skipped so the query count reflects
real work instead of connection-pool chatter.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.metrics import metrics

QUERY_COUNTER: str = "thecee_db_queries_total"
QUERY_ERROR_COUNTER: str = "thecee_db_query_errors_total"
CONTROL_ERROR_COUNTER: str = "thecee_db_control_errors_total"
SLOW_QUERY_COUNTER: str = "thecee_db_slow_queries_total"
QUERY_DURATION_HISTOGRAM: str = "thecee_db_query_duration_seconds"

KIND_SELECT: str = "SELECT"
KIND_INSERT: str = "INSERT"
KIND_UPDATE: str = "UPDATE"
KIND_DELETE: str = "DELETE"
KIND_OTHER: str = "OTHER"

# Statements that merely manage the transaction / session. Counting them
# would inflate the query total with pool chatter (one BEGIN per request).
_TRANSACTION_CONTROL: frozenset[str] = frozenset(
    {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "SET"}
)

# Read-shaped first keywords beyond the literal SELECT.
_SELECT_STARTS: frozenset[str] = frozenset(
    {"SELECT", "WITH", "VALUES", "SHOW", "EXPLAIN", "PRAGMA", "DESCRIBE"}
)

SLOW_QUERY_THRESHOLD_MS: float = 250.0
DEFAULT_SLOW_QUERY_LIMIT: int = 25
MAX_STATEMENT_CHARS: int = 800

# Seconds buckets for the query-latency histogram. The first buckets cover
# fast ORM reads; the tail captures the multi-second aggregates that
# usually indicate a missing index or a scan.
QUERY_DURATION_BUCKETS_SECONDS: tuple[float, ...] = (
    0.0005,
    0.001,
    0.002,
    0.005,
    0.01,
    0.02,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
)

_COMMENT_PREFIX_RE = re.compile(r"^\s*(?:(?:--[^\n]*|/\*.*?\*/)\s*)*", re.S)

_installed_engines: set[int] = set()
_install_lock = threading.Lock()

_starts: dict[tuple[int, int], float] = {}
_starts_lock = threading.Lock()

_slow_entries: list[dict[str, Any]] = []
_slow_lock = threading.Lock()


def _first_keyword(statement: str) -> str:
    """Return the upper-cased first SQL keyword, ignoring leading comments."""
    cleaned = _COMMENT_PREFIX_RE.sub("", statement, count=1).strip().upper()
    return cleaned.split(None, 1)[0] if cleaned else ""


def classify_query_kind(statement: str | None) -> str | None:
    """Classify a statement into a bounded kind bucket, or ``None`` to skip.

    ``None`` is returned for transaction-control statements (BEGIN,
    COMMIT, ROLLBACK, SAVEPOINT, RELEASE, SET) and empty statements, which
    should not count as application queries.
    """
    if not statement or not statement.strip():
        return None
    first = _first_keyword(statement)
    if first in _TRANSACTION_CONTROL:
        return None
    if first in _SELECT_STARTS:
        return KIND_SELECT
    if first == "INSERT":
        return KIND_INSERT
    if first == "UPDATE":
        return KIND_UPDATE
    if first == "DELETE":
        return KIND_DELETE
    return KIND_OTHER


def normalise_statement(
    statement: str | None,
    *,
    max_chars: int = MAX_STATEMENT_CHARS,
) -> str:
    """Collapse whitespace and truncate a statement for the slow-query ring.

    Bound parameters are deliberately excluded by callers, so the stored
    text is the SQL template only.
    """
    if not statement:
        return ""
    text = " ".join(statement.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _add_slow_entry(entry: dict[str, Any], *, limit: int) -> None:
    """Insert one slow-query entry, keeping only the ``limit`` slowest."""
    with _slow_lock:
        _slow_entries.append(entry)
        _slow_entries.sort(key=lambda item: item["duration_ms"], reverse=True)
        del _slow_entries[limit:]


def _pop_start(conn: Any, cursor: Any) -> float | None:
    key = (id(conn), id(cursor))
    with _starts_lock:
        return _starts.pop(key, None)


def install_query_metrics(
    engine: Engine,
    *,
    threshold_ms: float = SLOW_QUERY_THRESHOLD_MS,
    max_entries: int = DEFAULT_SLOW_QUERY_LIMIT,
) -> bool:
    """Attach query observers to ``engine`` once (idempotent per engine).

    Returns ``True`` when listeners were installed, ``False`` when they
    were already installed for this engine. The slow-query ring keeps at
    most ``max_entries`` statements (slowest first) and the threshold is
    configurable so tests can force entries cheaply.
    """
    engine_id = id(engine)
    with _install_lock:
        if engine_id in _installed_engines:
            return False
        _installed_engines.add(engine_id)

    def _before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if classify_query_kind(statement) is None:
            return
        key = (id(conn), id(cursor))
        with _starts_lock:
            _starts[key] = time.perf_counter()

    def _after_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        kind = classify_query_kind(statement)
        started = _pop_start(conn, cursor)
        if kind is None or started is None:
            return
        duration_seconds = max(0.0, time.perf_counter() - started)
        duration_ms = duration_seconds * 1000.0
        metrics.inc_counter(QUERY_COUNTER, {"kind": kind})
        metrics.observe(
            QUERY_DURATION_HISTOGRAM,
            duration_seconds,
            labels={"kind": kind},
            buckets=QUERY_DURATION_BUCKETS_SECONDS,
        )
        if duration_ms >= threshold_ms:
            metrics.inc_counter(SLOW_QUERY_COUNTER, {"kind": kind})
            _add_slow_entry(
                {
                    "kind": kind,
                    "statement": normalise_statement(statement),
                    "duration_ms": round(duration_ms, 3),
                    "at": datetime.now(UTC).isoformat(),
                },
                limit=max_entries,
            )

    def _handle_error(context: Any) -> None:
        statement = getattr(context, "statement", None)
        kind = classify_query_kind(statement)
        if kind is not None:
            metrics.inc_counter(QUERY_ERROR_COUNTER, {"kind": kind})
        elif statement and statement.strip():
            # Transaction / session-control failures are visible but kept
            # out of the query error rate (see module docstring).
            metrics.inc_counter(CONTROL_ERROR_COUNTER)
        # after_cursor_execute never fires for a failed execution; clear the
        # pending start so failed statements cannot leak timing entries.
        cursor = getattr(context, "cursor", None)
        conn = getattr(context, "connection", None)
        if cursor is not None and conn is not None:
            _pop_start(conn, cursor)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(engine, "handle_error", _handle_error)
    return True


def slow_queries_snapshot(limit: int | None = None) -> list[dict[str, Any]]:
    """Return copies of the slowest observed statements, newest-slowest first.

    Entries are sorted by ``duration_ms`` descending. When ``limit`` is
    omitted the whole bounded ring is returned. Callers may mutate the
    returned dicts freely; the internal ring is not affected.
    """
    with _slow_lock:
        items = [dict(entry) for entry in _slow_entries]
    if limit is not None:
        items = items[:limit]
    return items


def clear_slow_queries() -> None:
    """Drop all captured slow-query entries (test / reset helper)."""
    with _slow_lock:
        _slow_entries.clear()


__all__ = [
    "CONTROL_ERROR_COUNTER",
    "DEFAULT_SLOW_QUERY_LIMIT",
    "KIND_DELETE",
    "KIND_INSERT",
    "KIND_OTHER",
    "KIND_SELECT",
    "KIND_UPDATE",
    "MAX_STATEMENT_CHARS",
    "QUERY_COUNTER",
    "QUERY_DURATION_BUCKETS_SECONDS",
    "QUERY_DURATION_HISTOGRAM",
    "QUERY_ERROR_COUNTER",
    "SLOW_QUERY_COUNTER",
    "SLOW_QUERY_THRESHOLD_MS",
    "classify_query_kind",
    "clear_slow_queries",
    "install_query_metrics",
    "normalise_statement",
    "slow_queries_snapshot",
]
