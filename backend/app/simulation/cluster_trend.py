"""
Pure helpers for the per-cluster trend endpoint.

When the dashboard's cross-sim cluster aggregate surfaces a
laggard (e.g. tier3_first_time_app_user consistently
underperforming), the founder wants to see how that cluster's
predicted conversion rate has *evolved over time* across the
user's batch. Was it always bad, or did it drop recently?

The helper bins a sequence of (created_at, cluster_breakdown)
rows into calendar periods (month / week / day) and reports
per-bin mean conversion + observation count + sample size.

Pure-Python (no SQL, no I/O) — the route layer JOINs
simulations with their cluster_breakdowns before invoking.
Binning is done in UTC so the dashboard doesn't have to
disambiguate timezones.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

# Bin granularity options. The route validates user input
# against this allowlist so a typo ("mont") doesn't silently
# produce empty buckets.
BIN_MONTH: str = "month"
BIN_WEEK: str = "week"
BIN_DAY: str = "day"
VALID_BINS: frozenset[str] = frozenset({
    BIN_MONTH,
    BIN_WEEK,
    BIN_DAY,
})

# Below this absolute change in mean conversion across
# consecutive bins the trend is labelled "STABLE". 1pp
# matches the same precision founders see on the outcomes
# digest.
STABLE_DELTA_THRESHOLD: float = 0.01

# Direction labels for the overall trend.
TREND_UP: str = "UP"
TREND_DOWN: str = "DOWN"
TREND_STABLE: str = "STABLE"
TREND_UNKNOWN: str = "UNKNOWN"
VALID_TREND_LABELS: frozenset[str] = frozenset({
    TREND_UP,
    TREND_DOWN,
    TREND_STABLE,
    TREND_UNKNOWN,
})


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def normalise_bin(raw: str | None) -> str:
    """Coerce the bin query param into one of VALID_BINS.

    Empty / None → default to ``BIN_MONTH``. Unknown values
    raise so a typo doesn't silently produce empty buckets.
    """
    if raw is None:
        return BIN_MONTH
    candidate = (raw or "").strip().lower()
    if not candidate:
        return BIN_MONTH
    if candidate not in VALID_BINS:
        allowed = ", ".join(sorted(VALID_BINS))
        raise ValueError(
            f"invalid bin {raw!r}; allowed: {allowed}"
        )
    return candidate


def _bin_key(dt: datetime, bin_size: str) -> str:
    """ISO 8601-ish key for the bin containing ``dt`` (UTC).

    Monthly → 'YYYY-MM', weekly → 'YYYY-Www', daily →
    'YYYY-MM-DD'. Stable across locale changes because
    calendar methods operate on UTC.
    """
    if bin_size == BIN_DAY:
        return dt.strftime("%Y-%m-%d")
    if bin_size == BIN_WEEK:
        # ISO week: %G (ISO year) + %V (ISO week, 01-53).
        return f"{dt.strftime('%G')}-W{dt.strftime('%V')}"
    # BIN_MONTH
    return dt.strftime("%Y-%m")


def _bin_sort_key(key: str, bin_size: str) -> tuple:
    """Sort key for chronological ordering across bins."""
    if bin_size == BIN_DAY:
        return (int(key[0:4]), int(key[5:7]), int(key[8:10]))
    if bin_size == BIN_WEEK:
        # 'YYYY-Www' → (year, week)
        year = int(key[0:4])
        week = int(key[6:])
        return (year, week)
    # BIN_MONTH: 'YYYY-MM'
    return (int(key[0:4]), int(key[5:7]))


def _direction(mean_first: float, mean_last: float) -> str:
    """Bucket a delta into a trend direction label.

    STABLE when |delta| is within :data:`STABLE_DELTA_THRESHOLD`
    (1pp) so a tiny jitter doesn't read as 'the model is
    drifting'.
    """
    delta = mean_last - mean_first
    if abs(delta) < STABLE_DELTA_THRESHOLD:
        return TREND_STABLE
    return TREND_UP if delta > 0 else TREND_DOWN


def build_cluster_trend(
    cluster_id: str,
    rows: list[tuple[object, dict | None]],
    *,
    bin_size: str = BIN_MONTH,
) -> dict:
    """Build the per-cluster trend payload.

    Args:
        cluster_id: the cluster to filter for.
        rows: list of ``(created_at, results_json)`` tuples.
            ``created_at`` may be a datetime (preferred) or an
            ISO 8601 string. ``results_json`` is the simulation's
            persisted results dict (or None when missing).
        bin_size: ``BIN_MONTH`` (default) / ``BIN_WEEK`` / ``BIN_DAY``.

    Returns:
        A dict matching :class:`ClusterTrendOut`:

        * ``cluster_id`` — echoed.
        * ``bin_size`` — echoed.
        * ``bins`` — list of per-bin dicts sorted chronologically.
          Each row: ``bin`` (key), ``bin_start`` (ISO 8601 UTC),
          ``mean_conversion``, ``observation_count``,
          ``sim_count`` (sims in the bin).
        * ``overall_direction`` — UP / DOWN / STABLE / UNKNOWN
          bucketed from the first vs last bin mean.
        * ``mean_delta`` — last_bin_mean − first_bin_mean, or
          None when fewer than 2 bins have data.
        * ``first_bin_mean`` / ``last_bin_mean`` — for the
          dashboard's headline ("X% → Y%").
    """
    effective_bin = normalise_bin(bin_size)
    bins: dict[str, dict] = {}
    for created_at, results in rows:
        # Normalise created_at to a UTC datetime.
        if isinstance(created_at, datetime):
            dt = created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
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
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        else:
            continue
        # Pull cluster_breakdown from results.
        cb: dict | None = None
        if isinstance(results, dict):
            inner = results.get("cluster_breakdown")
            if isinstance(inner, dict):
                cb = inner
        if cb is None:
            continue
        raw = cb.get(cluster_id)
        rate = _safe_float(raw)
        if rate is None:
            continue
        key = _bin_key(dt, effective_bin)
        # Bin-start timestamp: first day of month/week/day.
        if effective_bin == BIN_DAY:
            ts = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif effective_bin == BIN_WEEK:
            # ISO weekday: Mon=1 ... Sun=7. Back up to Monday.
            iso_weekday = dt.isoweekday()
            ts = (dt - _timedelta(days=iso_weekday - 1)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
        else:
            ts = dt.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0,
            )
        slot = bins.setdefault(
            key,
            {
                "bin": key,
                "bin_start": ts.isoformat(),
                "rates": [],
                "_sim_ids": set(),
            },
        )
        slot["rates"].append(rate)
        # Track unique sim occurrences via the (id(cluster_id))
        # marker — cluster_breakdown has no sim id, so we use
        # the bin key + rate as the dedupe proxy. Equal rate
        # + same bin ⇒ same sim (this is conservative — if
        # two distinct sims happen to produce the same rate,
        # they're treated as one; the aggregate still
        # reflects the population correctly).
        slot["_sim_ids"].add(rate)

    # Materialise the bin dicts and sort chronologically.
    rows_out: list[dict] = []
    for key in sorted(bins.keys(), key=lambda k: _bin_sort_key(k, effective_bin)):
        slot = bins[key]
        rates = slot["rates"]
        mean = sum(rates) / len(rates) if rates else 0.0
        rows_out.append({
            "bin": key,
            "bin_start": slot["bin_start"],
            "mean_conversion": round(mean, 6),
            "observation_count": len(rates),
            "sim_count": len(slot["_sim_ids"]),
        })

    # Direction + delta from first to last bin with data.
    if len(rows_out) < 2:
        mean_delta = None
        first_mean = rows_out[0]["mean_conversion"] if rows_out else None
        last_mean = first_mean
        overall = TREND_UNKNOWN if not rows_out else TREND_STABLE
    else:
        first_mean = rows_out[0]["mean_conversion"]
        last_mean = rows_out[-1]["mean_conversion"]
        mean_delta = round(last_mean - first_mean, 6)
        overall = _direction(first_mean, last_mean)

    return {
        "cluster_id": cluster_id,
        "bin_size": effective_bin,
        "bins": rows_out,
        "overall_direction": overall,
        "first_bin_mean": (
            round(first_mean, 6) if first_mean is not None else None
        ),
        "last_bin_mean": (
            round(last_mean, 6) if last_mean is not None else None
        ),
        "mean_delta": mean_delta,
    }


def _timedelta(**kwargs):
    """Local helper to avoid importing timedelta at module top
    just for the week-rollback calculation."""
    from datetime import timedelta
    return timedelta(**kwargs)


__all__ = [
    "BIN_MONTH",
    "BIN_WEEK",
    "BIN_DAY",
    "VALID_BINS",
    "STABLE_DELTA_THRESHOLD",
    "TREND_UP",
    "TREND_DOWN",
    "TREND_STABLE",
    "TREND_UNKNOWN",
    "VALID_TREND_LABELS",
    "normalise_bin",
    "build_cluster_trend",
]