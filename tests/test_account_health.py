"""Tests for the per-user account-health helper + schema +
route registration.

The helper is pure-Python so it can be exercised without
a DB.
"""
from __future__ import annotations



# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import account_health

    expected = {
        "MAX_SCORE",
        "CALIBRATION_SCORE_GOOD",
        "CALIBRATION_SCORE_OK",
        "CALIBRATION_SCORE_WATCH",
        "BLINDSPOTS_SCORE_CLEAN",
        "BLINDSPOTS_SCORE_FEW",
        "BLINDSPOTS_SCORE_THRESHOLD_FEW",
        "BLINDSPOTS_CRITICAL_THRESHOLD",
        "SIM_SUCCESS_SCORE_HIGH",
        "SIM_SUCCESS_SCORE_MID",
        "SIM_SUCCESS_SCORE_LOW",
        "SIM_SUCCESS_RATIO_HIGH",
        "SIM_SUCCESS_RATIO_MID",
        "SIM_SUCCESS_RATIO_LOW",
        "DECISION_SUCCESS_SCORE_HIGH",
        "DECISION_SUCCESS_SCORE_MID",
        "DECISION_SUCCESS_RATIO_HIGH",
        "DECISION_SUCCESS_RATIO_MID",
        "ACCOUNT_AGE_ESTABLISHED_DAYS",
        "ACCOUNT_AGE_SCORE_BONUS",
        "PENALTY_PER_FAILED_OUTCOME",
        "PENALTY_PER_CRITICAL_SIGNAL",
        "VERDICT_HEALTHY",
        "VERDICT_NEEDS_ATTENTION",
        "VERDICT_AT_RISK",
        "VERDICT_HEALTHY_MIN",
        "VERDICT_AT_RISK_MAX",
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_account_health",
    }
    assert set(account_health.__all__) == expected


# ---------------------------------------------------------------------------
# Default-empty input
# ---------------------------------------------------------------------------


def test_default_empty_at_risk() -> None:
    from app.simulation.account_health import (
        VERDICT_AT_RISK,
        build_account_health,
    )

    out = build_account_health()
    # Empty input → verdict AT_RISK (no data to evaluate)
    # but score is 25, NOT 0: the helper credits
    #   * 20 points for "clean blindspot history" (zero blindspots)
    #   * 5  points for "no MAE yet" (neutral watch state, not critical)
    # Empty accounts earn a baseline for having nothing
    # wrong, but stay well below VERDICT_AT_RISK_MAX (40)
    # so the verdict correctly stays AT_RISK.
    assert out["verdict"] == VERDICT_AT_RISK
    assert out["health_score"] == 25


# ---------------------------------------------------------------------------
# Calibration MAE bucket
# ---------------------------------------------------------------------------


def test_calibration_good_high_score() -> None:
    from app.simulation.account_health import build_account_health

    # MAE 0.01 → CALIBRATION_SCORE_GOOD (25)
    out = build_account_health(mae=0.01)
    assert out["score_breakdown"]["calibration"] == 25


def test_calibration_ok_mid_score() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(mae=0.03)
    assert out["score_breakdown"]["calibration"] == 15


def test_calibration_watch_low_score() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(mae=0.08)
    # 0.08 >= 0.05 → no points (critical bucket).
    assert out["score_breakdown"]["calibration"] == 0


def test_calibration_none_gives_watch_points() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(mae=None)
    assert out["score_breakdown"]["calibration"] == 5


# ---------------------------------------------------------------------------
# Blindspot bucket
# ---------------------------------------------------------------------------


def test_blindspots_clean_max_points() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(blindspot_count=0)
    assert out["score_breakdown"]["blindspots"] == 20


def test_blindspots_few_mid_points() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(blindspot_count=2)
    assert out["score_breakdown"]["blindspots"] == 10


def test_blindspots_critical_zero_points() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(blindspot_count=3)
    assert out["score_breakdown"]["blindspots"] == 0


# ---------------------------------------------------------------------------
# Sim success ratio
# ---------------------------------------------------------------------------


def test_sim_success_high_ratio() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        simulation_completed=8, simulation_total=10,
    )
    assert out["score_breakdown"]["sim_success"] == 15


def test_sim_success_mid_ratio() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        simulation_completed=6, simulation_total=10,
    )
    assert out["score_breakdown"]["sim_success"] == 10


def test_sim_success_low_ratio() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        simulation_completed=2, simulation_total=10,
    )
    assert out["score_breakdown"]["sim_success"] == 5


def test_sim_success_zero_total() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        simulation_completed=0, simulation_total=0,
    )
    assert out["score_breakdown"]["sim_success"] == 0


# ---------------------------------------------------------------------------
# Decision success ratio
# ---------------------------------------------------------------------------


def test_decision_success_high_ratio() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        decision_completed=8, decision_total=10,
    )
    assert out["score_breakdown"]["decision_success"] == 10


def test_decision_success_zero_total() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        decision_completed=0, decision_total=0,
    )
    assert out["score_breakdown"]["decision_success"] == 0


# ---------------------------------------------------------------------------
# Account age bonus
# ---------------------------------------------------------------------------


def test_account_age_bonus_when_established() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(account_age_days=120)
    assert out["score_breakdown"]["account_age"] == 5


def test_account_age_no_bonus_when_fresh() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(account_age_days=20)
    assert out["score_breakdown"]["account_age"] == 0


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------


def test_failed_outcomes_penalty() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(failed_outcome_count=3)
    # 3 failed * 2 = 6 off.
    assert out["score_breakdown"]["penalties"] == -6


def test_critical_signals_penalty() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(critical_signal_count=4)
    assert out["score_breakdown"]["penalties"] == -4


def test_combined_penalties() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        failed_outcome_count=2,
        critical_signal_count=3,
    )
    # 2*2 + 3*1 = 7.
    assert out["score_breakdown"]["penalties"] == -7


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------


def test_verdict_healthy_when_score_high() -> None:
    from app.simulation.account_health import (
        VERDICT_HEALTHY,
        build_account_health,
    )

    # Calibration good (25) + blindspots clean (20) + sims
    # high (15) + decisions high (10) + age bonus (5) = 75.
    out = build_account_health(
        mae=0.01,
        blindspot_count=0,
        simulation_completed=8, simulation_total=10,
        decision_completed=8, decision_total=10,
        account_age_days=120,
    )
    assert out["health_score"] == 75
    assert out["verdict"] == VERDICT_HEALTHY


def test_verdict_at_risk_when_score_low() -> None:
    from app.simulation.account_health import (
        VERDICT_AT_RISK,
        build_account_health,
    )

    out = build_account_health(
        mae=0.10,
        blindspot_count=10,
        simulation_completed=1, simulation_total=100,
        account_age_days=1,
    )
    assert out["health_score"] <= 40
    assert out["verdict"] == VERDICT_AT_RISK


def test_score_clamped_to_zero() -> None:
    """Penalties alone can drive the score negative in
    theory; the helper clamps at 0, never negative."""
    from app.simulation.account_health import build_account_health

    out = build_account_health(
        mae=0.10,
        blindspot_count=10,
        failed_outcome_count=200,
        critical_signal_count=200,
    )
    assert out["health_score"] == 0


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


def test_narrative_mentions_score() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(mae=0.01, blindspot_count=0)
    assert "/100" in out["narrative"]


def test_narrative_mentions_penalties_when_present() -> None:
    from app.simulation.account_health import build_account_health

    out = build_account_health(failed_outcome_count=2)
    assert "Penalties" in out["narrative"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_account_health_out_default_shape() -> None:
    from app.schemas.user import AccountHealthOut

    out = AccountHealthOut()
    assert out.health_score == 0
    # Schema default for an empty account — a brand-new
    # account is NEEDS_ATTENTION, not AT_RISK.
    assert out.verdict == "NEEDS_ATTENTION"
    assert out.key_signals == []


def test_account_health_out_round_trips_helper_payload() -> None:
    from app.schemas.user import AccountHealthOut
    from app.simulation.account_health import build_account_health

    payload = build_account_health(mae=0.01, blindspot_count=0)
    out = AccountHealthOut(**payload)
    assert out.health_score == 45
    assert out.score_breakdown["calibration"] == 25
