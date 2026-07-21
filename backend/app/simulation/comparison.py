"""
Pure helpers for the simulation comparison / A/B testing endpoint.

The route ``POST /api/v1/simulations/compare`` accepts 2–5 simulation IDs
from the same project, fetches their completed results, and returns a
structured side-by-side comparison with:
  * Overall summary (winner, spread, verdict)
  * Per-cluster conversion rate comparison table
  * Domain finding cross-comparison
  * Winner recommendation with rationale

Keeping this layer pure (no DB, no HTTP) makes the math verifiable in tests.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.schemas.simulation_comparison import (
    ClusterComparisonRow,
    ComparisonSimulationRef,
    ComparisonSummary,
    DomainFindingComparison,
    SimulationComparisonOut,
)

_SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "WARNING": 3,
    "HIGH": 3,
    "MEDIUM": 2,
    "INFO": 1,
    "LOW": 1,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_results_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json as _json

            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _label_for_index(idx: int) -> str:
    return chr(ord("A") + idx) if 0 <= idx < 26 else str(idx + 1)


def _cluster_rate(raw: Any) -> float:
    if isinstance(raw, dict):
        return max(
            0.0,
            min(
                1.0,
                _safe_float(raw.get("conversion_rate", raw.get("conversion"))),
            ),
        )
    return max(0.0, min(1.0, _safe_float(raw)))


def _finding_domain(finding: dict[str, Any]) -> str:
    return str(
        finding.get("architect_name")
        or finding.get("domain")
        or finding.get("primary_domain")
        or "Unknown"
    )


def _finding_severity(finding: dict[str, Any]) -> str:
    return str(finding.get("severity") or "INFO").upper()


def build_simulation_comparison(
    sim_rows: list[dict[str, Any]],
    cluster_registry: dict[str, dict[str, Any]] | None = None,
) -> SimulationComparisonOut:
    """
    Build a SimulationComparisonOut from a list of simulation DB rows.

    ``sim_rows`` must be sorted by the caller in the desired comparison order.
    Each row should contain at minimum:
        - id (int)
        - project_id (int)
        - status (str)
        - results_json (dict | str | None)
        - signal_quality (float | None)
        - created_at (datetime | str)
    """
    if len(sim_rows) < 2:
        raise ValueError("At least 2 simulations required for comparison")
    if len(sim_rows) > 5:
        raise ValueError("At most 5 simulations can be compared at once")

    comparison_id = str(uuid.uuid4())[:8]
    project_id = int(sim_rows[0].get("project_id", 0))

    parsed: list[dict[str, Any]] = []
    for row in sim_rows:
        results = _coerce_results_dict(row.get("results_json"))
        cluster_breakdown = results.get("cluster_breakdown", {}) or {}
        if not isinstance(cluster_breakdown, dict):
            cluster_breakdown = {}
        domain_findings = results.get("domain_findings", []) or []
        if not isinstance(domain_findings, list):
            domain_findings = []

        revenue_projection = results.get("revenue_projection")
        if revenue_projection is None:
            raw_funnel = results.get("raw_funnel", {})
            if isinstance(raw_funnel, dict):
                revenue_projection = raw_funnel.get("revenue_projection")

        parsed.append(
            {
                "simulation_id": int(row.get("id", 0)),
                "status": str(row.get("status", "UNKNOWN")).upper(),
                "conversion_rate": _safe_float(
                    results.get("population_weighted_conversion")
                    or results.get("conversion_rate")
                    or 0.0
                ),
                "revenue_projection": (
                    _safe_float(revenue_projection)
                    if revenue_projection is not None
                    else None
                ),
                "signal_quality": (
                    _safe_float(row.get("signal_quality"))
                    if row.get("signal_quality") is not None
                    else None
                ),
                "created_at": row.get("created_at"),
                "product_type_detected": str(
                    results.get("product_type_detected") or ""
                ),
                "cluster_breakdown": cluster_breakdown,
                "domain_findings": [f for f in domain_findings if isinstance(f, dict)],
                "primary_failure_domain": str(
                    results.get("primary_failure_domain") or "unknown"
                ),
            }
        )

    sim_refs: list[ComparisonSimulationRef] = []
    for p in parsed:
        created_at = p["created_at"]
        if hasattr(created_at, "isoformat"):
            created_at_str = created_at.isoformat()
        else:
            created_at_str = (
                str(created_at)
                if created_at
                else datetime.now(timezone.utc).isoformat()
            )

        sim_refs.append(
            ComparisonSimulationRef(
                simulation_id=p["simulation_id"],
                status=p["status"],
                conversion_rate=round(p["conversion_rate"], 4),
                revenue_projection=(
                    round(p["revenue_projection"], 2)
                    if p["revenue_projection"] is not None
                    else None
                ),
                created_at=created_at_str,
                signal_quality=(
                    round(p["signal_quality"], 4)
                    if p["signal_quality"] is not None
                    else None
                ),
                product_type_detected=p["product_type_detected"],
            )
        )

    completed = [p for p in parsed if p["status"] == "COMPLETED"]
    pool = completed if completed else parsed
    best = max(pool, key=lambda x: x["conversion_rate"])
    worst = min(pool, key=lambda x: x["conversion_rate"])

    if not completed:
        verdict = "INCOMPLETE_DATA"
    elif len(completed) < len(parsed):
        verdict = "PARTIAL_COMPLETION"
    else:
        verdict = _determine_verdict(completed)

    best_idx = next(
        i for i, p in enumerate(parsed) if p["simulation_id"] == best["simulation_id"]
    )
    best_cr = best["conversion_rate"]
    worst_cr = worst["conversion_rate"]
    conversion_spread = (
        round(((best_cr - worst_cr) / max(worst_cr, 0.0001)) * 100, 2)
        if worst_cr > 0
        else (0.0 if best_cr == 0 else 100.0)
    )

    best_rev = best["revenue_projection"]
    worst_rev = worst["revenue_projection"]
    revenue_spread: float | None = None
    if best_rev is not None and worst_rev is not None and worst_rev > 0:
        revenue_spread = round(((best_rev - worst_rev) / worst_rev) * 100, 2)

    summary = ComparisonSummary(
        best_simulation_id=best["simulation_id"],
        best_conversion_rate=round(best_cr, 4),
        worst_simulation_id=worst["simulation_id"],
        worst_conversion_rate=round(worst_cr, 4),
        conversion_spread_pct=conversion_spread,
        revenue_spread_pct=revenue_spread,
        winner_label=_label_for_index(best_idx),
        verdict=verdict,
    )

    cluster_comparison = _build_cluster_comparison(parsed, cluster_registry)
    domain_comparison = _build_domain_comparison(parsed)

    metadata = {
        "total_simulations_compared": len(parsed),
        "completed_count": len(completed),
        "product_types": sorted(
            {
                p["product_type_detected"]
                for p in parsed
                if p["product_type_detected"]
            }
        ),
        "primary_failure_domains": sorted(
            {
                p["primary_failure_domain"]
                for p in parsed
                if p["primary_failure_domain"]
            }
        ),
    }

    return SimulationComparisonOut(
        project_id=project_id,
        comparison_id=comparison_id,
        simulations=sim_refs,
        summary=summary,
        cluster_comparison=cluster_comparison,
        domain_finding_comparison=domain_comparison,
        metadata=metadata,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _determine_verdict(completed: list[dict[str, Any]]) -> str:
    if len(completed) < 2:
        return "INSUFFICIENT_DATA"

    rates = [c["conversion_rate"] for c in completed]
    best = max(rates)
    worst = min(rates)
    sorted_rates = sorted(rates, reverse=True)

    if len(sorted_rates) >= 2 and sorted_rates[0] > 0:
        relative_gap = (sorted_rates[0] - sorted_rates[1]) / sorted_rates[0]
        if relative_gap > 0.20:
            return "CLEAR_WINNER"

    # Mixed-by-cluster before close-race: diverging per-cluster winners are
    # more actionable than a near-tie headline conversion.
    winners: set[int] = set()
    all_ids: set[str] = set()
    for c in completed:
        all_ids.update(str(k) for k in c["cluster_breakdown"].keys())
    for cid in all_ids:
        rates_by_sim: dict[int, float] = {}
        for c in completed:
            raw = None
            for k, v in c["cluster_breakdown"].items():
                if str(k) == cid:
                    raw = v
                    break
            rates_by_sim[c["simulation_id"]] = _cluster_rate(raw)
        if rates_by_sim:
            winners.add(max(rates_by_sim.items(), key=lambda kv: kv[1])[0])
    if len(winners) > 1:
        return "MIXED_BY_CLUSTER"

    if worst > 0 and ((best - worst) / worst) < 0.10:
        return "CLOSE_RACE"

    return "CLEAR_WINNER" if best > worst else "CLOSE_RACE"


def _build_cluster_comparison(
    parsed: list[dict[str, Any]],
    cluster_registry: dict[str, dict[str, Any]] | None,
) -> list[ClusterComparisonRow]:
    all_cluster_ids: set[str] = set()
    for p in parsed:
        all_cluster_ids.update(str(k) for k in p["cluster_breakdown"].keys())

    if cluster_registry is None:
        n = max(1, len(all_cluster_ids))
        cluster_registry = {
            cid: {"name": cid, "population_weight": 1.0 / n} for cid in all_cluster_ids
        }

    rows: list[ClusterComparisonRow] = []
    for cid in sorted(all_cluster_ids):
        conversions: dict[int, float] = {}
        for p in parsed:
            raw = p["cluster_breakdown"].get(cid, p["cluster_breakdown"].get(cid))
            # Also try original key if cid was str-coerced.
            if raw is None and cid in p["cluster_breakdown"]:
                raw = p["cluster_breakdown"][cid]
            if raw is None:
                # Attempt non-str key lookup from original breakdown.
                for k, v in p["cluster_breakdown"].items():
                    if str(k) == cid:
                        raw = v
                        break
            conversions[p["simulation_id"]] = round(_cluster_rate(raw), 4)

        if not conversions:
            continue

        best_sim_id = max(conversions.items(), key=lambda kv: kv[1])[0]
        best_rate = conversions[best_sim_id]
        delta_from_best = {
            sim_id: round(rate - best_rate, 4) for sim_id, rate in conversions.items()
        }
        winner_idx = next(
            i for i, p in enumerate(parsed) if p["simulation_id"] == best_sim_id
        )
        registry_info = cluster_registry.get(cid, {})
        rows.append(
            ClusterComparisonRow(
                cluster_id=cid,
                cluster_name=str(registry_info.get("name", cid)),
                population_weight=_safe_float(registry_info.get("population_weight")),
                conversions=conversions,
                delta_from_best=delta_from_best,
                best_simulation_id=best_sim_id,
                winner_label=_label_for_index(winner_idx),
            )
        )

    rows.sort(key=lambda r: (-r.population_weight, r.cluster_id))
    return rows


def _build_domain_comparison(
    parsed: list[dict[str, Any]],
) -> list[DomainFindingComparison]:
    all_domains: set[str] = set()
    domain_findings_by_sim: dict[int, dict[str, list[dict[str, Any]]]] = {}

    for p in parsed:
        sim_id = p["simulation_id"]
        domain_findings_by_sim[sim_id] = {}
        for finding in p["domain_findings"]:
            domain = _finding_domain(finding)
            all_domains.add(domain)
            domain_findings_by_sim[sim_id].setdefault(domain, []).append(finding)

    rows: list[DomainFindingComparison] = []
    for domain in sorted(all_domains):
        findings_by_sim: dict[int, list[dict[str, Any]]] = {}
        severity_by_sim: dict[int, str | None] = {}

        for p in parsed:
            sim_id = p["simulation_id"]
            findings = domain_findings_by_sim[sim_id].get(domain, [])
            findings_by_sim[sim_id] = findings
            if findings:
                top = max(
                    findings,
                    key=lambda f: _SEVERITY_RANK.get(_finding_severity(f), 0),
                )
                severity_by_sim[sim_id] = _finding_severity(top)
            else:
                severity_by_sim[sim_id] = None

        non_none = [s for s in severity_by_sim.values() if s is not None]
        if not non_none:
            consensus = "NO_FINDINGS"
        elif len(set(non_none)) == 1 and len(non_none) == len(parsed):
            consensus = "ALL_AGREE"
        elif len(non_none) == 1:
            consensus = "SINGLE_SIM_ONLY"
        else:
            consensus = "MIXED"

        rows.append(
            DomainFindingComparison(
                domain=domain,
                findings=findings_by_sim,
                severity_by_sim=severity_by_sim,
                consensus=consensus,
                recommendation=_domain_recommendation(
                    domain, severity_by_sim, consensus
                ),
            )
        )

    return rows


def _domain_recommendation(
    domain: str,
    severity_by_sim: dict[int, str | None],
    consensus: str,
) -> str:
    if consensus == "NO_FINDINGS":
        return f"No {domain} findings in any simulation."

    if consensus == "ALL_AGREE":
        sev = next(s for s in severity_by_sim.values() if s is not None)
        if sev in ("CRITICAL", "WARNING", "HIGH"):
            return (
                f"All simulations flag {domain} as {sev}. "
                f"Prioritize {domain} improvements across all variants."
            )
        return f"{domain} consistently rated {sev}. Monitor but not a primary blocker."

    if consensus == "SINGLE_SIM_ONLY":
        sim_id = next(s for s, v in severity_by_sim.items() if v is not None)
        sev = severity_by_sim[sim_id]
        return (
            f"Only simulation {sim_id} flags {domain} ({sev}). "
            f"Investigate if this variant has unique {domain} exposure."
        )

    critical_sims = [s for s, v in severity_by_sim.items() if v == "CRITICAL"]
    warning_sims = [
        s for s, v in severity_by_sim.items() if v in {"WARNING", "HIGH"}
    ]
    if critical_sims:
        return (
            f"{domain} is CRITICAL in simulations {critical_sims}. "
            "Focus remediation on those variants."
        )
    if warning_sims:
        return (
            f"{domain} is elevated in simulations {warning_sims}. "
            "Target improvements there."
        )
    return (
        f"{domain} severity varies across simulations. "
        f"Compare variant assumptions driving {domain} differences."
    )


__all__ = ["build_simulation_comparison"]
