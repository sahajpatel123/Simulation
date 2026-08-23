"""Tests for the per-project confidence-explainer helper."""
from __future__ import annotations



def test_public_allowlist_matches_callers():
    from app.simulation import confidence_explainer
    assert set(confidence_explainer.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_confidence_explainer",
    }


def test_default_zero_state():
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    out = build_confidence_explainer()
    assert out["confidence_score"] == 0.0
    assert len(out["factors"]) == 5


def test_high_confidence_score_is_ok():
    from app.simulation.confidence_explainer import (
        SIGNAL_OK,
        build_confidence_explainer,
    )
    out = build_confidence_explainer(
        confidence_score=0.85,
        sample_volume=10000,
        agreement_rate=0.05,
        assumption_coverage=1.0,
        days_since_latest_assumption=3,
        outcome_history_depth=5,
    )
    assert out["confidence_score"] == 0.85
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_OK


def test_low_confidence_score_is_critical():
    from app.simulation.confidence_explainer import (
        SIGNAL_CRITICAL,
        build_confidence_explainer,
    )
    out = build_confidence_explainer(confidence_score=0.2)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_CRITICAL


def test_moderate_confidence_is_watch():
    from app.simulation.confidence_explainer import (
        SIGNAL_WATCH,
        build_confidence_explainer,
    )
    out = build_confidence_explainer(confidence_score=0.5)
    sig = out["key_signals"][0]
    assert sig["severity"] == SIGNAL_WATCH


def test_sample_volume_factor_buckets():
    """Sample volume buckets: <500 → 0.2, 500-999 → 0.4,
    1k-5k → 0.7, 5k+ → 1.0."""
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    cases = [
        (100, 0.2),
        (500, 0.4),
        (1000, 0.7),
        (5000, 1.0),
        (50000, 1.0),
    ]
    for vol, expected in cases:
        out = build_confidence_explainer(sample_volume=vol)
        sample = next(
            f for f in out["factors"]
            if f["label"] == "Sample volume"
        )
        assert sample["factor"] == expected, (
            f"vol {vol} expected {expected}, "
            f"got {sample['factor']}"
        )


def test_agreement_factor_bands():
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    cases = [
        (0.001, 0.3),  # way too low
        (0.005, 0.7),  # OK
        (0.05, 1.0),   # sweet spot
        (0.10, 1.0),   # upper sweet spot
        (0.20, 0.7),   # OK
        (0.30, 0.3),   # too high
        (None, 0.5),   # unknown
    ]
    for rate, expected in cases:
        out = build_confidence_explainer(agreement_rate=rate)
        agreement = next(
            f for f in out["factors"]
            if f["label"] == "Conversion agreement"
        )
        assert agreement["factor"] == expected, (
            f"rate {rate} expected {expected}, "
            f"got {agreement['factor']}"
        )


def test_freshness_factor_buckets():
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    cases = [
        (None, 0.0),
        (0, 1.0),
        (7, 1.0),
        (8, 0.7),
        (30, 0.7),
        (31, 0.4),
        (60, 0.4),
        (61, 0.2),
        (365, 0.2),
    ]
    for days, expected in cases:
        out = build_confidence_explainer(
            days_since_latest_assumption=days,
        )
        fresh = next(
            f for f in out["factors"]
            if f["label"] == "Assumption freshness"
        )
        assert fresh["factor"] == expected, (
            f"days {days} expected {expected}, "
            f"got {fresh['factor']}"
        )


def test_history_factor_buckets():
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    cases = [(0, 0.3), (1, 0.7), (3, 1.0), (10, 1.0)]
    for n, expected in cases:
        out = build_confidence_explainer(
            outcome_history_depth=n,
        )
        hist = next(
            f for f in out["factors"]
            if f["label"] == "Outcome history depth"
        )
        assert hist["factor"] == expected


def test_narrative_high_confidence():
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    out = build_confidence_explainer(
        confidence_score=0.85,
        sample_volume=10000,
        agreement_rate=0.05,
        assumption_coverage=1.0,
        days_since_latest_assumption=3,
        outcome_history_depth=5,
    )
    assert "high" in out["narrative"].lower()


def test_narrative_low_confidence():
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    out = build_confidence_explainer(
        confidence_score=0.2,
        sample_volume=100,
        agreement_rate=0.001,
        days_since_latest_assumption=300,
    )
    n = out["narrative"].lower()
    assert "low" in n
    assert "weakest" in n


def test_schema_default_shape():
    from app.schemas.project import ConfidenceExplainerOut
    out = ConfidenceExplainerOut()
    assert out.confidence_score == 0.0
    assert out.factors == []
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.project import ConfidenceExplainerOut
    from app.simulation.confidence_explainer import (
        build_confidence_explainer,
    )
    payload = build_confidence_explainer(
        confidence_score=0.85,
        sample_volume=10000,
    )
    out = ConfidenceExplainerOut(**payload)
    assert out.confidence_score == 0.85
    assert len(out.factors) == 5
