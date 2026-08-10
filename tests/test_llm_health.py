"""Tests for the LLM call health digest endpoint.

The digest is a pure read over the metrics registry filled by
``app.core.claude_client``: successful calls land in
``thecee_llm_calls_total`` plus a latency histogram, failures land in the
distinct ``thecee_llm_failures_total`` counter. These tests pin the
attempt accounting (successes + failures, so a total outage reads as 100%
failure instead of a silent zero), per-model / per-task breakdowns,
histogram percentile math, failure-reason aggregation, verdict thresholds
and the route contract.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from openai import APIError, APITimeoutError

from app.core import claude_client
from app.core.llm_health import (
    LLM_CALLS_COUNTER,
    LLM_DURATION_HISTOGRAM,
    LLM_FAILURES_COUNTER,
    VERDICT_DEGRADED,
    VERDICT_HEALTHY,
    VERDICT_NO_DATA,
    VERDICT_WATCH,
    build_llm_health,
)
from app.core.metrics import metrics
from app.schemas.system_health import LLMHealthOut

# Importing ``app.api.v1.system_health`` pulls in the whole API router, which
# imports the billing router and the real ``razorpay`` SDK. On Python 3.12 the
# installed SDK fails on ``pkg_resources``; stub it the same way the other
# route tests do before any API-route import.
if "razorpay" not in sys.modules:
    _razorpay_stub = types.ModuleType("razorpay")
    _razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = _razorpay_stub

from app.api.v1 import system_health as system_health_module  # noqa: E402

MODEL: str = "grok-3-mini"
TASK: str = "assumption_extraction"
BUCKETS: list[float] = [0.5, 1.0, 2.0, 5.0]


@pytest.fixture(autouse=True)
def reset_registry():
    """Each test gets a fresh registry so assertions don't leak."""
    with metrics._lock:
        metrics._counters.clear()
        metrics._gauges.clear()
        metrics._histograms.clear()
    yield


def _counter_key(
    name: str,
    labels: dict[str, str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return (name, tuple(sorted(labels.items())))


def _histogram_key(
    name: str,
    labels: dict[str, str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return (name, tuple(sorted(labels.items())))


def _snapshot(
    counters: dict[tuple, float] | None = None,
    histograms: dict[tuple, tuple[list[float], list[int], float]] | None = None,
) -> dict[str, Any]:
    return {
        "counters": counters or {},
        "gauges": {},
        "histograms": histograms or {},
    }


def test_empty_snapshot_returns_zeroed_no_data_summary() -> None:
    payload = build_llm_health(_snapshot(), generated_at="now")

    assert payload["generated_at"] == "now"
    assert payload["total_attempts"] == 0
    assert payload["success_count"] == 0
    assert payload["failure_count"] == 0
    assert payload["success_rate"] is None
    assert payload["failure_rate"] is None
    assert payload["verdict"] == VERDICT_NO_DATA
    assert payload["models"] == []
    assert payload["tasks"] == []
    assert payload["failure_reasons"] == []
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_healthy_digest_aggregates_totals_percentiles_and_breakdowns() -> None:
    counters = {
        _counter_key(
            LLM_CALLS_COUNTER,
            {"model": MODEL, "task": TASK},
        ): 8.0,
        _counter_key(
            LLM_CALLS_COUNTER,
            {"model": MODEL, "task": "ui_generation"},
        ): 2.0,
    }
    histograms = {
        _histogram_key(
            LLM_DURATION_HISTOGRAM,
            {"model": MODEL, "task": TASK},
        ): (list(BUCKETS), [0, 8, 8, 8], 8.0),
        _histogram_key(
            LLM_DURATION_HISTOGRAM,
            {"model": MODEL, "task": "ui_generation"},
        ): (list(BUCKETS), [2, 2, 2, 2], 0.5),
    }
    payload = build_llm_health(
        _snapshot(counters=counters, histograms=histograms),
        generated_at="now",
    )

    assert payload["total_attempts"] == 10
    assert payload["success_count"] == 10
    assert payload["failure_count"] == 0
    assert payload["success_rate"] == 1.0
    assert payload["failure_rate"] == 0.0
    assert payload["mean_latency_ms"] == 850.0
    assert payload["p50_latency_ms"] == 687.5
    assert payload["p95_latency_ms"] == 968.75
    assert payload["p99_latency_ms"] == 993.75
    assert payload["verdict"] == VERDICT_HEALTHY

    assert [row["model"] for row in payload["models"]] == [MODEL]
    model_row = payload["models"][0]
    assert model_row["success_count"] == 10
    assert model_row["failure_count"] == 0
    assert model_row["attempt_count"] == 10
    assert model_row["mean_latency_ms"] == 850.0

    assert [row["task"] for row in payload["tasks"]] == [
        TASK,
        "ui_generation",
    ]
    assert payload["tasks"][0]["success_count"] == 8
    assert payload["tasks"][0]["p95_latency_ms"] == 975.0
    assert payload["tasks"][1]["mean_latency_ms"] == 250.0
    assert payload["failure_reasons"] == []
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_failure_rate_uses_attempts_and_drives_watch_verdict() -> None:
    counters = {
        _counter_key(
            LLM_CALLS_COUNTER,
            {"model": MODEL, "task": TASK},
        ): 100.0,
        _counter_key(
            LLM_FAILURES_COUNTER,
            {"model": MODEL, "task": TASK, "reason": "timeout"},
        ): 2.0,
    }
    payload = build_llm_health(_snapshot(counters=counters), generated_at="now")

    assert payload["total_attempts"] == 102
    assert payload["success_count"] == 100
    assert payload["failure_count"] == 2
    assert payload["failure_rate"] == pytest.approx(2 / 102, abs=1e-6)
    assert payload["success_rate"] == pytest.approx(100 / 102, abs=1e-6)
    assert payload["verdict"] == VERDICT_WATCH
    assert payload["failure_reasons"] == [
        {"reason": "timeout", "failure_count": 2}
    ]
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_high_failure_rate_is_degraded() -> None:
    counters = {
        _counter_key(
            LLM_CALLS_COUNTER,
            {"model": MODEL, "task": TASK},
        ): 100.0,
        _counter_key(
            LLM_FAILURES_COUNTER,
            {"model": MODEL, "task": TASK, "reason": "api_error_5xx"},
        ): 15.0,
    }
    payload = build_llm_health(_snapshot(counters=counters), generated_at="now")
    assert payload["verdict"] == VERDICT_DEGRADED
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_failures_without_successes_are_degraded_and_reasons_aggregate() -> None:
    counters = {
        _counter_key(
            LLM_FAILURES_COUNTER,
            {"model": MODEL, "task": TASK, "reason": "timeout"},
        ): 3.0,
        _counter_key(
            LLM_FAILURES_COUNTER,
            {"model": MODEL, "task": TASK, "reason": "api_error_5xx"},
        ): 1.0,
    }
    payload = build_llm_health(_snapshot(counters=counters), generated_at="now")

    assert payload["total_attempts"] == 4
    assert payload["success_count"] == 0
    assert payload["failure_count"] == 4
    assert payload["failure_rate"] == 1.0
    assert payload["success_rate"] == 0.0
    assert payload["verdict"] == VERDICT_DEGRADED
    assert payload["failure_reasons"] == [
        {"reason": "timeout", "failure_count": 3},
        {"reason": "api_error_5xx", "failure_count": 1},
    ]
    assert [row["model"] for row in payload["models"]] == [MODEL]
    assert payload["models"][0]["failure_rate"] == 1.0
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_latency_percentiles_drive_watch_and_degraded_verdicts() -> None:
    calls = {
        _counter_key(
            LLM_CALLS_COUNTER,
            {"model": MODEL, "task": TASK},
        ): 10.0,
    }
    watch_hist = {
        _histogram_key(
            LLM_DURATION_HISTOGRAM,
            {"model": MODEL, "task": TASK},
        ): ([0.5, 1.0, 2.0, 5.0, 10.0, 30.0], [0, 0, 0, 0, 10, 10], 100.0),
    }
    watch = build_llm_health(
        _snapshot(counters=calls, histograms=watch_hist),
        generated_at="now",
    )
    assert watch["verdict"] == VERDICT_WATCH
    assert watch["p95_latency_ms"] == 9750.0

    degraded_hist = {
        _histogram_key(
            LLM_DURATION_HISTOGRAM,
            {"model": MODEL, "task": TASK},
        ): ([0.5, 1.0, 2.0, 5.0, 10.0, 30.0], [0, 0, 0, 0, 0, 10], 250.0),
    }
    degraded = build_llm_health(
        _snapshot(counters=calls, histograms=degraded_hist),
        generated_at="now",
    )
    assert degraded["verdict"] == VERDICT_DEGRADED
    assert degraded["p95_latency_ms"] == 29000.0
    assert isinstance(LLMHealthOut(**degraded), LLMHealthOut)


def test_limit_caps_models_and_tasks() -> None:
    counters: dict[tuple, float] = {}
    for index in range(4):
        counters[
            _counter_key(
                LLM_CALLS_COUNTER,
                {"model": f"model-{index}", "task": f"task-{index}"},
            )
        ] = float(index + 1)
    payload = build_llm_health(
        _snapshot(counters=counters),
        limit=2,
        generated_at="now",
    )
    assert len(payload["models"]) == 2
    assert len(payload["tasks"]) == 2
    # Most attempted first: model-3 (4 calls), then model-2 (3 calls).
    assert [row["model"] for row in payload["models"]] == [
        "model-3",
        "model-2",
    ]
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_malformed_snapshot_entries_are_ignored() -> None:
    counters: dict[tuple, Any] = {
        _counter_key(
            LLM_CALLS_COUNTER,
            {"model": MODEL, "task": TASK},
        ): "not-a-number",
        _counter_key(
            LLM_FAILURES_COUNTER,
            {"model": MODEL, "task": TASK, "reason": "timeout"},
        ): -5.0,
    }
    histograms: dict[tuple, Any] = {
        _histogram_key(
            LLM_DURATION_HISTOGRAM,
            {"model": MODEL, "task": TASK},
        ): ([0.5, 1.0], [1], 0.5),
    }
    payload = build_llm_health(
        _snapshot(counters=counters, histograms=histograms),
        generated_at="now",
    )

    assert payload["total_attempts"] == 0
    assert payload["failure_count"] == 0
    assert payload["verdict"] == VERDICT_NO_DATA
    assert payload["mean_latency_ms"] is None
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


def test_route_returns_typed_summary_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _snapshot(
        counters={
            _counter_key(
                LLM_CALLS_COUNTER,
                {"model": MODEL, "task": TASK},
            ): 100.0,
            _counter_key(
                LLM_FAILURES_COUNTER,
                {"model": MODEL, "task": TASK, "reason": "timeout"},
            ): 2.0,
        },
        histograms={
            _histogram_key(
                LLM_DURATION_HISTOGRAM,
                {"model": MODEL, "task": TASK},
            ): (list(BUCKETS), [0, 100, 100, 100], 50.0),
        },
    )
    monkeypatch.setattr(metrics, "snapshot", lambda: fixture)

    payload = system_health_module.llm_health(limit=5)
    assert payload["total_attempts"] == 102
    assert payload["success_count"] == 100
    assert payload["failure_count"] == 2
    assert payload["verdict"] == VERDICT_WATCH
    assert payload["models"][0]["model"] == MODEL
    assert payload["failure_reasons"][0]["reason"] == "timeout"
    assert isinstance(LLMHealthOut(**payload), LLMHealthOut)


class _FakeMessage:
    content: str = "hello"


class _FakeChoices:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoices()]


class _FakeCompletions:
    def create(self, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse()


class _FakeChat:
    completions = _FakeCompletions()


class _FakeClient:
    chat = _FakeChat()


class _FakeTimeoutError(APITimeoutError):
    def __init__(self) -> None:
        super().__init__("request timed out")


class _FakeAPIError(APIError):
    def __init__(self, status_code: int | None) -> None:
        super().__init__("api boom", None, body=None)
        self.status_code = status_code


def test_claude_client_records_success_counter_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(claude_client, "_client", _FakeClient())

    result = claude_client.claude_call_with_fallback(
        messages=[{"role": "user", "content": "hi"}],
        model="grok-test-model",
        fallback_key="assumption_extraction",
    )

    assert result["content"] == "hello"
    assert result["error"] is None
    calls_key = _counter_key(
        LLM_CALLS_COUNTER,
        {"model": "grok-test-model", "task": "assumption_extraction"},
    )
    assert metrics._counters.get(calls_key, 0.0) == 1.0
    hist_key = _histogram_key(
        LLM_DURATION_HISTOGRAM,
        {"model": "grok-test-model", "task": "assumption_extraction"},
    )
    assert hist_key in metrics._histograms
    buckets, counts, total = metrics._histograms[hist_key]
    assert counts[buckets.index(1.0)] == 1
    assert total >= 0.0


def _failure_key(reason: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Registry key for the fake client's failure counter."""
    return _counter_key(
        LLM_FAILURES_COUNTER,
        {
            "model": "grok-test-model",
            "task": "assumption_extraction",
            "reason": reason,
        },
    )


def _assert_no_success_or_duration_recorded() -> None:
    """Failures must not inflate the success counter or latency histogram."""
    assert LLM_CALLS_COUNTER not in metrics._counters
    assert not any(name == LLM_DURATION_HISTOGRAM for name, _ in metrics._histograms)


def _monkeypatch_failing_client(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
) -> None:
    class _FailingCompletions:
        def create(self, **kwargs: Any) -> Any:
            raise exc

    class _FailingChat:
        completions = _FailingCompletions()

    class _FailingClient:
        chat = _FailingChat()

    monkeypatch.setattr(claude_client, "_client", _FailingClient())


def test_claude_client_records_timeout_failure_not_success_or_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _monkeypatch_failing_client(monkeypatch, _FakeTimeoutError())

    result = claude_client.claude_call_with_fallback(
        messages=[{"role": "user", "content": "hi"}],
        model="grok-test-model",
        fallback_key="assumption_extraction",
    )

    assert result["error"] == "LLM timeout — try again"
    assert metrics._counters[_failure_key("timeout")] == 1.0
    _assert_no_success_or_duration_recorded()


@pytest.mark.parametrize(
    ("status_code", "expected_reason", "expected_error"),
    [
        (429, "api_error_4xx", "API error 429: api boom"),
        (500, "api_error_5xx", "API error 500: api boom"),
        (None, "api_error_unknown", "api boom"),
    ],
)
def test_claude_client_maps_api_error_status_to_coarse_reason(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int | None,
    expected_reason: str,
    expected_error: str,
) -> None:
    _monkeypatch_failing_client(monkeypatch, _FakeAPIError(status_code))

    result = claude_client.claude_call_with_fallback(
        messages=[{"role": "user", "content": "hi"}],
        model="grok-test-model",
        fallback_key="assumption_extraction",
    )

    assert result["error"] == expected_error
    assert metrics._counters[_failure_key(expected_reason)] == 1.0
    _assert_no_success_or_duration_recorded()


def test_claude_client_records_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _monkeypatch_failing_client(monkeypatch, RuntimeError("boom"))

    result = claude_client.claude_call_with_fallback(
        messages=[{"role": "user", "content": "hi"}],
        model="grok-test-model",
        fallback_key="assumption_extraction",
    )

    assert result["error"] == "boom"
    assert metrics._counters[_failure_key("unexpected")] == 1.0
    _assert_no_success_or_duration_recorded()
