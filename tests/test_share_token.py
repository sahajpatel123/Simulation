"""
Tests for the share-token pure helpers and route registration.

The pure ``app.simulation.share_token`` layer (token generation, hashing,
expiry math, anonymisation) is fully covered here. The DB-backed routes
need an integration env, so they are smoke-tested via route registration
only — the helper layer is where the meaningful business logic lives.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Token generation / hashing
# ---------------------------------------------------------------------------


def test_generate_token_is_urlsafe_and_long() -> None:
    from app.simulation.share_token import generate_token

    token = generate_token()
    # 32 bytes → 43-char URL-safe base64 (no padding).
    assert len(token) >= 40
    assert isinstance(token, str)
    # URL-safe alphabet only.
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert set(token) <= allowed


def test_generate_token_is_unique_per_call() -> None:
    from app.simulation.share_token import generate_token

    tokens = {generate_token() for _ in range(50)}
    assert len(tokens) == 50  # collisions over 50 calls would be astronomically unlikely


def test_hash_token_is_deterministic_and_64_hex() -> None:
    from app.simulation.share_token import hash_token

    h1 = hash_token("hello-world")
    h2 = hash_token("hello-world")
    assert h1 == h2
    assert len(h1) == 64
    int(h1, 16)  # must be valid hex


def test_hash_token_differs_per_input() -> None:
    from app.simulation.share_token import hash_token

    assert hash_token("a") != hash_token("b")


# ---------------------------------------------------------------------------
# Expiry math
# ---------------------------------------------------------------------------


def test_compute_expiry_default_is_30_days() -> None:
    from app.simulation.share_token import compute_expiry

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exp = compute_expiry(now=now)
    assert exp == now + timedelta(days=30)


def test_compute_expiry_respects_ttl_days() -> None:
    from app.simulation.share_token import compute_expiry

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exp = compute_expiry(now=now, ttl_days=7)
    assert exp == now + timedelta(days=7)


def test_compute_expiry_coerces_naive_to_utc() -> None:
    """Naive datetimes should be treated as UTC — never local time."""
    from app.simulation.share_token import compute_expiry

    naive = datetime(2026, 1, 1, 12, 0, 0)
    exp = compute_expiry(now=naive)
    assert exp.tzinfo is not None
    assert exp.hour == 12  # UTC time preserved


def test_is_expired_true_for_past() -> None:
    from app.simulation.share_token import is_expired

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert is_expired(datetime(2026, 1, 1, tzinfo=timezone.utc), now=now) is True


def test_is_expired_false_for_future() -> None:
    from app.simulation.share_token import is_expired

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert is_expired(datetime(2026, 1, 3, tzinfo=timezone.utc), now=now) is False


def test_is_expired_true_at_exact_boundary() -> None:
    """``exp <= now`` is treated as expired — strictly safer."""
    from app.simulation.share_token import is_expired

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert is_expired(now, now=now) is True


# ---------------------------------------------------------------------------
# Anonymisation
# ---------------------------------------------------------------------------


def _completed_sim_row() -> dict:
    return {
        "id": 42,
        "status": "COMPLETED",
        "signal_quality": 0.74,
        "results_json": {
            "product_type_detected": "saas",
            "population_weighted_conversion": 0.062,
            "revenue_projection": 124000.0,
            "primary_failure_domain": "Pricing",
            "raw_funnel": {
                "ARRIVE": 10000,
                "BROWSE": 8700,
                "CONSIDER": 5394,
                "DECIDE": 2481,
                "PURCHASE": 769,
            },
            "domain_findings": [
                {
                    "architect_name": "Pricing",
                    "severity": "critical",
                    "narrative": "AOV above cluster willingness-to-pay for 41% of agents.",
                },
                {
                    "architect_name": "Trust",
                    "severity": "WARNING",
                    "summary": "No public testimonials — trust signals missing.",
                },
            ],
        },
    }


def test_anonymise_strips_user_id_and_project_id() -> None:
    from app.simulation.share_token import anonymise_simulation

    shared_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    expires_at = datetime(2026, 7, 31, tzinfo=timezone.utc)
    out = anonymise_simulation(
        sim_row=_completed_sim_row(),
        project_row={"title": "Acme SaaS"},
        shared_at=shared_at,
        expires_at=expires_at,
    )
    # No leakage of caller identifiers.
    assert "user_id" not in out
    assert "project_id" not in out
    assert "id" not in out or out.get("id") is None
    # Anonymised title is present.
    assert out["project_title"] == "Acme SaaS"


def test_anonymise_reads_funnel_counts() -> None:
    from app.simulation.share_token import anonymise_simulation

    out = anonymise_simulation(
        sim_row=_completed_sim_row(),
        project_row={"title": "X"},
        shared_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    assert out["funnel"] == {
        "ARRIVE": 10000,
        "BROWSE": 8700,
        "CONSIDER": 5394,
        "DECIDE": 2481,
        "PURCHASE": 769,
    }


def test_anonymise_normalises_finding_severity() -> None:
    from app.simulation.share_token import anonymise_simulation

    out = anonymise_simulation(
        sim_row=_completed_sim_row(),
        project_row={"title": "X"},
        shared_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    severities = [f["severity"] for f in out["domain_findings"]]
    assert severities == ["CRITICAL", "WARNING"]


def test_anonymise_handles_missing_project() -> None:
    from app.simulation.share_token import anonymise_simulation

    out = anonymise_simulation(
        sim_row=_completed_sim_row(),
        project_row=None,
        shared_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    assert out["project_title"] == "Untitled Project"


def test_anonymise_handles_missing_revenue_projection() -> None:
    from app.simulation.share_token import anonymise_simulation

    row = _completed_sim_row()
    row["results_json"] = {
        "population_weighted_conversion": 0.05,
        "raw_funnel": {"ARRIVE": 100, "BROWSE": 80},
    }
    out = anonymise_simulation(
        sim_row=row,
        project_row={"title": "X"},
        shared_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    assert out["revenue_projection"] is None
    assert out["funnel"] == {"ARRIVE": 100, "BROWSE": 80}


def test_anonymise_handles_string_results_json() -> None:
    """results_json may arrive as a JSON string; we should still parse it."""
    import json

    from app.simulation.share_token import anonymise_simulation

    row = _completed_sim_row()
    row["results_json"] = json.dumps(row["results_json"])
    out = anonymise_simulation(
        sim_row=row,
        project_row={"title": "X"},
        shared_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    assert out["population_weighted_conversion"] == 0.062


def test_anonymise_skips_non_dict_findings() -> None:
    from app.simulation.share_token import anonymise_simulation

    row = _completed_sim_row()
    row["results_json"]["domain_findings"] = [
        {"architect_name": "Pricing", "severity": "CRITICAL", "narrative": "ok"},
        "garbage",
        None,
        {"architect_name": "Trust", "severity": "WARNING", "narrative": "ok"},
    ]
    out = anonymise_simulation(
        sim_row=row,
        project_row={"title": "X"},
        shared_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    assert len(out["domain_findings"]) == 2


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_share_routes_registered() -> None:
    """The three share routes should appear in the share router."""
    # Stub razorpay to avoid the transitive ``pkg_resources`` import that
    # breaks on minimal envs when ``app.api.v1.__init__`` runs.
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.api.v1 import share as share_mod

    # The module-level router is composed via ``include_router``; each
    # entry wraps an ``original_router`` that owns the actual routes.
    paths = set()
    methods_by_path: dict[str, set[str]] = {}
    for sub in share_mod.router.routes:
        inner = getattr(sub, "original_router", None)
        inner_routes = getattr(inner, "routes", None) if inner is not None else None
        if inner_routes is None:
            continue
        for r in inner_routes:
            paths.add(r.path)
            methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "/simulations/{simulation_id}/share" in paths
    assert "/share/{token}" in paths
    # DELETE is on the same path as POST — verify both methods are present.
    assert "POST" in methods_by_path["/simulations/{simulation_id}/share"]
    assert "DELETE" in methods_by_path["/simulations/{simulation_id}/share"]
    assert "GET" in methods_by_path["/share/{token}"]


# ---------------------------------------------------------------------------
# Schema-level invariants
# ---------------------------------------------------------------------------


def test_share_token_out_round_trip() -> None:
    from app.schemas.share import ShareTokenOut

    out = ShareTokenOut(
        token="abc123",
        simulation_id=42,
        scope="read_only",
        expires_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        share_url="/api/v1/share/abc123",
    )
    dumped = out.model_dump()
    assert dumped["token"] == "abc123"
    assert dumped["scope"] == "read_only"
    assert dumped["share_url"].endswith("abc123")


def test_shared_simulation_out_rejects_user_data() -> None:
    """The public response schema must not expose user_id / project_id."""
    from app.schemas.share import SharedSimulationOut

    fields = set(SharedSimulationOut.model_fields.keys())
    assert "user_id" not in fields
    assert "project_id" not in fields
    assert "id" not in fields  # anonymised — only project_title leaks
    assert "simulation_id" not in fields
    assert "project_title" in fields
    assert "funnel" in fields
    assert "domain_findings" in fields