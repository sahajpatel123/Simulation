"""Tests for the per-project latest-snapshot helper."""
from __future__ import annotations

from datetime import UTC, datetime


def test_public_allowlist_matches_callers() -> None:
    from app.simulation import latest_snapshot

    assert set(latest_snapshot.__all__) == {
        "SIGNAL_OK",
        "SIGNAL_WATCH",
        "SIGNAL_CRITICAL",
        "build_latest_snapshot",
    }


def test_snapshot_empty_returns_fallback_state() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X", project_status=None,
        brief_completed=False,
        latest_simulation_row=None,
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    assert out["project_id"] == 1
    assert out["project_title"] == "X"
    assert out["project_status"] == "UNKNOWN"
    assert out["latest_simulation"] is None


def test_snapshot_picks_compact_fields_from_simulation() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    sim_row = {
        "id": 42, "status": "COMPLETED",
        "created_at": "2026-01-05T00:00:00Z",
        "predicted_conversion_rate": 0.05,
        "actual_conversion_rate": None,
        "confidence_score": 0.85,
        "domain_findings": [...],  # should NOT pass through
    }
    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status="COMPLETE",
        brief_completed=True,
        latest_simulation_row=sim_row,
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    sim = out["latest_simulation"]
    assert sim["id"] == 42
    assert sim["status"] == "COMPLETED"
    assert sim["predicted_conversion_rate"] == 0.05
    # domain_findings is NOT in the whitelist.
    assert "domain_findings" not in sim


def test_snapshot_compact_decision() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status="COMPLETE",
        brief_completed=False,
        latest_simulation_row=None,
        latest_decision_row={
            "id": 7, "title": "Pivot?",
            "status": "PENDING",
            "created_at": "2026-01-04T00:00:00Z",
            "description": "...",  # not in whitelist
        },
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    dec = out["latest_decision"]
    assert dec["id"] == 7
    assert dec["title"] == "Pivot?"
    assert "description" not in dec


def test_snapshot_compact_outcome() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status="COMPLETE",
        brief_completed=False,
        latest_simulation_row=None,
        latest_decision_row=None,
        latest_outcome_row={
            "id": 11, "created_at": "2026-01-02T00:00:00Z",
            "actual_conversion_rate": 0.051,
            "actual_mrr": 50000,
            "calibration_score": 80,
            "notes": "...",
        },
        latest_assumption_row=None,
    )
    out_row = out["latest_outcome"]
    assert out_row["calibration_score"] == 80
    assert "notes" not in out_row


def test_snapshot_assumption_only_when_text_or_created_present() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status="COMPLETE",
        brief_completed=False,
        latest_simulation_row=None,
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row={
            "id": 1, "text": "Devs want speed",
            "sensitivity": "HIGH", "created_at": "2026-01-01",
            "category": "Market",  # not in whitelist
        },
    )
    assert (
        out["latest_assumption_extraction"]["text"]
        == "Devs want speed"
    )
    assert "category" not in (
        out["latest_assumption_extraction"]
    )


def test_snapshot_no_assumption_when_only_unrelated_fields() -> None:
    """If the latest assumption row is somehow empty of
    fields in the whitelist, skip it."""
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status="COMPLETE",
        brief_completed=False,
        latest_simulation_row=None,
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row={
            "id": 1,
            "category": "Market",
        },
    )
    assert out["latest_assumption_extraction"] is None


def test_snapshot_narrative_mentions_status_and_title() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=42, project_title="DevTwin",
        project_status="COMPLETE",
        brief_completed=True,
        latest_simulation_row={
            "id": 1, "status": "COMPLETED",
            "created_at": "2026-01-05",
            "predicted_conversion_rate": 0.05,
            "actual_conversion_rate": None,
            "confidence_score": 0.85,
        },
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    n = out["narrative"]
    assert "DevTwin" in n
    assert "COMPLETE" in n
    assert "Brief completed" in n


def test_snapshot_key_signals_present() -> None:
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status=None,
        brief_completed=False,
        latest_simulation_row=None,
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    labels = {s["label"] for s in out["key_signals"]}
    assert "latest_simulation_present" in labels
    assert "latest_outcome_present" in labels
    assert "brief_completed" in labels


def test_snapshot_handles_datetime_objects() -> None:
    """datetime objects inside rows should be ISO-serialised
    by _compact."""
    from app.simulation.latest_snapshot import build_latest_snapshot

    out = build_latest_snapshot(
        project_id=1, project_title="X",
        project_status="COMPLETE",
        brief_completed=False,
        latest_simulation_row={
            "id": 1, "status": "COMPLETED",
            "created_at": datetime(
                2026, 1, 5, tzinfo=UTC,
            ),
            "predicted_conversion_rate": 0.05,
            "actual_conversion_rate": None,
            "confidence_score": 0.85,
        },
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    sim = out["latest_simulation"]
    assert "2026-01-05" in sim["created_at"]


def test_snapshot_schema_default_shape() -> None:
    from app.schemas.project import LatestSnapshotOut

    out = LatestSnapshotOut()
    assert out.project_id is None
    assert out.project_status == "UNKNOWN"
    assert out.brief_completed is False
    assert out.latest_simulation is None


def test_snapshot_schema_round_trip() -> None:
    from app.schemas.project import LatestSnapshotOut
    from app.simulation.latest_snapshot import build_latest_snapshot

    payload = build_latest_snapshot(
        project_id=99, project_title="Y",
        project_status="COMPLETE",
        brief_completed=True,
        latest_simulation_row=None,
        latest_decision_row=None,
        latest_outcome_row=None,
        latest_assumption_row=None,
    )
    out = LatestSnapshotOut(**payload)
    assert out.project_id == 99
    assert out.project_title == "Y"
    assert out.brief_completed is True
