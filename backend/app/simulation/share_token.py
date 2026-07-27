"""
Pure helpers for the public share-token system.

Kept DB-free so the math (token hashing, anonymisation, expiry math)
is verifiable in tests without spinning up Postgres.

The plaintext token is never persisted — only its SHA-256 hex digest.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_TTL_DAYS = 30
TOKEN_BYTES = 32  # 32 bytes → 43-char URL-safe base64 (no padding)


# ---------------------------------------------------------------------------
# Token generation / hashing
# ---------------------------------------------------------------------------


def generate_token() -> str:
    """Return a fresh URL-safe random token. ~256 bits of entropy."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of the plaintext token. Used as the lookup key."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Expiry math
# ---------------------------------------------------------------------------


def compute_expiry(now: datetime | None = None, ttl_days: int = DEFAULT_TTL_DAYS) -> datetime:
    """Return UTC expiry = now + ttl_days. Caller is responsible for tz."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(days=ttl_days)


def is_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    """True when ``expires_at`` is at or before ``now`` (UTC)."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp <= base


# ---------------------------------------------------------------------------
# Anonymisation
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json as _json

        try:
            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def anonymise_simulation(
    sim_row: dict[str, Any],
    project_row: dict[str, Any] | None,
    *,
    shared_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    """
    Build the public payload returned by ``GET /share/{token}``.

    Strips user_id / project_id and any per-user metadata, keeps only
    headline aggregates + anonymised domain findings.
    """
    results = _coerce_dict(sim_row.get("results_json"))

    funnel_raw = results.get("raw_funnel", {})
    funnel = {}
    if isinstance(funnel_raw, dict):
        for state in ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE"):
            raw = funnel_raw.get(state)
            if isinstance(raw, (int, float)):
                funnel[state] = int(raw)

    domain_findings_raw = results.get("domain_findings", []) or []
    domain_findings: list[dict[str, Any]] = []
    for f in domain_findings_raw:
        if not isinstance(f, dict):
            continue
        domain_findings.append(
            {
                "domain": str(
                    f.get("architect_name")
                    or f.get("domain")
                    or f.get("primary_domain")
                    or "Unknown"
                ),
                "severity": str(f.get("severity") or "INFO").upper(),
                "narrative": str(
                    f.get("narrative")
                    or f.get("description")
                    or f.get("summary")
                    or ""
                ),
            }
        )

    revenue_projection = results.get("revenue_projection")
    if revenue_projection is None and isinstance(funnel_raw, dict):
        revenue_projection = funnel_raw.get("revenue_projection")

    project_title = ""
    if project_row is not None:
        project_title = str(project_row.get("title") or "Untitled Project")
    else:
        project_title = "Untitled Project"

    return {
        "project_title": project_title,
        "product_type_detected": str(results.get("product_type_detected") or "")
        or None,
        "status": str(sim_row.get("status") or "UNKNOWN").upper(),
        "signal_quality": (
            _safe_float(sim_row.get("signal_quality"))
            if sim_row.get("signal_quality") is not None
            else None
        ),
        "population_weighted_conversion": _safe_float(
            results.get("population_weighted_conversion")
            or results.get("conversion_rate")
        ),
        "revenue_projection": (
            _safe_float(revenue_projection) if revenue_projection is not None else None
        ),
        "primary_failure_domain": str(results.get("primary_failure_domain") or "")
        or None,
        "funnel": funnel,
        "domain_findings": domain_findings,
        "shared_at": shared_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


__all__ = [
    "DEFAULT_TTL_DAYS",
    "generate_token",
    "hash_token",
    "compute_expiry",
    "is_expired",
    "anonymise_simulation",
]
