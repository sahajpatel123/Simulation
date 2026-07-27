"""Tests for the per-project premortem digest helper.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations

import pytest


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import premortem_digest

    assert set(premortem_digest.__all__) == {
        "MAX_TOP",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_premortem_digest",
    }


def test_digest_none_returns_zero_state() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest(None)
    assert out["premortem_count"] == 0
    assert out["top_failure_modes"] == []


def test_digest_empty_modes_returns_zero_state() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest({"failure_modes": []})
    assert out["premortem_count"] == 0


def test_digest_severity_breakdown() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest({
        "failure_modes": [
            {"title": "a", "severity": "CRITICAL", "impact": 9,
             "probability": 0.5, "description": "..."},
            {"title": "b", "severity": "HIGH", "impact": 7,
             "probability": 0.3, "description": "..."},
            {"title": "c", "severity": "CRITICAL", "impact": 8,
             "probability": 0.2, "description": "..."},
        ],
    })
    assert out["severity_breakdown"] == {
        "CRITICAL": 2,
        "HIGH": 1,
    }


def test_digest_top_failure_modes_sorted_by_impact() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest({
        "failure_modes": [
            {"title": "low", "severity": "MEDIUM", "impact": 1,
             "probability": 0.1},
            {"title": "high", "severity": "CRITICAL",
             "impact": 9, "probability": 0.5},
            {"title": "mid", "severity": "HIGH", "impact": 5,
             "probability": 0.3},
        ],
    })
    assert [m["title"] for m in out["top_failure_modes"]] == [
        "high", "mid", "low",
    ]


def test_digest_top_failure_modes_capped() -> None:
    from app.simulation.premortem_digest import (
        MAX_TOP,
        build_premortem_digest,
    )

    out = build_premortem_digest({
        "failure_modes": [
            {
                "title": f"m{i}", "severity": "MEDIUM",
                "impact": 1.0 + i, "probability": 0.1,
            }
            for i in range(20)
        ],
    })
    assert len(out["top_failure_modes"]) == MAX_TOP


def test_digest_narrative_mentions_most_fatal() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest({
        "failure_modes": [
            {"title": "Founder burns out",
             "severity": "CRITICAL", "impact": 9,
             "probability": 0.7, "description": "..."},
        ],
    })
    assert "Founder burns out" in out["narrative"]


def test_digest_handles_alternate_keys() -> None:
    """Some premortem generators use 'modes' or
    'findings' instead of 'failure_modes'."""
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest({
        "modes": [
            {"title": "x", "severity": "CRITICAL", "impact": 5,
             "probability": 0.5},
        ],
    })
    assert out["premortem_count"] == 1


def test_digest_handles_non_dict_entries() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest({
        "failure_modes": [
            "not-a-dict",
            None,
            {"title": "x", "severity": "MEDIUM",
             "impact": 5, "probability": 0.1},
        ],
    })
    assert out["premortem_count"] == 1


def test_digest_no_key_signals_when_zero() -> None:
    from app.simulation.premortem_digest import build_premortem_digest

    out = build_premortem_digest(None)
    labels = {s["label"] for s in out["key_signals"]}
    assert "premortem_count" in labels


def test_digest_key_signal_critical_severity() -> None:
    from app.simulation.premortem_digest import (
        SIGNAL_CRITICAL,
        build_premortem_digest,
    )

    out = build_premortem_digest({
        "failure_modes": [
            {"title": "a", "severity": "CRITICAL", "impact": 9,
             "probability": 0.5}
            for _ in range(3)
        ],
    })
    sig = next(
        s for s in out["key_signals"]
        if s["label"] == "premortem_count"
    )
    assert sig["severity"] == SIGNAL_CRITICAL


def test_digest_schema_round_trip() -> None:
    from app.schemas.project import PremortemDigestOut
    from app.simulation.premortem_digest import build_premortem_digest

    payload = build_premortem_digest({
        "failure_modes": [
            {"title": "x", "severity": "CRITICAL",
             "impact": 5, "probability": 0.5},
        ],
    })
    out = PremortemDigestOut(**payload)
    assert out.premortem_count == 1
    assert out.severity_breakdown["CRITICAL"] == 1