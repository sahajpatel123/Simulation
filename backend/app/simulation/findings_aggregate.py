"""
Pure helpers for the cross-simulation findings aggregate endpoint.

The aggregate surfaces the *most common* failure domains across the
user's selected simulations — a portfolio view that lets a founder
see "across my 12 simulations, the Pricing architect has flagged
critical issues 7 times" without iterating each simulation.

The aggregation is intentionally simple:

* severity counts across all findings (CRITICAL / WARNING / INFO)
* per-architect counts, sorted by finding_count DESC
* per-architect critical counts (the call-to-action)
* top N (default 5) architect names by critical count
* "shared" domain names — those that appear in >= half of the
  supplied simulations, i.e. the systemic failures
* per-cluster rollup (NEW) — which user segments are most affected
* top N findings by conversion_impact (NEW) — the actual
  "show me the worst thing" payload
* optional architect filter (NEW) — drill into one architect

The route layer applies the user's ``min_severity`` filter (default
``INFO``) so the dashboard can drill into "only show me critical
findings across these sims".

The aggregate is built in Python (not SQL) because the dataset per
request is bounded by the batch cap (100 sims) and the per-sim
findings list is small (<100 entries). A single Python pass is
faster than orchestrating a server-side aggregation query.
"""
from __future__ import annotations

from collections import defaultdict

# Allowlist of severities this endpoint accepts. Mirrors the
# accountability validation set so we don't silently expand the
# surface when the engine adds a new severity.
VALID_SEVERITIES: frozenset[str] = frozenset(
    {"CRITICAL", "WARNING", "INFO"}
)
DEFAULT_MIN_SEVERITY: str = "INFO"

# Severity ordering — higher rank = more severe. Used so the
# "min_severity" filter is monotonic: ``min_severity=CRITICAL``
# returns only CRITICAL findings, ``min_severity=WARNING`` returns
# CRITICAL + WARNING, etc.
_SEVERITY_RANK: dict[str, int] = {
    "INFO": 1,
    "WARNING": 2,
    "CRITICAL": 3,
}

DEFAULT_TOP_N: int = 5
MAX_TOP_N: int = 100
MAX_ARCHITECT_NAME_LEN: int = 64


def _normalise_severity(raw: str | None) -> str:
    """Return a valid severity or the default.

    Anything outside the allowlist raises ``ValueError`` so a typo
    (e.g. ``?min_severity=crit``) doesn't silently downgrade the
    filter and hide critical findings.
    """
    if raw is None:
        return DEFAULT_MIN_SEVERITY
    candidate = raw.strip().upper()
    if not candidate:
        return DEFAULT_MIN_SEVERITY
    if candidate not in VALID_SEVERITIES:
        allowed = ", ".join(sorted(VALID_SEVERITIES))
        raise ValueError(f"invalid severity {raw!r}; allowed: {allowed}")
    return candidate


def _normalise_architect_filter(raw: str | None) -> str | None:
    """Return a lowercase architect name to filter by, or None.

    Whitespace is stripped; empty / None inputs return ``None``
    (no filter). Length is capped so a giant blob can't be smuggled
    into the slow Python path. The case-fold happens **after** the
    strip so the comparison is case-insensitive without storing a
    massive normalised copy in the caller's payload.
    """
    if raw is None:
        return None
    candidate = raw.strip().casefold()
    if not candidate:
        return None
    if len(candidate) > MAX_ARCHITECT_NAME_LEN:
        raise ValueError(
            f"architect filter exceeds {MAX_ARCHITECT_NAME_LEN} chars"
        )
    return candidate


def severity_meets_min(severity: str, min_severity: str) -> bool:
    """Return True if ``severity`` is at or above ``min_severity``."""
    return _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK.get(
        min_severity, 0
    )


def normalise_severity(raw: str | None) -> str:
    """Public wrapper around ``_normalise_severity`` for tests."""
    return _normalise_severity(raw)


def normalise_architect_filter(raw: str | None) -> str | None:
    """Public wrapper around ``_normalise_architect_filter``."""
    return _normalise_architect_filter(raw)


def normalise_top_n(raw: int | None) -> int:
    """Public wrapper around ``_normalise_top_n``."""
    return _normalise_top_n(raw)


def _extract_findings(sim_results: object) -> list[dict]:
    """Pull a list of finding dicts out of a simulation's results_json.

    The persisted shape varies slightly across versions:

    * ``results_json.domain_findings`` — the canonical list.
    * ``results_json.findings`` — older versions.
    * ``results_json`` is itself a list — older "findings" style.

    Anything we can't parse becomes an empty list so the aggregate
    doesn't crash on a stale row.
    """
    if sim_results is None:
        return []
    if isinstance(sim_results, list):
        return [f for f in sim_results if isinstance(f, dict)]
    if not isinstance(sim_results, dict):
        return []
    for key in ("domain_findings", "findings"):
        value = sim_results.get(key)
        if isinstance(value, list):
            return [f for f in value if isinstance(f, dict)]
    return []


def _safe_impact(raw: object) -> float:
    """Coerce a finding's ``conversion_impact`` to a float, defaulting
    to 0.0 on missing or non-numeric input. Used for top-findings
    sorting so a stray null / string can't crash the aggregate."""
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def aggregate_findings(
    simulation_results: list[dict],
    *,
    min_severity: str = DEFAULT_MIN_SEVERITY,
    top_n: int = DEFAULT_TOP_N,
    architect: str | None = None,
) -> dict:
    """Aggregate findings across N simulations.

    Args:
        simulation_results: list of ``results_json`` payloads (one per
            simulation). Each is a dict — defensive for our persisted
            shape variants.
        min_severity: filter the finding list to findings at or above
            this severity. The ``severity_breakdown`` always counts
            *all* findings so the dashboard can show the full
            distribution; only the per-architect rollup is filtered.
        top_n: how many top architects to return in the rollup, and
            how many ``top_findings`` (by conversion_impact) to surface.
        architect: optional case-insensitive architect name; only
            findings from this architect feed the per-architect /
            per-cluster / top-findings rollups. ``severity_breakdown``
            and ``total_findings`` still reflect *all* findings so
            the dashboard can show "Pricing: 7 of 42 critical".

    Returns:
        A dict matching the ``FindingsAggregateOut`` schema:

        * ``total_findings`` — count of all findings (regardless of
          filter) so the UI can render the "X of Y critical" badge.
        * ``filtered_findings`` — count of findings passing the
          ``min_severity`` filter.
        * ``severity_breakdown`` — ``{CRITICAL/WARNING/INFO: count}``
          across all findings.
        * ``by_architect`` — sorted by filtered count DESC, then
          critical count DESC, then name ASC. Each row carries
          ``severity_breakdown`` for the filtered slice.
        * ``by_cluster`` — per-cluster rollup (cluster_id, name,
          finding_count, total_impact, severity_breakdown).
        * ``top_architects`` — first ``top_n`` entries (by name) for
          the dashboard's "top failure domains" widget.
        * ``top_findings`` — top ``top_n`` findings by conversion_impact.
        * ``simulation_count`` — how many simulations contributed.
        * ``simulations_with_findings`` — how many simulations had
          at least one finding in the filtered set.
        * ``shared_domain_count`` — number of architect names that
          appear as the top failure domain in >= half of the sims.
        * ``architect_filter`` — echoed back (lowercased) so the UI
          can show "filtering by: pricing".
    """
    if not simulation_results:
        return {
            "total_findings": 0,
            "filtered_findings": 0,
            "severity_breakdown": {},
            "by_architect": [],
            "by_cluster": [],
            "top_architects": [],
            "top_findings": [],
            "simulation_count": 0,
            "simulations_with_findings": 0,
            "shared_domain_count": 0,
            "architect_filter": architect,
        }

    # Global severity counts (unfiltered) so the dashboard can render
    # "10 critical of 50 total findings" cleanly.
    severity_breakdown: dict[str, int] = defaultdict(int)
    total_findings = 0
    filtered_findings = 0
    sims_with_findings = 0

    # Per-architect accumulators (filtered).
    per_architect: dict[str, dict] = {}
    # Per-cluster accumulators (filtered).
    per_cluster: dict[str, dict] = {}
    # Per-sim top-architect tracker for "shared domain" detection.
    per_sim_top_architect: list[str] = []
    # Top-findings heap (sorted later by conversion_impact DESC).
    top_findings: list[dict] = []

    architect_filter = (
        architect.casefold() if architect else None
    )

    for sim_results in simulation_results:
        raw_findings = _extract_findings(sim_results)
        if not raw_findings:
            continue
        sims_with_findings += 1
        # Track the highest-severity architect for this sim only
        # (so the "shared domain" count reflects actual problem
        # ownership, not noise).
        best_arch: tuple[tuple[int, int], str] | None = None
        for f in raw_findings:
            severity = str(f.get("severity", "INFO")).upper()
            arch = str(f.get("architect_name", "unknown"))
            arch_cf = arch.casefold()
            cluster_id = str(f.get("cluster_id", "unknown"))
            cluster_name = str(
                f.get("cluster_name", cluster_id)
            )
            total_findings += 1
            severity_breakdown[severity] += 1
            if not severity_meets_min(severity, min_severity):
                continue
            # Architect filter narrows the per-architect / per-cluster
            # / top-findings rollups but never affects the global
            # severity_breakdown (computed above the filter).
            if architect_filter is not None and arch_cf != architect_filter:
                continue
            filtered_findings += 1
            impact = _safe_impact(f.get("conversion_impact"))

            slot = per_architect.setdefault(
                arch,
                {
                    "architect_name": arch,
                    "finding_count": 0,
                    "critical_count": 0,
                    "warning_count": 0,
                    "info_count": 0,
                    "total_conversion_impact": 0.0,
                    "severity_breakdown": {
                        "CRITICAL": 0,
                        "WARNING": 0,
                        "INFO": 0,
                    },
                },
            )
            slot["finding_count"] += 1
            slot["severity_breakdown"][severity] += 1
            if severity == "CRITICAL":
                slot["critical_count"] += 1
            elif severity == "WARNING":
                slot["warning_count"] += 1
            else:
                slot["info_count"] += 1
            slot["total_conversion_impact"] += impact

            cluster_slot = per_cluster.setdefault(
                cluster_id,
                {
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                    "finding_count": 0,
                    "critical_count": 0,
                    "warning_count": 0,
                    "info_count": 0,
                    "total_conversion_impact": 0.0,
                    "severity_breakdown": {
                        "CRITICAL": 0,
                        "WARNING": 0,
                        "INFO": 0,
                    },
                },
            )
            cluster_slot["finding_count"] += 1
            cluster_slot["severity_breakdown"][severity] += 1
            if severity == "CRITICAL":
                cluster_slot["critical_count"] += 1
            elif severity == "WARNING":
                cluster_slot["warning_count"] += 1
            else:
                cluster_slot["info_count"] += 1
            cluster_slot["total_conversion_impact"] += impact

            # Track (severity_rank, filtered_count) ranking for the
            # per-sim top architect.
            rank = -_SEVERITY_RANK.get(severity, 0)
            if best_arch is None or (rank, -slot["finding_count"]) > best_arch[0]:
                best_arch = ((rank, -slot["finding_count"]), arch)

            # Top findings: pass-through the raw dict so the UI can
            # render the full row (architect_name, cluster_name, etc).
            top_findings.append({
                "architect_name": arch,
                "cluster_id": cluster_id,
                "cluster_name": cluster_name,
                "severity": severity,
                "finding": str(f.get("finding", "")),
                "metric_affected": str(f.get("metric_affected", "")),
                "recommended_action": str(f.get("recommended_action", "")),
                "conversion_impact": impact,
            })
        if best_arch is not None:
            per_sim_top_architect.append(best_arch[1])

    by_architect = sorted(
        per_architect.values(),
        key=lambda row: (
            -row["finding_count"],
            -row["critical_count"],
            row["architect_name"],
        ),
    )
    by_cluster = sorted(
        per_cluster.values(),
        key=lambda row: (
            -row["finding_count"],
            -row["critical_count"],
            row["cluster_id"],
        ),
    )
    top_architects = [
        row["architect_name"]
        for row in by_architect[: max(0, top_n)]
    ]
    # Top findings: sort by conversion_impact DESC, then severity DESC
    # (tiebreaker), then architect + cluster (stable).
    top_findings.sort(
        key=lambda f: (
            -_safe_impact(f["conversion_impact"]),
            -_SEVERITY_RANK.get(f["severity"], 0),
            f["architect_name"],
            f["cluster_id"],
        )
    )
    top_findings_capped = top_findings[: max(0, top_n)]

    # Shared domains: those that topped at least half of the sims
    # that had any findings. Round *up* so a single-sim call still
    # has a sensible denominator.
    shared_count = 0
    if per_sim_top_architect:
        threshold = max(1, (len(per_sim_top_architect) + 1) // 2)
        counts: dict[str, int] = defaultdict(int)
        for arch in per_sim_top_architect:
            counts[arch] += 1
        shared_count = sum(1 for c in counts.values() if c >= threshold)

    return {
        "total_findings": total_findings,
        "filtered_findings": filtered_findings,
        "severity_breakdown": dict(severity_breakdown),
        "by_architect": by_architect,
        "by_cluster": by_cluster,
        "top_architects": top_architects,
        "top_findings": top_findings_capped,
        "simulation_count": len(simulation_results),
        "simulations_with_findings": sims_with_findings,
        "shared_domain_count": shared_count,
        "architect_filter": architect,
    }


def _normalise_top_n(raw: int | None) -> int:
    """Coerce ``top_n`` into [1, MAX_TOP_N], default DEFAULT_TOP_N."""
    if raw is None:
        return DEFAULT_TOP_N
    if raw < 1:
        return 1
    if raw > MAX_TOP_N:
        return MAX_TOP_N
    return raw


__all__ = [
    "VALID_SEVERITIES",
    "DEFAULT_MIN_SEVERITY",
    "DEFAULT_TOP_N",
    "MAX_TOP_N",
    "MAX_ARCHITECT_NAME_LEN",
    "normalise_severity",
    "normalise_architect_filter",
    "normalise_top_n",
    "severity_meets_min",
    "aggregate_findings",
]