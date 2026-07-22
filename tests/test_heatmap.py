"""
Tests for ``app.simulation.heatmap`` — pure-Python click aggregation.

Locks down the click counting, conversion/abandon rate math, per-cluster
breakdowns, ranking choices (top_conversion / top_abandon), JSON-event
decoding, and edge cases (empty sessions, unknown clusters, mixed event
types, malformed event JSON).
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _click(target: str, cluster: str = "metro_power_professional", converted: bool = False) -> dict[str, Any]:
    return {
        "agent_cluster_id": cluster,
        "converted": converted,
        "events_json": [{"action": "click", "target": target}],
    }


def _mixed_events(target: str, cluster: str) -> list[dict[str, Any]]:
    return [{
        "agent_cluster_id": cluster,
        "converted": False,
        "events_json": [
            {"action": "click", "target": target},
            {"action": "scroll", "target": "page"},
            {"action": "hover", "target": target},
            {"action": "click", "target": target},  # second click on same target
        ],
    }]


# ---------------------------------------------------------------------------
# Click counting
# ---------------------------------------------------------------------------


def test_counts_clicks_per_target() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("cta_button", converted=False),
        _click("cta_button", converted=True),
        _click("pricing_link", converted=False),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    by_id = {p.thecee_id: p.click_count for p in result.heatmap_points}
    assert by_id["cta_button"] == 2
    assert by_id["pricing_link"] == 1


def test_total_clicks_sums_all_targets() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("a"),
        _click("a"),
        _click("b"),
        _click("c", converted=True),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.total_clicks == 4


def test_unique_elements_count_distinct_targets() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("a"),
        _click("a"),
        _click("b"),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.unique_elements == 2


def test_ignores_non_click_actions() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [{
        "agent_cluster_id": "metro_power_professional",
        "converted": False,
        "events_json": [
            {"action": "scroll", "target": "page"},
            {"action": "hover", "target": "x"},
            {"action": "input", "target": "form"},
        ],
    }]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.heatmap_points == []
    assert result.total_clicks == 0


# ---------------------------------------------------------------------------
# Conversion / abandon rates
# ---------------------------------------------------------------------------


def test_conversion_rate_matches_counts() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("btn", converted=True),
        _click("btn", converted=True),
        _click("btn", converted=False),
        _click("btn", converted=False),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    assert point.click_count == 4
    assert point.conversion_rate == 0.5
    assert point.abandon_rate == 0.5


def test_all_converted_rates_eq_one() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [_click("btn", converted=True) for _ in range(5)]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    assert point.conversion_rate == 1.0
    assert point.abandon_rate == 0.0


def test_all_abandoned_rates_eq_zero_conversion() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [_click("btn", converted=False) for _ in range(3)]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    assert point.conversion_rate == 0.0
    assert point.abandon_rate == 1.0


def test_rates_rounded_to_four_dp() -> None:
    from app.simulation.heatmap import HeatmapEngine

    # 7 clicks → 2/7 = 0.2857...
    sessions = (
        [_click("btn", converted=True), _click("btn", converted=True)]
        + [_click("btn", converted=False) for _ in range(5)]
    )
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    assert point.conversion_rate == round(2 / 7, 4)


# ---------------------------------------------------------------------------
# Sorting + ranking
# ---------------------------------------------------------------------------


def test_heatmap_points_sorted_by_click_count_descending() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [_click("a")] + [_click("b") for _ in range(3)] + [_click("c") for _ in range(2)]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    counts = [p.click_count for p in result.heatmap_points]
    assert counts == sorted(counts, reverse=True)


def test_top_conversion_element_picked_among_nonempty_points() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("low_btn", converted=False),
        _click("low_btn", converted=True),  # 50% conversion
        _click("high_btn", converted=True),
        _click("high_btn", converted=True),  # 100% conversion
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.top_conversion_element == "high_btn"


def test_top_abandon_element_picked_among_nonempty_points() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("low_btn", converted=True),
        _click("low_btn", converted=True),
        _click("high_btn", converted=False),
        _click("high_btn", converted=False),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.top_abandon_element == "high_btn"


# ---------------------------------------------------------------------------
# Cluster breakdown
# ---------------------------------------------------------------------------


def test_cluster_breakdown_sums_across_sessions() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("btn", cluster="metro_power_professional", converted=False),
        _click("btn", cluster="metro_power_professional", converted=True),
        _click("btn", cluster="tier3_first_time_app_user", converted=False),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    assert point.cluster_breakdown == {
        "metro_power_professional": 2,
        "tier3_first_time_app_user": 1,
    }


def test_cluster_heatmaps_separated_per_cluster() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        _click("a", cluster="metro_power_professional"),
        _click("a", cluster="metro_power_professional"),
        _click("a", cluster="tier3_first_time_app_user"),
        _click("b", cluster="tier3_first_time_app_user"),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert set(result.cluster_heatmaps.keys()) == {
        "metro_power_professional",
        "tier3_first_time_app_user",
    }
    metro = result.cluster_heatmaps["metro_power_professional"]
    tier3 = result.cluster_heatmaps["tier3_first_time_app_user"]
    # metro only clicked "a"; tier3 clicked both.
    assert {p.thecee_id for p in metro} == {"a"}
    assert {p.thecee_id for p in tier3} == {"a", "b"}


def test_cluster_heatmap_points_sorted_by_clicks() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = (
        [_click("a", cluster="x") for _ in range(5)]
        + [_click("b", cluster="x") for _ in range(2)]
    )
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    pts = result.cluster_heatmaps["x"]
    counts = [p.click_count for p in pts]
    assert counts == sorted(counts, reverse=True)


def test_unknown_cluster_defaults_to_unknown_label() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [{
        "agent_cluster_id": None,
        "converted": False,
        "events_json": [{"action": "click", "target": "btn"}],
    }]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    assert "unknown" in point.cluster_breakdown


# ---------------------------------------------------------------------------
# JSON event decoding
# ---------------------------------------------------------------------------


def test_events_json_string_is_decoded() -> None:
    import json as _json

    from app.simulation.heatmap import HeatmapEngine

    sessions = [{
        "agent_cluster_id": "metro",
        "converted": False,
        "events_json": _json.dumps([{"action": "click", "target": "btn"}]),
    }]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert len(result.heatmap_points) == 1


def test_garbage_events_json_falls_back_to_empty() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [{
        "agent_cluster_id": "metro",
        "converted": False,
        "events_json": "{not valid json[[[",
    }]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    # Garbage treated as no events → no points, no crash.
    assert result.heatmap_points == []


def test_missing_events_json_treated_as_empty() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [{"agent_cluster_id": "metro", "converted": False}]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.heatmap_points == []


def test_none_events_json_treated_as_empty() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        {"agent_cluster_id": "metro", "converted": False, "events_json": None},
        {"agent_cluster_id": "metro", "converted": False, "events_json": []},
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    assert result.heatmap_points == []


# ---------------------------------------------------------------------------
# Mixed event types
# ---------------------------------------------------------------------------


def test_mixed_events_only_clicks_count() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = _mixed_events("btn", "metro")
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    [point] = result.heatmap_points
    # 2 clicks out of 4 events.
    assert point.click_count == 2


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_serialises_required_keys() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = [_click("a"), _click("b")]
    result = HeatmapEngine().generate(generated_ui_id=7, sessions=sessions)
    payload = HeatmapEngine().to_dict(result)

    for key in (
        "generated_ui_id",
        "total_clicks",
        "unique_elements",
        "top_conversion_element",
        "top_abandon_element",
        "heatmap_points",
        "cluster_heatmaps",
    ):
        assert key in payload
    assert payload["generated_ui_id"] == 7


def test_to_dict_cluster_heatmaps_sorted_by_click_count_desc() -> None:
    from app.simulation.heatmap import HeatmapEngine

    sessions = (
        [_click("a", cluster="x") for _ in range(5)]
        + [_click("b", cluster="x") for _ in range(2)]
    )
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    payload = HeatmapEngine().to_dict(result)
    counts = [p["click_count"] for p in payload["cluster_heatmaps"]["x"]]
    assert counts == sorted(counts, reverse=True)


def test_to_dict_is_json_serialisable() -> None:
    import json

    from app.simulation.heatmap import HeatmapEngine

    sessions = [_click("btn", converted=True)]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    payload = HeatmapEngine().to_dict(result)
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["generated_ui_id"] == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_sessions_degrades_gracefully() -> None:
    from app.simulation.heatmap import HeatmapEngine

    result = HeatmapEngine().generate(generated_ui_id=1, sessions=[])
    # Bug: max(points, ...) on empty list raises. After fix falls back to "none".
    assert result.heatmap_points == []
    assert result.cluster_heatmaps == {}
    assert result.top_conversion_element == "none"
    assert result.top_abandon_element == "none"
    assert result.total_clicks == 0
    assert result.unique_elements == 0


def test_session_with_no_clicks_does_not_appear() -> None:
    """Sessions that only scrolled are still iterated but contribute nothing."""
    from app.simulation.heatmap import HeatmapEngine

    sessions = [
        {"agent_cluster_id": "metro", "converted": False, "events_json": [{"action": "scroll", "target": "page"}]},
        _click("real_btn"),
    ]
    result = HeatmapEngine().generate(generated_ui_id=1, sessions=sessions)
    ids = [p.thecee_id for p in result.heatmap_points]
    assert ids == ["real_btn"]


def test_generate_is_deterministic() -> None:
    from app.simulation.heatmap import HeatmapEngine

    engine = HeatmapEngine()
    sessions = [
        _click("a", converted=True),
        _click("b", converted=False),
        _click("a", converted=False),
    ]
    a = engine.generate(generated_ui_id=1, sessions=sessions)
    b = engine.generate(generated_ui_id=1, sessions=sessions)
    assert engine.to_dict(a) == engine.to_dict(b)
