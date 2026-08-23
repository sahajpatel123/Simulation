"""Tests for the per-user outcome-rate helper."""
from __future__ import annotations



def test_public_allowlist_matches_callers():
    from app.simulation import outcome_rate
    assert set(outcome_rate.__all__) == {
        "HIGH_MIN", "NORMAL_MIN",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_outcome_rate",
    }


def test_default_zero_state():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate()
    assert out["sim_count"] == 0
    assert out["outcome_count"] == 0
    assert out["rate_per_sim"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_high_verdict_when_above_half_per_sim():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=2, outcome_count=2)
    assert out["rate_per_sim"] == 1.0
    assert out["verdict"] == "HIGH"


def test_normal_verdict_when_above_quarter_per_sim():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=4, outcome_count=1)
    assert out["rate_per_sim"] == 0.25
    assert out["verdict"] == "NORMAL"


def test_low_verdict_when_below_quarter_per_sim():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=10, outcome_count=1)
    assert out["rate_per_sim"] == 0.1
    assert out["verdict"] == "LOW"


def test_rounds_to_2_decimals():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=3, outcome_count=1)
    # 1/3 = 0.3333... -> 0.33
    assert out["rate_per_sim"] == 0.33


def test_no_division_by_zero():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=0, outcome_count=3)
    assert out["rate_per_sim"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_narrative_mentions_verdict():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=2, outcome_count=4)
    assert "high" in out["narrative"].lower()


def test_narrative_no_projects_message():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate()
    assert "no completed simulations" in out["narrative"].lower()


def test_narrative_low_message():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=10, outcome_count=1)
    assert "low" in out["narrative"].lower()


def test_narrative_normal_message():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=4, outcome_count=1)
    assert "normal" in out["narrative"].lower()


def test_key_signal_present_when_data_exists():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate(sim_count=2, outcome_count=2)
    assert out["key_signals"][0]["label"] == "rate_per_sim"


def test_no_key_signal_when_no_data():
    from app.simulation.outcome_rate import build_outcome_rate
    out = build_outcome_rate()
    assert out["key_signals"] == []


def test_schema_default_shape():
    from app.schemas.user import OutcomeRateOut
    out = OutcomeRateOut()
    assert out.sim_count == 0
    assert out.outcome_count == 0
    assert out.rate_per_sim is None
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import OutcomeRateOut
    from app.simulation.outcome_rate import build_outcome_rate
    payload = build_outcome_rate(
        sim_count=4,
        outcome_count=1,
    )
    out = OutcomeRateOut(**payload)
    assert out.sim_count == 4
    assert out.outcome_count == 1
    assert out.rate_per_sim == 0.25
    assert out.verdict == "NORMAL"
