"""Tests for the per-user decision-rate helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import decision_rate
    assert set(decision_rate.__all__) == {
        "HIGH_MIN", "NORMAL_MIN",
        "SIGNAL_OK", "SIGNAL_WATCH", "SIGNAL_CRITICAL",
        "build_decision_rate",
    }


def test_default_zero_state():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate()
    assert out["sim_count"] == 0
    assert out["decision_count"] == 0
    assert out["rate_per_sim"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_high_verdict_when_above_1_per_sim():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=2, decision_count=3)
    assert out["rate_per_sim"] == 1.5
    assert out["verdict"] == "HIGH"


def test_normal_verdict_when_above_half_per_sim():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=4, decision_count=2)
    assert out["rate_per_sim"] == 0.5
    assert out["verdict"] == "NORMAL"


def test_low_verdict_when_below_half_per_sim():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=10, decision_count=2)
    assert out["rate_per_sim"] == 0.2
    assert out["verdict"] == "LOW"


def test_rounds_to_2_decimals():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=3, decision_count=1)
    # 1/3 = 0.3333... -> 0.33
    assert out["rate_per_sim"] == 0.33


def test_no_division_by_zero():
    """When sim_count=0, rate_per_sim must be None
    (no division)."""
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=0, decision_count=5)
    assert out["rate_per_sim"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_narrative_mentions_verdict():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=2, decision_count=4)
    assert "high" in out["narrative"].lower()


def test_narrative_no_projects_message():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate()
    assert "no completed simulations" in out["narrative"].lower()


def test_narrative_low_message():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=10, decision_count=2)
    assert "low" in out["narrative"].lower()


def test_narrative_normal_message():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=4, decision_count=2)
    assert "normal" in out["narrative"].lower()


def test_key_signal_present_when_data_exists():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate(sim_count=2, decision_count=3)
    assert out["key_signals"][0]["label"] == "rate_per_sim"


def test_no_key_signal_when_no_data():
    from app.simulation.decision_rate import build_decision_rate
    out = build_decision_rate()
    assert out["key_signals"] == []


def test_schema_default_shape():
    from app.schemas.user import DecisionRateOut
    out = DecisionRateOut()
    assert out.sim_count == 0
    assert out.decision_count == 0
    assert out.rate_per_sim is None
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.key_signals == []


def test_schema_round_trip():
    from app.schemas.user import DecisionRateOut
    from app.simulation.decision_rate import build_decision_rate
    payload = build_decision_rate(
        sim_count=4,
        decision_count=2,
    )
    out = DecisionRateOut(**payload)
    assert out.sim_count == 4
    assert out.decision_count == 2
    assert out.rate_per_sim == 0.5
    assert out.verdict == "NORMAL"
