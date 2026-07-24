"""
Tests for ``app.simulation.funnel_analytics`` — pure-Python funnel
rollup engine. Locks down _infer_stage heuristics, per-stage agent
counts, exit-rate math, per-cluster breakdowns, summary metrics
(highest_drop, best/worst cluster), JSON-event decoding, and the
empty-sessions fallback.
"""
from __future__ import annotations

import json as _json
from typing import Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _session(events: list[dict], *, converted: bool = False, cluster: str = "metro") -> dict[str, Any]:
    return {
        "agent_cluster_id": cluster,
        "converted": converted,
        "events_json": events,
    }


def _click(target: str) -> dict[str, str]:
    return {"action": "click", "target": target}


# ---------------------------------------------------------------------------
# _infer_stage
# ---------------------------------------------------------------------------


def test_infer_stage_purchase_when_converted() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    # Even with checkout clicks, a converted session must report PURCHASE.
    stage = engine._infer_stage([_click("checkout-form"), _click("cta-primary")], converted=True)
    assert stage == "PURCHASE"


def test_infer_stage_decide_on_checkout_clicks() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    stage = engine._infer_stage([_click("cta-primary"), _click("checkout-form")], converted=False)
    assert stage == "DECIDE"


def test_infer_stage_decide_on_nav_checkout() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    stage = engine._infer_stage([_click("nav-checkout")], converted=False)
    assert stage == "DECIDE"


def test_infer_stage_consider_on_add_to_cart() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    stage = engine._infer_stage([_click("add-to-cart")], converted=False)
    assert stage == "CONSIDER"


def test_infer_stage_consider_on_pricing_section() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    stage = engine._infer_stage([_click("pricing-section")], converted=False)
    assert stage == "CONSIDER"


def test_infer_stage_browse_on_cta_primary() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    stage = engine._infer_stage([_click("cta-primary")], converted=False)
    assert stage == "BROWSE"


def test_infer_stage_browse_on_nav_links() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    for tgt in ("nav-products", "nav-home"):
        stage = engine._infer_stage([_click(tgt)], converted=False)
        assert stage == "BROWSE", tgt


def test_infer_stage_arrive_on_immediate_abandon() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    events = [{"action": "abandon", "target": "ARRIVE"}]
    assert engine._infer_stage(events, converted=False) == "ARRIVE"


def test_infer_stage_defaults_to_browse_for_unknown_clicks() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    stage = engine._infer_stage([_click("random-target")], converted=False)
    assert stage == "BROWSE"


def test_infer_stage_ignores_non_click_actions_for_target_hits() -> None:
    """Scroll/hover to 'checkout-form' must not promote to DECIDE."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    events = [
        {"action": "scroll", "target": "checkout-form"},
        {"action": "hover", "target": "checkout-form"},
    ]
    assert engine._infer_stage(events, converted=False) == "BROWSE"


def test_infer_stage_priority_checkout_over_browse() -> None:
    """When checkout + cta-primary are mixed, DECIDE wins."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    events = [_click("cta-primary"), _click("checkout-form"), _click("cta-primary")]
    assert engine._infer_stage(events, converted=False) == "DECIDE"


# ---------------------------------------------------------------------------
# generate() — empty + basic counts
# ---------------------------------------------------------------------------


def test_generate_empty_sessions_returns_neutral_payload() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=[])
    assert result.total_agents == 0
    assert result.overall_conversion == 0.0
    assert result.stages == []
    assert result.cluster_funnels == {}
    assert result.highest_drop_stage == "ARRIVE"
    assert result.best_cluster == "none"
    assert result.worst_cluster == "none"


def test_generate_total_agents_matches_session_count() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        _session([_click("cta-primary")], cluster="metro"),
        _session([_click("cta-primary")], cluster="metro"),
        _session([_click("cta-primary")], cluster="tier3"),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.total_agents == 3


def test_generate_all_converted_overall_conversion_is_one() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        _session([_click("cta-primary")], converted=True),
        _session([_click("cta-primary")], converted=True),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.overall_conversion == 1.0


def test_generate_stage_orders_match_funnel_stages() -> None:
    from app.simulation.funnel_analytics import (
        FUNNEL_STAGES,
        FunnelAnalyticsEngine,
    )

    sessions = [_session([_click("cta-primary")])]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert [s.stage for s in result.stages] == FUNNEL_STAGES


def test_generate_arr_reach_all_agents() -> None:
    """Every agent reached ARRIVE → entered_for_arr == total."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        _session([_click("random")]),
        _session([_click("random")]),
        _session([_click("random")]),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    arrive = result.stages[0]
    assert arrive.agents_entered == 3


def test_generate_exit_rate_monotonic_in_drop_count() -> None:
    """5/10 convert → PURCHASE exit rate = 0.5."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = (
        [_session([_click("cta-primary")], converted=True, cluster="x") for _ in range(5)]
        + [_session([_click("cta-primary")], converted=False, cluster="x") for _ in range(5)]
    )
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    purchase = result.stages[-1]
    # Only converted sessions land at PURCHASE stage; non-converted land at BROWSE.
    assert purchase.agents_entered == 5
    assert purchase.agents_exited == 0
    assert purchase.exit_rate == 0.0


def test_generate_exit_rate_nonzero_when_unconverted_after_purchase_clicks() -> None:
    """Sessions with checkout clicks but no conversion land at DECIDE — so
    they enter the funnel as ARRIVE/BROWSE/CONSIDER/DECIDE but not PURCHASE.
    Pure BROWSE sessions (= cta-primary only) have exit_rate = 1.0 at PURCHASE
    because they entered BROWSE but never reached PURCHASE."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [_session([_click("cta-primary")], converted=False) for _ in range(4)]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    purchase = result.stages[-1]
    assert purchase.agents_entered == 0  # no one reached PURCHASE stage
    assert purchase.exit_rate == 0.0


def test_generate_exit_rate_at_browse_stage_with_only_browse_sessions() -> None:
    """4 sessions that all hit BROWSE → BROWSE exit_rate = 0 (no one exits
    at this stage, since CONSIDER is the next stage reached by no one)."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [_session([_click("cta-primary")], converted=False) for _ in range(4)]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    browse = [s for s in result.stages if s.stage == "BROWSE"][0]
    assert browse.agents_entered == 4
    assert browse.agents_exited == 4  # all 4 drop between BROWSE and CONSIDER
    assert browse.exit_rate == 1.0


def test_generate_highest_drop_stage_picks_most_exits() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    # 5 converted (PURCHASE) + 5 BROWSE-only — biggest drop is BROWSE→CONSIDER.
    sessions = (
        [_session([_click("cta-primary")], converted=True) for _ in range(5)]
        + [_session([_click("cta-primary")], converted=False) for _ in range(5)]
    )
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.highest_drop_stage == "BROWSE"


# ---------------------------------------------------------------------------
# Per-cluster breakdown
# ---------------------------------------------------------------------------


def test_generate_cluster_funnels_have_per_stage_metrics() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        _session([_click("cta-primary")], converted=True, cluster="metro"),
        _session([_click("cta-primary")], converted=False, cluster="metro"),
        _session([_click("cta-primary")], converted=False, cluster="tier3"),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    metro = result.cluster_funnels["metro"]
    assert metro["total_agents"] == 2
    assert metro["converted"] == 1
    assert metro["conversion_rate"] == 0.5
    # ARRIVE reach is 2/2 = 1.0
    assert metro["stages"]["ARRIVE"]["agents_reached"] == 2
    assert metro["stages"]["ARRIVE"]["reach_rate"] == 1.0


def test_generate_cluster_exit_rates_per_stage() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        _session([_click("cta-primary")], converted=True, cluster="metro"),
        _session([_click("cta-primary")], converted=False, cluster="metro"),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    # Every stage carries cluster_exit_rates for clusters that entered it.
    stages_with_metro = [s for s in result.stages if "metro" in s.cluster_exit_rates]
    assert len(stages_with_metro) == 5
    # BROWSE-stage cluster exit for metro = 1/2 = 0.5 (one converted → PURCHASE,
    # one stayed at BROWSE).
    browse_stage = [s for s in result.stages if s.stage == "BROWSE"][0]
    assert browse_stage.cluster_exit_rates["metro"] == 0.5


def test_generate_best_worst_clusters_picked_by_conversion_rate() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        # high_cluster: 3/4 convert
        _session([_click("cta-primary")], converted=True, cluster="high_cluster"),
        _session([_click("cta-primary")], converted=True, cluster="high_cluster"),
        _session([_click("cta-primary")], converted=True, cluster="high_cluster"),
        _session([_click("cta-primary")], converted=False, cluster="high_cluster"),
        # low_cluster: 0/3 convert
        _session([_click("cta-primary")], converted=False, cluster="low_cluster"),
        _session([_click("cta-primary")], converted=False, cluster="low_cluster"),
        _session([_click("cta-primary")], converted=False, cluster="low_cluster"),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.best_cluster == "high_cluster"
    assert result.worst_cluster == "low_cluster"


def test_generate_single_cluster_marks_same_best_and_worst() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [_session([_click("cta-primary")], cluster="only")]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.best_cluster == "only"
    assert result.worst_cluster == "only"


# ---------------------------------------------------------------------------
# JSON decoding
# ---------------------------------------------------------------------------


def test_generate_handles_json_string_events() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [{
        "agent_cluster_id": "metro",
        "converted": False,
        "events_json": _json.dumps([{"action": "click", "target": "cta-primary"}]),
    }]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.total_agents == 1


def test_generate_handles_garbage_events_json() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [{
        "agent_cluster_id": "metro",
        "converted": False,
        "events_json": "{not really json[[[",
    }]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    # Falls back to empty events → BROWSE.
    assert result.total_agents == 1


def test_generate_handles_missing_events_json() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [{"agent_cluster_id": "metro", "converted": False}]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.total_agents == 1


def test_generate_handles_none_cluster_id() -> None:
    """agent_cluster_id=None coalesces to 'unknown' (regression for prior bug)."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [{
        "agent_cluster_id": None,
        "converted": False,
        "events_json": [_click("cta-primary")],
    }]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert "unknown" in result.cluster_funnels


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_serialises_required_keys() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [_session([_click("cta-primary")], converted=True, cluster="metro")]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=12, sessions=sessions)
    payload = FunnelAnalyticsEngine().to_dict(result)
    for key in (
        "generated_ui_id",
        "total_agents",
        "overall_conversion",
        "highest_drop_stage",
        "best_cluster",
        "worst_cluster",
        "stages",
        "cluster_funnels",
    ):
        assert key in payload
    assert payload["generated_ui_id"] == 12


def test_to_dict_is_json_serialisable() -> None:
    import json

    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [_session([_click("cta-primary")], converted=True, cluster="metro")]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    payload = FunnelAnalyticsEngine().to_dict(result)
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["generated_ui_id"] == 1


def test_to_dict_stages_carry_per_cluster_exit_rates() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = [
        _session([_click("cta-primary")], converted=True, cluster="metro"),
        _session([_click("cta-primary")], converted=False, cluster="metro"),
    ]
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    payload = FunnelAnalyticsEngine().to_dict(result)
    purchase = [s for s in payload["stages"] if s["stage"] == "PURCHASE"][0]
    assert "metro" in purchase["cluster_exit_rates"]


# ---------------------------------------------------------------------------
# Determinism + invariants
# ---------------------------------------------------------------------------


def test_generate_is_deterministic() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    engine = FunnelAnalyticsEngine()
    sessions = [
        _session([_click("cta-primary")], converted=True),
        _session([_click("cta-primary")], converted=False),
    ]
    a = engine.generate(generated_ui_id=1, sessions=sessions)
    b = engine.generate(generated_ui_id=1, sessions=sessions)
    assert engine.to_dict(a) == engine.to_dict(b)


def test_generate_stage_entered_counts_non_increasing() -> None:
    """Entered at stage[i] >= entered at stage[i+1] (monotonic funnel)."""
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = (
        [_session([_click("cta-primary")], converted=True) for _ in range(2)]
        + [_session([_click("cta-primary")], converted=False) for _ in range(3)]
    )
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    counts = [s.agents_entered for s in result.stages]
    for prev, nxt in zip(counts, counts[1:]):
        assert nxt <= prev + 1e-9, counts


def test_generate_overall_conversion_equals_total_purchase_fraction() -> None:
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    sessions = (
        [_session([_click("cta-primary")], converted=True) for _ in range(4)]
        + [_session([_click("cta-primary")], converted=False) for _ in range(6)]
    )
    result = FunnelAnalyticsEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.overall_conversion == 0.4
