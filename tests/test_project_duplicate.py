"""
Tests for ``app.simulation.project_duplicate`` — pure helpers that
build the new title + project / environment payload for a clone.

The DB-touching route lives in ``app/api/v1/projects.py`` and is
smoke-tested via route registration here.
"""
from __future__ import annotations

import sys
import types


# ---------------------------------------------------------------------------
# Title builder
# ---------------------------------------------------------------------------


def test_title_for_first_copy_appends_copy() -> None:
    from app.simulation.project_duplicate import build_duplicate_title

    assert build_duplicate_title("My Idea") == "My Idea (copy)"


def test_title_increments_existing_copy_marker() -> None:
    from app.simulation.project_duplicate import build_duplicate_title

    assert build_duplicate_title("My Idea (copy)") == "My Idea (copy 2)"
    assert build_duplicate_title("My Idea (copy 7)") == "My Idea (copy 8)"


def test_title_preserves_whitespace_in_base() -> None:
    from app.simulation.project_duplicate import build_duplicate_title

    # Surrounding whitespace inside the base is preserved; only outer
    # whitespace is stripped.
    assert build_duplicate_title("  spaced  ") == "spaced (copy)"


def test_title_falls_back_when_blank() -> None:
    from app.simulation.project_duplicate import build_duplicate_title

    assert build_duplicate_title("") == "Untitled Project (copy)"
    assert build_duplicate_title("   ") == "Untitled Project (copy)"


def test_title_clamps_to_500_chars() -> None:
    from app.simulation.project_duplicate import build_duplicate_title

    long_base = "x" * 600
    out = build_duplicate_title(long_base)
    assert len(out) <= 500
    assert out.endswith("(copy)")


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def test_payload_resets_runtime_fields() -> None:
    """The duplicate must NOT inherit brief_completed_at, status, simulations."""
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={
            "title": "My Idea",
            "description": "An idea",
            "precis": "summary",
            "readings_json": "{}",
        },
        environment=None,
    )
    assert built["project"]["title"] == "My Idea (copy)"
    assert built["project"]["status"] == "DRAFT"
    assert built["project"]["brief_completed_at"] is None
    assert built["environment"] is None


def test_payload_uses_overridden_title() -> None:
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={"title": "Old", "description": "x"},
        environment=None,
        new_title="Variant B",
    )
    assert built["project"]["title"] == "Variant B"


def test_payload_falls_back_to_default_naming_when_override_empty() -> None:
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={"title": "Old", "description": "x"},
        environment=None,
        new_title="   ",
    )
    assert built["project"]["title"] == "Old (copy)"


def test_payload_copies_environment_values() -> None:
    from app.simulation.project_duplicate import duplicate_project_payload

    env = {
        "mode": "SCENARIO",
        "consumer_volume": 5000,
        "growth_rate_per_month": 12.5,
        "average_order_value": 499.0,
        "price_sensitivity": 0.7,
        "market_maturity": 0.4,
        "scenario_type": "HIGH_GROWTH",
        "manual_params_json": {"k": "v"},
        "trend_data_json": {"trajectory": [1, 2, 3]},
    }
    built = duplicate_project_payload(
        project={"title": "Old", "description": "x"},
        environment=env,
    )
    assert built["environment"] == env


def test_payload_coerces_environment_defaults() -> None:
    """Missing env fields fall back to the canonical defaults."""
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={"title": "Old", "description": "x"},
        environment={},
    )
    env = built["environment"]
    assert env["mode"] == "MANUAL"
    assert env["consumer_volume"] == 10000
    assert env["price_sensitivity"] == 0.5
    assert env["market_maturity"] == 0.3


def test_payload_handles_no_environment() -> None:
    """Source projects without an environment must still duplicate cleanly."""
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={"title": "Bare", "description": "x"},
        environment=None,
    )
    assert built["environment"] is None
    assert built["project"]["title"] == "Bare (copy)"


# ---------------------------------------------------------------------------
# Schema + route registration
# ---------------------------------------------------------------------------


def test_project_duplicate_in_schema_accepts_empty_body() -> None:
    from app.schemas.project import ProjectDuplicateIn

    p = ProjectDuplicateIn()
    assert p.new_title is None


def test_project_duplicate_in_schema_caps_title() -> None:
    from pydantic import ValidationError

    from app.schemas.project import ProjectDuplicateIn

    ProjectDuplicateIn(new_title="ok" * 50)  # 100 chars — fine
    with pytest.raises(ValidationError):
        ProjectDuplicateIn(new_title="x" * 501)  # 501 chars — too long


def test_duplicate_route_registered() -> None:
    """POST /projects/{project_id}/duplicate should appear in the router."""
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.api.v1 import projects as projects_mod

    paths = {r.path for r in projects_mod.router.routes}
    assert "/projects/{project_id}/duplicate" in paths

    # Verify it's POST with the response_model.
    methods_by_path: dict[str, set[str]] = {}
    for r in projects_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "POST" in methods_by_path["/projects/{project_id}/duplicate"]


# ---------------------------------------------------------------------------
# Polish: include_simulations / dry_run flags
# ---------------------------------------------------------------------------


def test_duplicate_in_defaults_are_safe() -> None:
    """Default behavior should be a clean duplicate (no sims, no dry run)."""
    from app.schemas.project import ProjectDuplicateIn

    p = ProjectDuplicateIn()
    assert p.include_simulations is False
    assert p.dry_run is False
    assert p.new_title is None


def test_duplicate_in_accepts_polish_flags() -> None:
    from app.schemas.project import ProjectDuplicateIn

    p = ProjectDuplicateIn(
        new_title="Variant B",
        include_simulations=True,
        dry_run=True,
    )
    assert p.new_title == "Variant B"
    assert p.include_simulations is True
    assert p.dry_run is True


def test_duplicate_out_round_trip() -> None:
    from app.schemas.project import ProjectDuplicateOut

    payload = ProjectDuplicateOut(
        project={
            "id": 99,
            "title": "My Idea (copy)",
            "description": "Test project",
            "status": "DRAFT",
            "user_id": 7,
        },
        source_project_id=42,
        simulations_copied=0,
        environment_copied=True,
        dry_run=False,
    )
    dumped = payload.model_dump()
    assert dumped["source_project_id"] == 42
    assert dumped["simulations_copied"] == 0
    assert dumped["environment_copied"] is True
    assert dumped["dry_run"] is False


def test_duplicate_out_carries_simulations_count() -> None:
    """When include_simulations=true, the counter reports the snapshot count."""
    from app.schemas.project import ProjectDuplicateOut

    payload = ProjectDuplicateOut(
        project={"id": 99, "title": "x", "description": "x", "status": "DRAFT", "user_id": 7},
        source_project_id=42,
        simulations_copied=3,
        environment_copied=True,
        dry_run=False,
    )
    assert payload.simulations_copied == 3


def test_duplicate_out_dry_run_is_visible() -> None:
    """dry_run must be a top-level field so the dashboard can render a preview banner."""
    from app.schemas.project import ProjectDuplicateOut

    payload = ProjectDuplicateOut(
        project={"id": 0, "title": "x", "description": "x", "status": "DRAFT", "user_id": 7},
        source_project_id=42,
        simulations_copied=0,
        environment_copied=False,
        dry_run=True,
    )
    assert payload.dry_run is True


import pytest  # noqa: E402  — placed here so helper tests above don't import it prematurely