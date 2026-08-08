"""
Pure helpers for the findings-trend endpoint.

Siblings to cluster_trend and architect_bias_trend: takes a
sequence of ``(created_at, findings)`` rows and bins the
per-sim severity counts by day / week / month. Lets the
dashboard render "CRITICAL findings peaked at 12 on day X ·
trending DOWN −40 % week-over-week" alongside the bias trend.

``min_severity`` filters which findings are counted (the same
allowlist the findings_aggregate helper uses). The result
includes the unfiltered total finding count too so the
dashboard can show "X CRITICAL · Y WARNING · Z INFO" at a
glance.

Pure-Python (no SQL, no I/O) — the route layer pulls the
results_json + created_at per sim before invoking.
"""
from __future__ import annotations

from datetime import UTC, datetime

# Reuse the bin constants from cluster_trend so the
# dashboard's wording stays consistent.
from app.simulation.cluster_trend import (
    BIN_DAY,
    BIN_WEEK,
    _bin_key,
    _bin_sort_key,
    normalise_bin,
)

# Severity allowlist — same as findings_aggregate so the
# surface doesn't silently expand.
VALID_SEVERITIES: frozenset[str] = frozenset(
    {"CRITICAL", "WARNING", "INFO"}
)
DEFAULT_MIN_SEVERITY: str = "INFO"

# Severity ordering — higher rank = more severe.
_SEVERITY_RANK: dict[str, int] = {
    "INFO": 1,
    "WARNING": 2,
    "CRITICAL": 3,
}

# Direction labels for the overall CRITICAL count trend.
LABEL_IMPROVING: str = "IMPROVING"  # fewer CRITICALs over time
LABEL_DEGRADING: str = "DEGRADING"  # more CRITICALs over time
LABEL_STABLE: str = "STABLE"
LABEL_UNKNOWN: str = "UNKNOWN"
VALID_DIRECTIONS: frozenset[str] = frozenset({
    LABEL_IMPROVING,
    LABEL_DEGRADING,
    LABEL_STABLE,
    LABEL_UNKNOWN,
})


def normalise_severity(raw: str | None) -> str:
    """Coerce min_severity query param into a valid severity.

    Empty / None → default ``INFO``. Unknown raises so a
    typo doesn't silently downgrade the filter.
    """
    if raw is None:
        return DEFAULT_MIN_SEVERITY
    candidate = (raw or "").strip().upper()
    if not candidate:
        return DEFAULT_MIN_SEVERITY
    if candidate not in VALID_SEVERITIES:
        allowed = ", ".join(sorted(VALID_SEVERITIES))
        raise ValueError(
            f"invalid severity {raw!r}; allowed: {allowed}"
        )
    return candidate


def severity_meets_min(severity: str, min_severity: str) -> bool:
    """Return True if ``severity`` is at or above ``min_severity``."""
    return _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK.get(
        min_severity, 0
    )


def _direction(
    first_critical: int, last_critical: int
) -> str:
    """Bucket CRITICAL-count delta into a trend label.

    For findings, IMPROVING means fewer CRITICALs over time.
    """
    if first_critical == 0 and last_critical == 0:
        return LABEL_STABLE
    delta = last_critical - first_critical
    if delta < 0:
        return LABEL_IMPROVING
    if delta > 0:
        return LABEL_DEGRADING
    return LABEL_STABLE


def build_findings_trend(
    rows: list[tuple[object, list[dict] | None]],
    *,
    min_severity: str = DEFAULT_MIN_SEVERITY,
    bin_size: str = BIN_DAY,
) -> dict:
    """Build the findings-trend payload.

    Args:
        rows: list of ``(created_at, findings)`` tuples.
            ``created_at`` may be a datetime or ISO 8601 string.
            ``findings`` is the list of finding dicts from the
            sim's ``domain_findings`` (or None when missing).
        min_severity: only count findings at or above this
            severity (default INFO). Buckets still show the
            full breakdown so the dashboard can render "X
            CRITICAL · Y WARNING · Z INFO".
        bin_size: ``BIN_DAY`` (default) / ``BIN_WEEK`` /
            ``BIN_MONTH``.

    Returns:
        A dict matching :class:`FindingsTrendOut`:

        * ``bin_size`` / ``min_severity`` — echoed.
        * ``bins`` — per-bin dict sorted chronologically.
          Each row: ``bin``, ``bin_start`` (ISO 8601 UTC),
          ``critical_count``, ``warning_count``,
          ``info_count``, ``finding_count`` (total),
          ``sim_count``.
        * ``overall_direction`` — IMPROVING / DEGRADING /
          STABLE / UNKNOWN bucketed from first vs last
          bin's CRITICAL count.
        * ``first_bin_critical`` /
          ``last_bin_critical`` — for the dashboard's
          headline.
        * ``mean_delta_critical`` — last − first, or None
          when fewer than 2 bins have data.
        * ``peak_critical_bin`` — the bin with the highest
          CRITICAL count (tiebreaker: latest bin_start).
          None when no bins have data.
    """
    effective_bin = normalise_bin(bin_size)
    effective_severity = normalise_severity(min_severity)

    bins: dict[str, dict] = {}
    for created_at, findings in rows:
        if isinstance(created_at, datetime):
            dt = created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
        elif isinstance(created_at, str):
            candidate = created_at.strip()
            if not candidate:
                continue
            if candidate.endswith("Z"):
                candidate = candidate[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
        else:
            continue
        # Defensive — accept only iterables of findings (a
        # string or None would otherwise pollute the bins).
        if not isinstance(findings, list) or not findings:
            continue

        # Bin-start timestamp.
        if effective_bin == BIN_DAY:
            ts = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif effective_bin == BIN_WEEK:
            iso_weekday = dt.isoweekday()
            ts = (
                dt - _timedelta(days=iso_weekday - 1)
            ).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            ts = dt.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0,
            )
        key = _bin_key(dt, effective_bin)
        slot = bins.setdefault(
            key,
            {
                "bin": key,
                "bin_start": ts.isoformat(),
                "critical_count": 0,
                "warning_count": 0,
                "info_count": 0,
                "_sim_ids": set(),
            },
        )
        slot["_sim_ids"].add(id(findings))

        # Count findings by severity. min_severity is the
        # floor — findings below it (or with unknown severity
        # strings) are skipped entirely so the per-bin counts
        # reflect the filtered subset.
        for f in findings:
            if not isinstance(f, dict):
                continue
            severity = str(
                f.get("severity", "INFO")
            ).upper()
            # Skip findings whose severity isn't in the
            # allowlist — counting an unknown severity as INFO
            # would silently inflate the buckets.
            if severity not in {"CRITICAL", "WARNING", "INFO"}:
                continue
            if not severity_meets_min(severity, effective_severity):
                continue
            if severity == "CRITICAL":
                slot["critical_count"] += 1
            elif severity == "WARNING":
                slot["warning_count"] += 1
            else:
                slot["info_count"] += 1

    rows_out: list[dict] = []
    for key in sorted(
        bins.keys(), key=lambda k: _bin_sort_key(k, effective_bin)
    ):
        slot = bins[key]
        total = (
            slot["critical_count"]
            + slot["warning_count"]
            + slot["info_count"]
        )
        rows_out.append({
            "bin": key,
            "bin_start": slot["bin_start"],
            "critical_count": slot["critical_count"],
            "warning_count": slot["warning_count"],
            "info_count": slot["info_count"],
            "finding_count": total,
            "sim_count": len(slot["_sim_ids"]),
        })

    # Empty input → UNKNOWN so the dashboard doesn't see
    # misleading "STABLE" with 0/0 criticals.
    if not rows_out:
        return {
            "bin_size": effective_bin,
            "min_severity": effective_severity,
            "bins": [],
            "overall_direction": LABEL_UNKNOWN,
            "first_bin_critical": 0,
            "last_bin_critical": 0,
            "mean_delta_critical": None,
            "peak_critical_bin": None,
            "critical_finding_distribution": {
                "zero": 0, "low": 0, "moderate": 0, "high": 0,
            },
            "total_finding_count": 0,
            "total_critical_count": 0,
            "total_warning_count": 0,
            "total_info_count": 0,
        }

    # Direction from first vs last bin's CRITICAL count.
    if len(rows_out) < 2:
        mean_delta = None
    else:
        mean_delta = (
            rows_out[-1]["critical_count"]
            - rows_out[0]["critical_count"]
        )
    first_critical = rows_out[0]["critical_count"]
    last_critical = rows_out[-1]["critical_count"]

    # Peak critical bin — bin with the highest CRITICAL count
    # (tiebreaker: latest bin_start for stability).
    peak_payload: dict | None = None
    if rows_out:
        peak_row = max(
            rows_out,
            key=lambda r: (
                r["critical_count"],
                r["bin_start"],
            ),
        )
        if peak_row["critical_count"] > 0:
            peak_payload = {
                "bin": peak_row["bin"],
                "bin_start": peak_row["bin_start"],
                "critical_count": peak_row["critical_count"],
            }

    # Critical finding distribution — bucket each bin's
    # critical_count into zero / low (1-2) / moderate (3-5) /
    # high (6+) so the dashboard can render "5 bins had no
    # criticals · 2 bins had 1-2 · 1 bin had 6+" without
    # iterating.
    critical_distribution = {"zero": 0, "low": 0, "moderate": 0, "high": 0}
    for r in rows_out:
        c = r["critical_count"]
        if c == 0:
            critical_distribution["zero"] += 1
        elif c <= 2:
            critical_distribution["low"] += 1
        elif c <= 5:
            critical_distribution["moderate"] += 1
        else:
            critical_distribution["high"] += 1

    total_critical = sum(r["critical_count"] for r in rows_out)
    total_warning = sum(r["warning_count"] for r in rows_out)
    total_info = sum(r["info_count"] for r in rows_out)
    total_finding = total_critical + total_warning + total_info

    return {
        "bin_size": effective_bin,
        "min_severity": effective_severity,
        "bins": rows_out,
        "overall_direction": _direction(first_critical, last_critical),
        "first_bin_critical": first_critical,
        "last_bin_critical": last_critical,
        "mean_delta_critical": mean_delta,
        "peak_critical_bin": peak_payload,
        "critical_finding_distribution": critical_distribution,
        "total_finding_count": total_finding,
        "total_critical_count": total_critical,
        "total_warning_count": total_warning,
        "total_info_count": total_info,
    }


def _timedelta(**kwargs):
    from datetime import timedelta
    return timedelta(**kwargs)


__all__ = [
    "VALID_SEVERITIES",
    "DEFAULT_MIN_SEVERITY",
    "LABEL_IMPROVING",
    "LABEL_DEGRADING",
    "LABEL_STABLE",
    "LABEL_UNKNOWN",
    "VALID_DIRECTIONS",
    "normalise_severity",
    "severity_meets_min",
    "build_findings_trend",
]
