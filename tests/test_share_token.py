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

    # FastAPI's router-internals (``_IncludedRouter`` /
    # ``original_router`` / ``api_router``) shift between versions
    # (verified broken on FastAPI 0.115.0 vs 0.139.x). Walk the
    # routes recursively instead — any object exposing a
    # ``.routes`` list contributes its leaves.
    def _collect_routes(carrier) -> list:
        leaves = []
        for item in getattr(carrier, "routes", []):
            inner = (
                getattr(item, "original_router", None)
                or getattr(item, "api_router", None)
                or getattr(item, "router", None)
            )
            if inner is not None and inner is not item:
                leaves.extend(_collect_routes(inner))
            else:
                leaves.append(item)
        return leaves

    routes = _collect_routes(share_mod.router)
    paths = {r.path for r in routes}
    methods_by_path: dict[str, set[str]] = {}
    for r in routes:
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


# ---------------------------------------------------------------------------
# Polish iteration: list endpoint + token validation + schema additions
# ---------------------------------------------------------------------------


def test_share_token_list_item_round_trip() -> None:
    from app.schemas.share import ShareTokenListItem

    item = ShareTokenListItem(
        id=1,
        simulation_id=42,
        scope="read_only",
        is_active=True,
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        revoked_at=None,
        last_accessed_at=None,
        access_count=0,
    )
    dumped = item.model_dump()
    assert dumped["is_active"] is True
    assert dumped["access_count"] == 0
    assert dumped["plaintext_token" if "plaintext_token" in dumped else "id"] == 1


def test_share_token_list_out_counters_sum() -> None:
    from app.schemas.share import ShareTokenListItem, ShareTokenListOut

    items = [
        ShareTokenListItem(
            id=1,
            simulation_id=42,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        ),
        ShareTokenListItem(
            id=2,
            simulation_id=42,
            is_active=False,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
            revoked_at=datetime.now(timezone.utc),
        ),
    ]
    out = ShareTokenListOut(
        simulation_id=42,
        active_count=1,
        revoked_count=1,
        expired_count=0,
        tokens=items,
    )
    assert len(out.tokens) == 2
    # Counters cover every token in the list exactly once.
    assert out.active_count + out.revoked_count + out.expired_count == len(items)


def test_share_token_list_out_does_not_leak_plaintext() -> None:
    """The list response must never carry the plaintext token."""
    from app.schemas.share import ShareTokenListOut

    fields = set(ShareTokenListOut.model_fields.keys())
    assert "token" not in fields
    assert "plaintext_token" not in fields
    assert "token_hash" not in fields
    # Only summary / counters + the nested item list — the per-item
    # ``id`` lives inside ``tokens`` and is verified separately.
    assert "tokens" in fields
    assert "active_count" in fields
    assert "simulation_id" in fields
    assert "revoked_count" in fields
    assert "expired_count" in fields


def test_routes_include_list_endpoint() -> None:
    """POST / GET / DELETE / GET-list — all four should be present."""
    import sys
    import types

    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.api.v1 import share as share_mod

    # Same FastAPI-version-agnostic walker as
    # ``test_share_routes_registered`` — pinned 0.115.0 doesn't
    # expose ``original_router`` the way 0.139.x does.
    def _collect_routes(carrier) -> list:
        leaves = []
        for item in getattr(carrier, "routes", []):
            inner = (
                getattr(item, "original_router", None)
                or getattr(item, "api_router", None)
                or getattr(item, "router", None)
            )
            if inner is not None and inner is not item:
                leaves.extend(_collect_routes(inner))
            else:
                leaves.append(item)
        return leaves

    routes = _collect_routes(share_mod.router)
    paths = {r.path for r in routes}
    methods_by_path: dict[str, set[str]] = {}
    for r in routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "/simulations/{simulation_id}/share" in paths
    assert "/share/{token}" in paths
    # The new GET-list shares the same path as POST + DELETE.
    assert "POST" in methods_by_path["/simulations/{simulation_id}/share"]
    assert "DELETE" in methods_by_path["/simulations/{simulation_id}/share"]
    assert "GET" in methods_by_path["/simulations/{simulation_id}/share"]
    assert "GET" in methods_by_path["/share/{token}"]


def test_compute_expiry_returns_aware_datetime() -> None:
    """All expiry / shared_at timestamps must be tz-aware after polish."""
    from app.simulation.share_token import compute_expiry

    exp = compute_expiry()
    assert exp.tzinfo is not None
    assert exp.tzinfo.utcoffset(exp) == timedelta(0)


def test_generated_token_meets_min_length() -> None:
    """``secrets.token_urlsafe(32)`` is 43 chars — well above the 16-char floor."""
    from app.simulation.share_token import generate_token

    for _ in range(20):
        assert len(generate_token()) >= 16