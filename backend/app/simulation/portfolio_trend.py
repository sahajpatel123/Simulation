"""
Pure helpers for the portfolio trend endpoint.

The portfolio trend fuses TWO portfolio summaries — one for the
"earlier" time window and one for the "later" window — into a
single delta payload so the dashboard can render "MAE dropped
from 0.12 → 0.05 over the last 30 days · 3 → 12 sims ·
NEEDS_ATTENTION → HEALTHY".

The helper is pure-Python (no SQL, no I/O) — the route layer
runs :func:`build_portfolio_summary` twice (once per window) and
passes the two payloads in. The trend work is composition + a
handful of threshold comparisons.

Direction labels are bucketed from a relative-change threshold
(:data:`STABLE_RELATIVE_THRESHOLD`, default 5 %): below the
threshold → ``STABLE``; otherwise ``IMPROVING`` / ``DEGRADING``
depending on which direction the metric SHOULD move. For new /
disappeared metrics (``earlier=0, later>0`` → ``NEW``;
``earlier>0, later=0`` → ``RESOLVED``) we use dedicated labels.

Overall health transition uses a transition matrix — see
:func:`_health_transition`.
"""
from __future__ import annotations

# Direction labels — emitted by per-metric delta calc.
DIR_IMPROVING: str = "IMPROVING"
DIR_DEGRADING: str = "DEGRADING"
DIR_STABLE: str = "STABLE"
DIR_NEW: str = "NEW"          # metric absent in earlier, present in later
DIR_RESOLVED: str = "RESOLVED"  # metric present in earlier, absent in later
VALID_DIRECTIONS: frozenset[str] = frozenset({
    DIR_IMPROVING,
    DIR_DEGRADING,
    DIR_STABLE,
    DIR_NEW,
    DIR_RESOLVED,
})

# Overall transition labels — emitted by health-transition calc.
TREND_IMPROVED: str = "IMPROVED"
TREND_DEGRADED: str = "DEGRADED"
TREND_STABLE: str = "STABLE"
TREND_NEW: str = "NEW"
TREND_RESOLVED: str = "RESOLVED"
TREND_MIXED: str = "MIXED"
VALID_TRENDS: frozenset[str] = frozenset({
    TREND_IMPROVED,
    TREND_DEGRADED,
    TREND_STABLE,
    TREND_NEW,
    TREND_RESOLVED,
    TREND_MIXED,
})

# Relative-change threshold below which a metric is labelled
# STABLE. 5 % matches the same precision founders see on the
# outcomes digest (mae/mape to 4 decimal places).
STABLE_RELATIVE_THRESHOLD: float = 0.05

# Per-metric absolute-change thresholds for the ``significant``
# flag. A change SMALLER than these thresholds is treated as
# noise even when IMPROVING / DEGRADING — the dashboard can
# filter on significant=True to surface only meaningful shifts.
# Different metrics need different scales: MAE is in fractions
# (0.005 = 0.5pp) while tighten_count is a unit count.
SIGNIFICANT_THRESHOLDS: dict[str, float] = {
    "mae": 0.005,
    "mape": 0.05,
    "data_quality_score": 0.10,
    # Counts: any change ≥ 1 is meaningful.
    "critical_findings": 1.0,
    "correlated_bias_count": 1.0,
    "tighten_count": 1.0,
    "loosen_count": 1.0,
    "needs_attention_clusters": 1.0,
}

# How many deltas to surface in ``key_shifts``. The dashboard's
# headline widget renders this list directly, so the cap keeps
# the tile readable.
KEY_SHIFTS_LIMIT: int = 3


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float or return ``None``. Mirrors the
    helper module's defensive coercion so NaN / None /
    out-of-range never poison a delta."""
    import math
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
    return value


def _direction(
    earlier: float | None,
    later: float | None,
    higher_is_better: bool,
) -> str:
    """Bucket a numeric delta into a direction label.

    Args:
        earlier / later: the metric values (None when missing).
        higher_is_better: True for metrics where later>earlier
            is good (e.g. data_quality_score, trusted_count);
            False for metrics where lower is better
            (e.g. mae, mape, correlated_bias_count).
    """
    if earlier is None and later is None:
        return DIR_STABLE
    if earlier is None and later is not None:
        return DIR_NEW
    if earlier is not None and later is None:
        return DIR_RESOLVED
    # Both numeric.
    if earlier == 0 and later == 0:
        return DIR_STABLE
    # Relative change against the larger magnitude — handles
    # "later went from 0.001 → 0.0005" as STABLE rather than
    # spurious DEGRADING.
    base = max(abs(earlier), abs(later), 1e-9)
    rel_change = (later - earlier) / base
    if abs(rel_change) < STABLE_RELATIVE_THRESHOLD:
        return DIR_STABLE
    if later > earlier:
        return DIR_IMPROVING if higher_is_better else DIR_DEGRADING
    return DIR_DEGRADING if higher_is_better else DIR_IMPROVING


def _health_rank(health: str) -> int:
    """Rank a health label so transitions can be compared.

    Higher = healthier. INSUFFICIENT_DATA is treated as worse
    than CRITICAL — we want to flag a regression into
    INSUFFICIENT_DATA as DEGRADED, not as "improvement because
    the score went down".
    """
    order = {
        "INSUFFICIENT_DATA": 0,
        "CRITICAL": 1,
        "NEEDS_ATTENTION": 2,
        "HEALTHY": 3,
    }
    return order.get(health, -1)


def _health_transition(earlier: str, later: str) -> str:
    """Bucket the overall-health delta into a trend label.

    Rules:
      * NEW — earlier was INSUFFICIENT_DATA, later is real data.
      * RESOLVED — earlier was real data, later is INSUFFICIENT_DATA.
      * IMPROVED — later_rank > earlier_rank (strict).
      * DEGRADED — later_rank < earlier_rank (strict).
      * STABLE — same rank.
      * MIXED — used as a fallback when something weird happens
        (e.g. unknown health strings).
    """
    e_rank = _health_rank(earlier)
    l_rank = _health_rank(later)
    if earlier == "INSUFFICIENT_DATA" and later != "INSUFFICIENT_DATA":
        return TREND_NEW
    if earlier != "INSUFFICIENT_DATA" and later == "INSUFFICIENT_DATA":
        return TREND_RESOLVED
    if l_rank > e_rank:
        return TREND_IMPROVED
    if l_rank < e_rank:
        return TREND_DEGRADED
    if e_rank == l_rank:
        return TREND_STABLE
    return TREND_MIXED


def _deltas_row(
    key: str,
    earlier: float | None,
    later: float | None,
    higher_is_better: bool,
) -> dict:
    """Build a per-metric delta row matching the helper output
    contract.
    """
    direction = _direction(earlier, later, higher_is_better)
    delta = None
    if earlier is not None and later is not None:
        delta = round(later - earlier, 6)
    # Significance is independent of direction — a 0.1pp MAE
    # shift is "STABLE" by direction (within 5%) but still
    # "not significant" by the absolute threshold. Conversely a
    # 50pp MAE shift is both DEGRADING and significant.
    significant = False
    if delta is not None:
        threshold = SIGNIFICANT_THRESHOLDS.get(key, 0.0)
        significant = abs(delta) >= threshold
    return {
        "metric": key,
        "earlier": earlier,
        "later": later,
        "delta": delta,
        "direction": direction,
        "significant": significant,
    }


def _build_key_shifts(deltas: list[dict]) -> list[dict]:
    """Surface the top-N most-meaningful deltas for the headline.

    Only IMPROVING / DEGRADING rows compete (STABLE / NEW /
    RESOLVED aren't a "shift"). Ranked by relative-change
    magnitude against the larger of |earlier|, |later|, with a
    1e-9 floor so a metric moving from 0 → 0.001 ranks ahead
    of a metric moving from 1.0 → 1.0 (the latter is stable).
    """
    candidates: list[tuple[float, dict]] = []
    for d in deltas:
        if d["direction"] not in (DIR_IMPROVING, DIR_DEGRADING):
            continue
        e = d["earlier"]
        later_v = d["later"]
        if e is None or later_v is None:
            continue
        base = max(abs(e), abs(later_v), 1e-9)
        magnitude = abs(later_v - e) / base
        candidates.append((magnitude, d))
    candidates.sort(key=lambda x: x[0], reverse=True)
    top = [
        {
            "metric": row["metric"],
            "direction": row["direction"],
            "delta": row["delta"],
            "earlier": row["earlier"],
            "later": row["later"],
            "relative_change": round(magnitude, 6),
        }
        for magnitude, row in candidates[:KEY_SHIFTS_LIMIT]
    ]
    return top


def compute_portfolio_trend(
    earlier_payload: dict,
    later_payload: dict,
) -> dict:
    """Diff two portfolio summary payloads into a trend rollup.

    Args:
        earlier_payload: output of :func:`build_portfolio_summary`
            for the earlier time window.
        later_payload: output of :func:`build_portfolio_summary`
            for the later time window.

    Returns:
        A dict matching :class:`PortfolioTrendOut`:

        * ``earlier_simulation_count`` / ``later_simulation_count``
          / ``simulation_count_delta`` — how the batch grew.
        * ``earlier_health`` / ``later_health`` — echoed back.
        * ``health_transition`` — one of :data:`VALID_TRENDS`.
        * ``deltas`` — list of per-metric rows (mae, mape,
          critical_findings, correlated_bias_count, tighten_count,
          loosen_count, data_quality_score, needs_attention_clusters).
        * ``improving_count`` / ``degrading_count`` / ``stable_count``
          — summary counts so the dashboard has a one-glance read.
        * ``summary`` — one-line human-readable headline.
    """
    e_findings = earlier_payload.get("findings_summary") or {}
    e_outcomes = earlier_payload.get("outcomes_summary") or {}
    e_clusters = earlier_payload.get("clusters_summary") or {}
    e_arch = earlier_payload.get("architect_accuracy_summary") or {}
    l_findings = later_payload.get("findings_summary") or {}
    l_outcomes = later_payload.get("outcomes_summary") or {}
    l_clusters = later_payload.get("clusters_summary") or {}
    l_arch = later_payload.get("architect_accuracy_summary") or {}

    earlier_health = earlier_payload.get("overall_health") or (
        "INSUFFICIENT_DATA"
    )
    later_health = later_payload.get("overall_health") or (
        "INSUFFICIENT_DATA"
    )
    health_transition = _health_transition(
        earlier_health, later_health
    )

    # Each metric paired with its (higher_is_better) flag.
    metric_specs: list[tuple[str, callable, callable, bool]] = [
        (
            "mae",
            lambda p: p.get("mae"),
            lambda p: p.get("mae"),
            False,
        ),
        (
            "mape",
            lambda p: p.get("mape"),
            lambda p: p.get("mape"),
            False,
        ),
        (
            "critical_findings",
            lambda p: (
                (p.get("severity_breakdown") or {}).get(
                    "CRITICAL"
                )
            ),
            lambda p: (
                (p.get("severity_breakdown") or {}).get(
                    "CRITICAL"
                )
            ),
            False,
        ),
        (
            "correlated_bias_count",
            lambda p: p.get("correlated_bias_count"),
            lambda p: p.get("correlated_bias_count"),
            False,
        ),
        (
            "tighten_count",
            lambda p: p.get("tighten_count"),
            lambda p: p.get("tighten_count"),
            False,
        ),
        (
            "loosen_count",
            lambda p: p.get("loosen_count"),
            lambda p: p.get("loosen_count"),
            False,
        ),
        (
            "data_quality_score",
            lambda p: p.get("data_quality_score"),
            lambda p: p.get("data_quality_score"),
            True,
        ),
        (
            "needs_attention_clusters",
            lambda p: p.get("needs_attention_count"),
            lambda p: p.get("needs_attention_count"),
            False,
        ),
    ]
    # Note: outcomes_summary is shared across both metrics
    # except critical_findings (findings). The closures pull
    # from the right summary dict via the module-level lookup.
    def _find_metric(spec, payload):
        key, e_fn, l_fn, hib = spec
        return e_fn(payload) if key in {
            "mae", "mape", "data_quality_score",
        } else None

    deltas: list[dict] = []
    for spec in metric_specs:
        key = spec[0]
        if key in {"mae", "mape", "data_quality_score"}:
            e_val = _safe_float(spec[1](e_outcomes))
            l_val = _safe_float(spec[1](l_outcomes))
        elif key == "critical_findings":
            e_val = _safe_float(spec[1](e_findings))
            l_val = _safe_float(spec[1](l_findings))
        elif key == "needs_attention_clusters":
            e_val = _safe_float(spec[1](e_clusters))
            l_val = _safe_float(spec[1](l_clusters))
        else:
            e_val = _safe_float(spec[1](e_arch))
            l_val = _safe_float(spec[1](l_arch))
        deltas.append(
            _deltas_row(key, e_val, l_val, spec[3])
        )

    improving_count = sum(
        1 for d in deltas if d["direction"] == DIR_IMPROVING
    )
    degrading_count = sum(
        1 for d in deltas if d["direction"] == DIR_DEGRADING
    )
    stable_count = sum(
        1 for d in deltas if d["direction"] == DIR_STABLE
    )
    significant_change_count = sum(
        1 for d in deltas if d["significant"]
    )
    key_shifts = _build_key_shifts(deltas)

    e_count = int(earlier_payload.get("simulation_count") or 0)
    l_count = int(later_payload.get("simulation_count") or 0)

    summary = _build_summary(
        earlier_health=earlier_health,
        later_health=later_health,
        health_transition=health_transition,
        improving_count=improving_count,
        degrading_count=degrading_count,
        e_count=e_count,
        l_count=l_count,
    )

    return {
        "earlier_simulation_count": e_count,
        "later_simulation_count": l_count,
        "simulation_count_delta": l_count - e_count,
        "earlier_health": earlier_health,
        "later_health": later_health,
        "health_transition": health_transition,
        "deltas": deltas,
        "improving_count": improving_count,
        "degrading_count": degrading_count,
        "stable_count": stable_count,
        "significant_change_count": significant_change_count,
        "key_shifts": key_shifts,
        "summary": summary,
    }


def _build_summary(
    *,
    earlier_health: str,
    later_health: str,
    health_transition: str,
    improving_count: int,
    degrading_count: int,
    e_count: int,
    l_count: int,
) -> str:
    """One-line headline for the dashboard.

    Composed deterministically from the health transition and
    the simulation-count delta so the dashboard can render the
    same string the helper produces.
    """
    if health_transition == TREND_NEW:
        return (
            f"Calibration analysis unlocked: {l_count} sim(s) "
            f"now have ground truth"
        )
    if health_transition == TREND_RESOLVED:
        return (
            "Regression: ground-truth coverage dropped, no actionable "
            "calibration data"
        )
    count_delta = l_count - e_count
    if health_transition == TREND_IMPROVED:
        return (
            f"{earlier_health} → {later_health} · "
            f"{improving_count} metric(s) improved · "
            f"{count_delta:+d} sim(s)"
        )
    if health_transition == TREND_DEGRADED:
        return (
            f"{earlier_health} → {later_health} · "
            f"{degrading_count} metric(s) degraded · "
            f"{count_delta:+d} sim(s)"
        )
    if health_transition == TREND_STABLE:
        return (
            f"{earlier_health} stable · "
            f"{improving_count} up / {degrading_count} down · "
            f"{count_delta:+d} sim(s)"
        )
    return (
        f"{earlier_health} → {later_health} · mixed signals · "
        f"{count_delta:+d} sim(s)"
    )


__all__ = [
    "DIR_IMPROVING",
    "DIR_DEGRADING",
    "DIR_STABLE",
    "DIR_NEW",
    "DIR_RESOLVED",
    "VALID_DIRECTIONS",
    "TREND_IMPROVED",
    "TREND_DEGRADED",
    "TREND_STABLE",
    "TREND_NEW",
    "TREND_RESOLVED",
    "TREND_MIXED",
    "VALID_TRENDS",
    "STABLE_RELATIVE_THRESHOLD",
    "SIGNIFICANT_THRESHOLDS",
    "KEY_SHIFTS_LIMIT",
    "compute_portfolio_trend",
]