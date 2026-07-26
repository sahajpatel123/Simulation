"""
Pure helpers for project duplication.

Kept DB-free so the naming / counter math is verifiable in tests without
spinning up Postgres. The route handler in ``app.api.v1.projects`` runs
these against a live session and commits.
"""
from __future__ import annotations

from typing import Any


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def build_duplicate_title(original_title: str, *, suffix: str = " (copy)") -> str:
    """
    Build the new project title for a duplicate.

    Rules:
      * ``"My Idea"`` → ``"My Idea (copy)"``
      * ``"My Idea (copy)"`` → ``"My Idea (copy 2)"`` (increment, not stack)
      * ``"My Idea (copy 7)"`` → ``"My Idea (copy 8)"``
      * Truncates the original to keep the final title ≤ 500 chars.
    """
    title = _coerce_str(original_title).strip() or "Untitled Project"
    # Detect existing " (copy)" or " (copy N)" suffix.
    import re

    pattern = re.compile(r"^(.*?) \(copy(?: (\d+))?\)$")
    match = pattern.match(title)
    if match is None:
        base = title
        next_n = 1
    else:
        base = match.group(1)
        n_str = match.group(2)
        next_n = int(n_str) + 1 if n_str else 2

    suffix_text = f" (copy {next_n})" if next_n > 1 else " (copy)"
    candidate = f"{base}{suffix_text}"
    # Project title column is VARCHAR(500).
    if len(candidate) > 500:
        # Trim the base so the final string still fits.
        keep = 500 - len(suffix_text)
        base = base[: max(0, keep - 1)].rstrip()
        candidate = f"{base}{suffix_text}"
    return candidate


def duplicate_project_payload(
    project: dict[str, Any],
    environment: dict[str, Any] | None,
    *,
    new_title: str | None = None,
) -> dict[str, Any]:
    """
    Build the dict to feed into the new ``Project`` row.

    ``project`` and ``environment`` are dict-shaped views of the source
    rows. Caller is responsible for assigning the new user_id (must be
    the same owner — duplicate is owner-only) and committing.
    """
    resolved_title = (
        new_title.strip()
        if new_title and new_title.strip()
        else build_duplicate_title(project.get("title") or "")
    )
    new_project = {
        "title": resolved_title,
        "description": _coerce_str(project.get("description"), ""),
        "precis": project.get("precis"),
        "readings_json": project.get("readings_json"),
        "status": "DRAFT",
        "brief_completed_at": None,
        # Carry tags across — they're organisational metadata, not
        # run-state. Bad input that somehow snuck into the column is
        # silently filtered to strings; the column itself is JSONB
        # so we don't want to crash on a stray int/null either.
        "tags": [
            t for t in (project.get("tags") or [])
            if isinstance(t, str) and t
        ],
    }
    new_environment = None
    if environment is not None:
        new_environment = {
            "mode": _coerce_str(environment.get("mode"), "MANUAL"),
            "consumer_volume": int(environment.get("consumer_volume") or 10000),
            "growth_rate_per_month": float(environment.get("growth_rate_per_month") or 0.0),
            "average_order_value": float(environment.get("average_order_value") or 0.0),
            "price_sensitivity": float(environment.get("price_sensitivity") or 0.5),
            "market_maturity": float(environment.get("market_maturity") or 0.3),
            "scenario_type": environment.get("scenario_type"),
            "manual_params_json": environment.get("manual_params_json"),
            "trend_data_json": environment.get("trend_data_json"),
        }
    return {"project": new_project, "environment": new_environment}


__all__ = ["build_duplicate_title", "duplicate_project_payload"]