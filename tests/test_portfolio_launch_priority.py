"""Pure-helper tests for the portfolio launch-priority digest."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.portfolio_launch_priority import PortfolioLaunchPriorityOut
from app.simulation.go_no_go import (
    VERDICT_CONDITIONAL_GO,
    VERDICT_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_NO_GO,
)
from app.simulation.portfolio_launch_priority import (
    BUCKET_CONDITIONAL_LAUNCH,
    BUCKET_FIX_FIRST,
    BUCKET_LAUNCH_NOW,
    BUCKET_PARK,
    PORTFOLIO_VERDICT_ALMOST_READY,
    PORTFOLIO_VERDICT_INSUFFICIENT,
    PORTFOLIO_VERDICT_NOT_READY,
    PORTFOLIO_VERDICT_READY,
    build_portfolio_launch_priority,
)

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _scorecard(
    score: int | None,
    verdict: str,
    *,
    verdict_label: str = "",
    latest_simulation_id: int | None = None,
    pillars: list[dict] | None = None,
    top_actions: list[str] | None = None,
) -> dict:
    return {
        "go_no_go_score": score,
        "verdict": verdict,
        "verdict_label": verdict_label or verdict,
        "latest_simulation_id": latest_simulation_id,
        "pillars": pillars or [],
        "top_actions": top_actions or [],
    }


def _project(
    project_id: int,
    title: str,
    score: int | None,
    verdict: str,
    *,
    sim_at: datetime | None = None,
    has_outcomes: bool = False,
    pillars: list[dict] | None = None,
    top_actions: list[str] | None = None,
) -> dict:
    return {
        "project_id": project_id,
        "project_title": title,
        "latest_simulation_at": sim_at,
        "has_outcomes": has_outcomes,
        "go_no_go": _scorecard(
            score,
            verdict,
            latest_simulation_id=project_id * 10,
            pillars=pillars,
            top_actions=top_actions,
        ),
    }


def _pillar(key: str, score: int | None) -> dict:
    return {"key": key, "label": key, "score": score}


def test_empty_input_returns_canonical_empty_payload() -> None:
    out = build_portfolio_launch_priority([], now=_NOW)

    assert out["project_count"] == 0
    assert out["evaluated_count"] == 0
    assert out["portfolio_verdict"] == PORTFOLIO_VERDICT_INSUFFICIENT
    assert out["top_pick"] is None
    assert out["launch_sequence"] == []
    assert out["next_focus"] == ""
    for bucket in (
        BUCKET_LAUNCH_NOW,
        BUCKET_CONDITIONAL_LAUNCH,
        BUCKET_FIX_FIRST,
        BUCKET_PARK,
    ):
        assert out["buckets"][bucket] == []
    assert "No projects with a usable launch scorecard" in out["narrative"]
    assert out["meta"]["generated_at"] == _NOW.isoformat()
    assert out["meta"]["caps"]["max_launch_sequence"] == 25


def test_malformed_entries_are_skipped() -> None:
    out = build_portfolio_launch_priority(
        [
            {"project_id": 1, "project_title": "No scorecard"},
            {
                "project_id": 2,
                "project_title": "Bad scorecard",
                "go_no_go": "not-a-dict",
            },
            {
                "project_id": 0,
                "project_title": "Zero id",
                "go_no_go": _scorecard(80, VERDICT_GO),
            },
            _project(3, "Good", 80, VERDICT_GO),
        ],
        now=_NOW,
    )

    assert out["project_count"] == 4
    assert out["evaluated_count"] == 1
    assert out["launch_sequence"] == [3]
    assert out["top_pick"]["project_id"] == 3


def test_buckets_and_ranking_by_score() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(1, "Weak", 40, VERDICT_NO_GO),
            _project(2, "Strong", 90, VERDICT_GO),
            _project(3, "Conditional", 80, VERDICT_CONDITIONAL_GO),
            _project(4, "Mid", 85, VERDICT_GO),
            _project(5, "Parked", None, VERDICT_INSUFFICIENT),
        ],
        now=_NOW,
    )

    assert out["evaluated_count"] == 5
    assert out["launch_sequence"] == [2, 4, 3, 1, 5]
    assert [p["project_id"] for p in out["buckets"][BUCKET_LAUNCH_NOW]] == [
        2,
        4,
    ]
    assert [
        p["project_id"] for p in out["buckets"][BUCKET_CONDITIONAL_LAUNCH]
    ] == [3]
    assert [p["project_id"] for p in out["buckets"][BUCKET_FIX_FIRST]] == [1]
    assert [p["project_id"] for p in out["buckets"][BUCKET_PARK]] == [5]
    assert out["top_pick"]["project_id"] == 2
    assert out["top_pick"]["rank"] == 1
    assert out["top_pick"]["bucket"] == BUCKET_LAUNCH_NOW


def test_verdict_priority_breaks_score_ties() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(1, "Conditional", 80, VERDICT_CONDITIONAL_GO),
            _project(2, "Go", 80, VERDICT_GO),
            _project(3, "NoGo", 40, VERDICT_NO_GO),
            _project(4, "Parked", 40, VERDICT_INSUFFICIENT),
        ],
        now=_NOW,
    )

    assert out["launch_sequence"] == [2, 1, 3, 4]


def test_freshness_breaks_score_and_verdict_ties() -> None:
    older = _NOW - timedelta(days=10)
    newer = _NOW - timedelta(days=1)
    out = build_portfolio_launch_priority(
        [
            _project(1, "Older", 70, VERDICT_GO, sim_at=older),
            _project(2, "Newer", 70, VERDICT_GO, sim_at=newer),
        ],
        now=_NOW,
    )

    assert out["launch_sequence"] == [2, 1]


def test_project_id_is_stable_final_tiebreak() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(9, "Nine", 70, VERDICT_GO, sim_at=None),
            _project(2, "Two", 70, VERDICT_GO, sim_at=None),
        ],
        now=_NOW,
    )

    assert out["launch_sequence"] == [2, 9]


def test_portfolio_verdict_priorities() -> None:
    ready = build_portfolio_launch_priority(
        [
            _project(1, "Go", 90, VERDICT_GO),
            _project(2, "Fix", 30, VERDICT_NO_GO),
        ],
        now=_NOW,
    )
    assert ready["portfolio_verdict"] == PORTFOLIO_VERDICT_READY

    almost = build_portfolio_launch_priority(
        [
            _project(1, "Conditional", 70, VERDICT_CONDITIONAL_GO),
            _project(2, "Parked", None, VERDICT_INSUFFICIENT),
        ],
        now=_NOW,
    )
    assert almost["portfolio_verdict"] == PORTFOLIO_VERDICT_ALMOST_READY

    not_ready = build_portfolio_launch_priority(
        [
            _project(1, "Fix", 30, VERDICT_NO_GO),
            _project(2, "Parked", None, VERDICT_INSUFFICIENT),
        ],
        now=_NOW,
    )
    assert not_ready["portfolio_verdict"] == PORTFOLIO_VERDICT_NOT_READY

    parked = build_portfolio_launch_priority(
        [_project(1, "Parked", None, VERDICT_INSUFFICIENT)],
        now=_NOW,
    )
    assert parked["portfolio_verdict"] == PORTFOLIO_VERDICT_INSUFFICIENT


def test_reasons_and_top_action() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(
                1,
                "Go",
                90,
                VERDICT_GO,
                top_actions=["Ship the landing page"],
            ),
            _project(2, "Parked", None, VERDICT_INSUFFICIENT),
        ],
        now=_NOW,
    )

    assert "Signals support launch (go/no-go 90/100)" in out["top_pick"]["reason"]
    assert out["top_pick"]["top_action"] == "Ship the landing page"
    parked = out["buckets"][BUCKET_PARK][0]
    assert "Insufficient launch data" in parked["reason"]
    assert parked["top_action"] == ""


def test_weakest_pillar_is_exposed() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(
                1,
                "Go",
                75,
                VERDICT_GO,
                pillars=[
                    _pillar("readiness", 80),
                    _pillar("premortem", 30),
                ],
            ),
        ],
        now=_NOW,
    )

    weakest = out["top_pick"]["weakest_pillar"]
    assert weakest is not None
    assert weakest["key"] == "premortem"
    assert weakest["score"] == 30
    # The internal ``pillars`` working key must never leak into the
    # public item.
    assert "pillars" not in out["top_pick"]


def test_next_focus_picks_weakest_pillar_across_top_candidates() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(
                1,
                "A",
                90,
                VERDICT_GO,
                pillars=[_pillar("readiness", 90), _pillar("coverage", 60)],
            ),
            _project(
                2,
                "B",
                85,
                VERDICT_GO,
                pillars=[_pillar("readiness", 95), _pillar("coverage", 50)],
            ),
            _project(
                3,
                "C",
                80,
                VERDICT_GO,
                pillars=[_pillar("readiness", 85), _pillar("coverage", 70)],
            ),
        ],
        now=_NOW,
    )

    focus = out["next_focus"]
    assert "coverage" in focus.lower()
    assert "60/100" in focus
    assert "3 top candidate(s)" in focus


def test_next_focus_empty_without_pillars() -> None:
    out = build_portfolio_launch_priority(
        [_project(1, "A", 90, VERDICT_GO, pillars=[])],
        now=_NOW,
    )
    assert out["next_focus"] == ""


def test_launch_sequence_cap() -> None:
    projects = [
        _project(i, f"P{i}", 90, VERDICT_GO)
        for i in range(1, 31)
    ]
    out = build_portfolio_launch_priority(projects, now=_NOW)

    assert len(out["launch_sequence"]) == 25
    assert out["launch_sequence"] == list(range(1, 26))
    assert len(out["buckets"][BUCKET_LAUNCH_NOW]) == 10
    assert out["evaluated_count"] == 30


def test_key_signal_severities() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(1, "Fix", 30, VERDICT_NO_GO),
            _project(2, "Fix", 25, VERDICT_NO_GO),
            _project(3, "Fix", 20, VERDICT_NO_GO),
        ],
        now=_NOW,
    )
    signals = {s["label"]: s for s in out["key_signals"]}
    assert signals["launch_now_count"]["severity"] == "watch"
    assert signals["fix_first_count"]["severity"] == "critical"
    assert signals["top_pick_score"]["severity"] == "critical"

    ok = build_portfolio_launch_priority(
        [_project(1, "Go", 90, VERDICT_GO)],
        now=_NOW,
    )
    ok_signals = {s["label"]: s for s in ok["key_signals"]}
    assert ok_signals["launch_now_count"]["severity"] == "ok"
    assert ok_signals["top_pick_score"]["severity"] == "ok"
    assert ok_signals["portfolio_verdict"]["value"] == PORTFOLIO_VERDICT_READY


def test_schema_roundtrip() -> None:
    out = build_portfolio_launch_priority(
        [
            _project(
                1,
                "Go",
                90,
                VERDICT_GO,
                sim_at=_NOW,
                has_outcomes=True,
                pillars=[_pillar("readiness", 90)],
            ),
        ],
        now=_NOW,
    )
    parsed = PortfolioLaunchPriorityOut(**out)

    assert parsed.project_count == 1
    assert parsed.evaluated_count == 1
    assert parsed.top_pick is not None
    assert parsed.top_pick.project_title == "Go"
    assert parsed.top_pick.latest_simulation_at is not None
    assert parsed.top_pick.has_outcomes is True
    assert parsed.buckets[BUCKET_LAUNCH_NOW][0].project_id == 1
    assert parsed.launch_sequence == [1]
    assert parsed.meta["caps"]["max_bucket_items"] == 10
