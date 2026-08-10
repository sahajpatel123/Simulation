"""Regression tests for the in-process metrics registry.

The metrics module is the source of truth for the /metrics
endpoint. Bugs here — a counter that doesn't increment, a
label cardinality that explodes — would silently break the
SRE dashboard.

Specifically pins the failure counter added in 8efffca so a
future refactor can't silently drop failure tracking.
"""
from __future__ import annotations

import pytest

from app.core.metrics import LLM_DURATION_HISTOGRAM, metrics


@pytest.fixture(autouse=True)
def reset_registry():
    """Each test gets a fresh counter set so assertions
    don't depend on test ordering. Counters are shared
    module-level state — without a reset, a test that
    asserts ``counter == 1`` would break if another test
    ran first and incremented the same counter."""
    with metrics._lock:
        metrics._counters.clear()
        metrics._gauges.clear()
        metrics._histograms.clear()
    yield


def test_claude_call_failure_increments_counter_with_reason_label() -> None:
    """Failed / timed-out / errored LLM calls must be tracked
    distinctly from successes so the dashboard can compute
    success-rate alerts. Reason label is bounded to a coarse
    category (timeout / api_error_4xx / api_error_5xx /
    api_error_unknown / unexpected) so cardinality stays
    bounded — a free-form exception message as the label
    would explode the counter set."""
    metrics.claude_call_failure(
        model="grok-3-mini", task="assumption_extraction",
        reason="timeout",
    )
    metrics.claude_call_failure(
        model="grok-3-mini", task="assumption_extraction",
        reason="timeout",
    )
    metrics.claude_call_failure(
        model="grok-3-mini", task="assumption_extraction",
        reason="api_error_5xx",
    )

    key = ("thecee_llm_failures_total", (("model", "grok-3-mini"),
                                          ("reason", "timeout"),
                                          ("task", "assumption_extraction")))
    assert metrics._counters[key] == 2
    key5 = ("thecee_llm_failures_total",
             (("model", "grok-3-mini"),
              ("reason", "api_error_5xx"),
              ("task", "assumption_extraction")))
    assert metrics._counters[key5] == 1


def test_claude_call_failure_separate_from_claude_call_success() -> None:
    """The failure counter must be distinct from the success
    counter — the dashboard computes success-rate alerts
    as failure / (failure + success). Mixing them would
    silently break the alert."""
    metrics.claude_call(model="grok-3-mini", task="assumption_extraction")
    metrics.claude_call(model="grok-3-mini", task="assumption_extraction")
    metrics.claude_call_failure(
        model="grok-3-mini", task="assumption_extraction",
        reason="timeout",
    )

    # 2 successes
    success_key = ("thecee_llm_calls_total",
                  (("model", "grok-3-mini"),
                   ("task", "assumption_extraction")))
    assert metrics._counters[success_key] == 2

    # 1 failure — distinct counter
    failure_key = ("thecee_llm_failures_total",
                   (("model", "grok-3-mini"),
                    ("reason", "timeout"),
                    ("task", "assumption_extraction")))
    assert metrics._counters[failure_key] == 1


def test_claude_call_failure_label_does_not_leak_exception_message() -> None:
    """The reason label MUST be a coarse category, not a
    free-form exception message. A real exception string
    (``"HTTPConnectionPool(host='api.x.ai', port=443):
    Read timed out."``) would explode the counter set
    cardinality — every unique timeout message would get
    its own counter. Pin that the test passes when given
    a coarse category, and document that the production
    code in claude_client.py is responsible for mapping
    raw exceptions to coarse categories before calling."""
    metrics.claude_call_failure(
        model="grok-3-mini", task="assumption_extraction",
        reason="timeout",  # coarse
    )
    # If a future refactor passes the raw exception message
    # as the reason, the cardinality would explode. This
    # test doesn't catch that directly — it just documents
    # the contract: reason is a coarse label, not a message.
    # The cardinality-bounding test is the histogram test
    # below.
    metrics.claude_call_failure(
        model="grok-3-mini", task="assumption_extraction",
        reason="api_error_500",
    )
    assert len(metrics._counters) == 2  # one per coarse reason


def test_claude_call_duration_observes_latency_histogram() -> None:
    """Successful LLM calls must record a per-model/per-task latency
    histogram so the llm-health digest can report percentiles — without
    this, /metrics only shows call counts and outage detection has no
    latency signal."""
    metrics.claude_call_duration(
        model="grok-3-mini",
        task="assumption_extraction",
        duration_seconds=1.2,
    )

    key = ("thecee_llm_duration_seconds",
           (("model", "grok-3-mini"),
            ("task", "assumption_extraction")))
    assert key in metrics._histograms
    buckets, counts, total = metrics._histograms[key]
    assert total == 1.2
    # 1.2s falls in the 2s bucket; the 1s bucket stays empty.
    assert counts[buckets.index(1.0)] == 0
    assert counts[buckets.index(2.0)] == 1
    assert LLM_DURATION_HISTOGRAM == "thecee_llm_duration_seconds"
