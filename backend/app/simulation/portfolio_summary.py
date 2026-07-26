"""
Pure helpers for the portfolio summary endpoint.

The portfolio summary fuses the four cross-simulation aggregates
into a single dashboard payload. Each sub-aggregate is computed
independently (by its own helper); this module's job is purely
composition + deriving cross-aggregate signals:

* ``correlated_bias_count`` — number of architect names that
  appear in BOTH the findings rollup's "top critical architect"
  list AND the architect-accuracy bridge's "most biased
  architects" list. When this number is high, the architect's
  CRITICAL flags correlate with actual bias (the alert signal
  is real, not noise).
* ``data_quality_score`` — fraction of sims that had at least
  one finding AND an attached outcome. Closer to 1.0 means we
  have ground truth for most of the batch; closer to 0.0 means
  most sims are still unmeasurable.
* ``overall_health`` — one of ``HEALTHY`` / ``NEEDS_ATTENTION``
  / ``CRITICAL`` / ``INSUFFICIENT_DATA`` bucketed from
  confidence_label + needs_attention_count + correlated_bias_count.
  The dashboard's one-word summary.

The helper is pure-Python (no SQL, no I/O) — the route layer
joins the data and runs the sub-helpers before invoking this
composition step. Composition is O(A) where A is the architect
count (≤ 21).
"""
from __future__ import annotations

# Health-label allowlist — the route / schema echo this enum
# verbatim. Stable so the dashboard can hard-code the set.
LABEL_HEALTHY: str = "HEALTHY"
LABEL_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
LABEL_CRITICAL: str = "CRITICAL"
LABEL_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VALID_HEALTH_LABELS: frozenset[str] = frozenset({
    LABEL_HEALTHY,
    LABEL_NEEDS_ATTENTION,
    LABEL_CRITICAL,
    LABEL_INSUFFICIENT_DATA,
})

# Top critical architects surfaced from the findings rollup.
# Kept small so the intersection with "most biased" stays
# meaningful (an architect that shows up in both lists within
# the top 5 is genuinely correlated, not a long-tail mention).
TOP_N_CORRELATION: int = 5

# Health thresholds.
#
# We start from the outcomes-digest confidence_label (the cleanest
# single signal), then OR-in stricter signals from the other
# aggregates. The bucketing is conservative — we only escalate to
# CRITICAL when multiple bad signals line up — because the
# founder's first instinct is to look at this one word.
#
#   INSUFFICIENT_DATA — no actionable outcomes to score.
#   HEALTHY            — WELL_CALIBRATED + no correlated bias +
#                        < 2 needs_attention clusters.
#   NEEDS_ATTENTION    — NEUTRAL / NEEDS_ATTENTION confidence OR
#                        1+ correlated bias OR ≥ 2 needs_attention
#                        clusters.
#   CRITICAL           — POORLY_CALIBRATED AND ≥ 2 correlated bias.

# CTA strings for ``next_action`` — one per health bucket. The
# route / schema echo these verbatim so the dashboard can map a
# label to its primary call-to-action button.
NEXT_ACTION_CRITICAL: str = (
    "Review correlated bias and recalibrate top architects"
)
NEXT_ACTION_NEEDS_ATTENTION: str = (
    "Investigate flagged architects and collect more outcomes"
)
NEXT_ACTION_HEALTHY: str = (
    "Continue current calibration — no action needed"
)
NEXT_ACTION_INSUFFICIENT_DATA: str = (
    "Record more outcomes to unlock calibration analysis"
)
VALID_NEXT_ACTIONS: frozenset[str] = frozenset({
    NEXT_ACTION_CRITICAL,
    NEXT_ACTION_NEEDS_ATTENTION,
    NEXT_ACTION_HEALTHY,
    NEXT_ACTION_INSUFFICIENT_DATA,
})

# Cap on the recommendations list — keeps the dashboard tile
# readable and prevents one bad aggregate from spamming 30 lines.
MAX_RECOMMENDATIONS: int = 8


def _csv_escape(value: object) -> str:
    """Escape a value for a single CSV cell.

    Wraps in quotes when the value contains a comma / quote /
    newline. Quotes inside the value are doubled (the standard
    CSV convention). ``None`` / non-strings are coerced via
    ``str()``.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if any(ch in text for ch in (",", "\"", "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def _csv_row(cells: list[object]) -> str:
    """Join a list of values into a single CSV row."""
    return ",".join(_csv_escape(c) for c in cells)


def portfolio_to_csv(
    portfolio_payload: dict,
    *,
    metadata: dict | None = None,
) -> str:
    """Render a portfolio summary payload as a multi-section CSV.

    The output is structured for spreadsheet import — sections
    are separated by a blank line so users can split on the
    section header row.

    Args:
        portfolio_payload: the dict returned by
            :func:`build_portfolio_summary`.
        metadata: optional dict of ``# key: value`` lines
            rendered at the very top of the file (e.g.
            ``{"generated_at": "2026-07-26T07:00:00Z",
            "user_id": 42}``). Useful for provenance — the
            spreadsheet can show when the file was generated
            and by whom without polluting the section rows.

    Sections (in order):

      1. **Summary** — single row of portfolio-level scalars
         (simulation_count, correlated_bias_count,
         data_quality_score, overall_health, plus the first
         recommendation + next_action for at-a-glance review).
      2. **Findings** — header + one row per top
         critical architect.
      3. **Outcomes** — header + a single MAE / MAPE / RMSE
         / outlier_count / worst_offender row.
      4. **Clusters** — header + one row per top laggard.
      5. **Architect accuracy** — header + one row per
         tighten / loosen / trusted / insufficient_data count.
      6. **Recommendations** — header + one row per
         recommendation string.

    Empty / missing sub-aggregates produce an empty section
    (header only) so the dashboard can show "no data" cleanly.
    """
    lines: list[str] = []

    # Metadata header — ``# key: value`` lines, one per entry.
    # Rendered BEFORE the sections so spreadsheets can show
    # provenance at the top. The leading ``#`` keeps the
    # convention that all CSV comments start with ``#``.
    if metadata:
        for key, value in metadata.items():
            lines.append(f"# {key}: {value}")
        lines.append("")

    # Section 1: summary
    lines.append("# Summary")
    lines.append(_csv_row([
        "simulation_count",
        "correlated_bias_count",
        "data_quality_score",
        "overall_health",
        "next_action",
    ]))
    recs = list(portfolio_payload.get("key_recommendations") or [])
    lines.append(_csv_row([
        portfolio_payload.get("simulation_count", 0),
        portfolio_payload.get("correlated_bias_count", 0),
        portfolio_payload.get("data_quality_score", 0.0),
        portfolio_payload.get("overall_health", "INSUFFICIENT_DATA"),
        portfolio_payload.get(
            "next_action", "Record more outcomes to unlock calibration analysis"
        ),
    ]))
    lines.append("")

    findings = portfolio_payload.get("findings_summary") or {}
    outcomes = portfolio_payload.get("outcomes_summary") or {}
    clusters = portfolio_payload.get("clusters_summary") or {}
    arch = (
        portfolio_payload.get("architect_accuracy_summary") or {}
    )

    # Section 2: findings (one row per top critical architect).
    lines.append("# Findings — top critical architects")
    lines.append(_csv_row(["architect_name"]))
    top_archs = list(findings.get("top_critical_architects") or [])
    if top_archs:
        for name in top_archs:
            lines.append(_csv_row([name]))
    else:
        lines.append(_csv_row(["(none)"]))
    lines.append("")

    # Section 3: outcomes (single-row summary).
    lines.append("# Outcomes — conversion accuracy")
    lines.append(_csv_row([
        "mae",
        "mape",
        "rmse",
        "mae_count",
        "outlier_count",
        "confidence_label",
        "worst_offender_sim_id",
    ]))
    lines.append(_csv_row([
        outcomes.get("mae", 0.0),
        outcomes.get("mape", 0.0),
        outcomes.get("rmse", 0.0),
        outcomes.get("mae_count", 0),
        outcomes.get("outlier_count", 0),
        outcomes.get("confidence_label", "INSUFFICIENT_DATA"),
        outcomes.get("worst_offender_sim_id", ""),
    ]))
    lines.append("")

    # Section 4: clusters (one row per top laggard).
    lines.append("# Clusters — top laggards")
    lines.append(_csv_row(["cluster_id"]))
    laggards = list(clusters.get("top_laggards") or [])
    if laggards:
        for name in laggards:
            lines.append(_csv_row([name]))
    else:
        lines.append(_csv_row(["(none)"]))
    lines.append("")

    # Section 5: architect accuracy (one row per action count).
    lines.append("# Architect accuracy — action counts")
    lines.append(_csv_row([
        "tighten_count",
        "loosen_count",
        "trusted_count",
        "insufficient_data_count",
        "outcome_attached_sim_count",
    ]))
    lines.append(_csv_row([
        arch.get("tighten_count", 0),
        arch.get("loosen_count", 0),
        arch.get("trusted_count", 0),
        arch.get("insufficient_data_count", 0),
        arch.get("outcome_attached_sim_count", 0),
    ]))
    lines.append("")

    # Section 6: recommendations.
    lines.append("# Recommendations")
    lines.append(_csv_row(["recommendation"]))
    if recs:
        for rec in recs:
            lines.append(_csv_row([rec]))
    else:
        lines.append(_csv_row(["(none)"]))
    lines.append("")

    return "\n".join(lines)


def _set_intersection_size(a: list[str], b: list[str]) -> int:
    """Return the size of the case-insensitive intersection of two
    name lists. ``Pricing`` and ``pricing`` match; ``pricing`` and
    ``pricing_v2`` do not.
    """
    set_a = {n.casefold() for n in a if n}
    set_b = {n.casefold() for n in b if n}
    return len(set_a & set_b)


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float or return ``None``."""
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


def _confidence_label(payload: dict) -> str:
    """Pull the confidence_label from an outcomes payload (default
    INSUFFICIENT_DATA when missing)."""
    raw = payload.get("confidence_label")
    if isinstance(raw, str) and raw:
        return raw
    return LABEL_INSUFFICIENT_DATA


def _next_action(overall_health: str) -> str:
    """Map ``overall_health`` to a single primary call-to-action.

    The string is what the dashboard renders as its primary
    button / banner headline. Stable so the dashboard can
    hard-code the four CTAs.
    """
    if overall_health == LABEL_CRITICAL:
        return NEXT_ACTION_CRITICAL
    if overall_health == LABEL_NEEDS_ATTENTION:
        return NEXT_ACTION_NEEDS_ATTENTION
    if overall_health == LABEL_HEALTHY:
        return NEXT_ACTION_HEALTHY
    return NEXT_ACTION_INSUFFICIENT_DATA


def _build_recommendations(
    *,
    findings: dict,
    outcomes: dict,
    clusters: dict,
    architect_accuracy: dict,
    correlated_bias_count: int,
    data_quality_score: float,
    simulation_count: int,
) -> list[str]:
    """Distil each sub-aggregate into one-line actionable hints.

    Capped at :data:`MAX_RECOMMENDATIONS` so the dashboard tile
    stays readable; ordered by priority (critical / bias /
    coverage first, then the smaller signals).
    """
    recs: list[str] = []

    # Architect-accuracy CTAs are the most actionable — flag them
    # first so the dashboard surfaces a real "fix this" button.
    tighten = architect_accuracy.get("tighten_count") or 0
    if tighten > 0:
        recs.append(
            f"Tighten calibration for {tighten} over-predicting architect(s)"
        )
    loosen = architect_accuracy.get("loosen_count") or 0
    if loosen > 0:
        recs.append(
            f"Loosen calibration for {loosen} under-predicting architect(s)"
        )

    # Correlated-bias cross-aggregate signal — the strongest "the
    # CRITICAL flag is real" evidence we have.
    if correlated_bias_count >= 1:
        recs.append(
            f"{correlated_bias_count} architect(s) flagged CRITICAL "
            f"and confirmed biased — prioritise their calibration"
        )

    # Findings — the top failure domain, when it's systemic.
    shared = findings.get("shared_domain_count") or 0
    if shared > 0:
        recs.append(
            f"{shared} architect name(s) appear as the top failure "
            f"domain in ≥half of sims"
        )

    # Outcomes — confidence + outliers.
    confidence = outcomes.get("confidence_label")
    if confidence == "POORLY_CALIBRATED":
        recs.append(
            "Calibration confidence is POORLY_CALIBRATED — recalibrate "
            "the model"
        )
    elif confidence == "NEEDS_ATTENTION":
        recs.append(
            "Calibration confidence is NEEDS_ATTENTION — review "
            "predicted vs actual"
        )
    outlier_count = outcomes.get("outlier_count") or 0
    if outlier_count > 0:
        recs.append(
            f"{outlier_count} simulation(s) exceed the outlier "
            f"variance threshold"
        )

    # Clusters — coverage + attention.
    needs_attention = clusters.get("needs_attention_count") or 0
    if needs_attention > 0:
        recs.append(
            f"{needs_attention} cluster segment(s) need closer look"
        )
    under_observed = clusters.get("under_observed_count") or 0
    if under_observed > 0:
        recs.append(
            f"{under_observed} cluster(s) are under-observed — collect "
            f"more sims covering them"
        )

    # Data-quality nudge — only when the score is meaningfully low.
    if simulation_count > 0 and data_quality_score < 0.5:
        recs.append(
            f"Data quality is {int(round(data_quality_score * 100))}%"
            f" — record more outcomes to improve calibration confidence"
        )

    return recs[:MAX_RECOMMENDATIONS]


def _overall_health(
    confidence_label: str,
    needs_attention_count: int,
    correlated_bias_count: int,
    outcome_attached_count: int,
    simulation_count: int,
) -> str:
    """Bucket the cross-aggregate signals into one word.

    Returns the most severe label that applies. Order:
    INSUFFICIENT_DATA → CRITICAL → NEEDS_ATTENTION → HEALTHY.
    """
    if (
        confidence_label == LABEL_INSUFFICIENT_DATA
        or outcome_attached_count == 0
    ):
        return LABEL_INSUFFICIENT_DATA

    is_critical_confidence = confidence_label == "POORLY_CALIBRATED"
    is_biased_correlated = correlated_bias_count >= 2
    if is_critical_confidence and is_biased_correlated:
        return LABEL_CRITICAL

    is_needs_attention_confidence = confidence_label == "NEEDS_ATTENTION"
    has_attention_signal = (
        is_needs_attention_confidence
        or correlated_bias_count >= 1
        or needs_attention_count >= 2
    )
    if has_attention_signal:
        return LABEL_NEEDS_ATTENTION

    return LABEL_HEALTHY


def _summarise_findings(payload: dict) -> dict:
    """Reduce a full findings rollup to the handful of fields the
    dashboard summary tile needs."""
    return {
        "total_findings": int(payload.get("total_findings") or 0),
        "filtered_findings": int(
            payload.get("filtered_findings") or 0
        ),
        "severity_breakdown": dict(
            payload.get("severity_breakdown") or {}
        ),
        "shared_domain_count": int(
            payload.get("shared_domain_count") or 0
        ),
        "top_critical_architects": list(
            payload.get("top_architects") or []
        )[:TOP_N_CORRELATION],
        "simulations_with_findings": int(
            payload.get("simulations_with_findings") or 0
        ),
    }


def _summarise_outcomes(payload: dict) -> dict:
    """Reduce a full outcomes digest to the summary fields."""
    return {
        "mae": float(payload.get("mae") or 0.0),
        "mape": float(payload.get("mape") or 0.0),
        "rmse": float(payload.get("rmse") or 0.0),
        "mae_count": int(payload.get("mae_count") or 0),
        "outlier_count": int(payload.get("outlier_count") or 0),
        "direction_breakdown": dict(
            payload.get("direction_breakdown") or {}
        ),
        "confidence_label": _confidence_label(payload),
        "worst_offender_sim_id": payload.get(
            "worst_offender_sim_id"
        ),
    }


def _summarise_clusters(payload: dict) -> dict:
    """Reduce a full clusters aggregate to the summary fields."""
    return {
        "clusters_seen": int(payload.get("clusters_seen") or 0),
        "under_observed_count": int(
            payload.get("under_observed_count") or 0
        ),
        "needs_attention_count": int(
            payload.get("needs_attention_count") or 0
        ),
        "top_laggards": list(payload.get("top_laggards") or []),
    }


def _summarise_architect_accuracy(payload: dict) -> dict:
    """Reduce a full architect-accuracy bridge to summary fields."""
    return {
        "outcome_attached_sim_count": int(
            payload.get("outcome_attached_sim_count") or 0
        ),
        "tighten_count": int(payload.get("tighten_count") or 0),
        "loosen_count": int(payload.get("loosen_count") or 0),
        "trusted_count": int(payload.get("trusted_count") or 0),
        "insufficient_data_count": int(
            payload.get("insufficient_data_count") or 0
        ),
        "most_biased_architects": list(
            payload.get("most_biased_architects") or []
        )[:TOP_N_CORRELATION],
    }


def build_portfolio_summary(
    *,
    simulation_count: int,
    findings_payload: dict | None = None,
    outcomes_payload: dict | None = None,
    clusters_payload: dict | None = None,
    architect_accuracy_payload: dict | None = None,
) -> dict:
    """Fuse the four sub-aggregates into a single dashboard payload.

    Args:
        simulation_count: how many sims the user selected. The
            denominator for the data-quality score.
        findings_payload: output of :func:`aggregate_findings`.
            May be ``None`` if no sims were provided.
        outcomes_payload: output of :func:`aggregate_outcomes`.
        clusters_payload: output of :func:`aggregate_clusters`.
        architect_accuracy_payload: output of
            :func:`bridge_architect_accuracy`.

    Returns:
        A dict matching :class:`PortfolioSummaryOut`:

        * ``simulation_count`` — echoed back.
        * ``findings_summary`` / ``outcomes_summary`` /
          ``clusters_summary`` / ``architect_accuracy_summary`` —
          reduced views of each sub-aggregate, suitable for the
          dashboard's summary tiles.
        * ``correlated_bias_count`` — number of architect names
          that appear in BOTH
          ``findings_summary.top_critical_architects`` AND
          ``architect_accuracy_summary.most_biased_architects``.
        * ``data_quality_score`` — fraction of sims with at least
          one finding AND an attached outcome (0.0 when no sims).
        * ``overall_health`` — one of
          :data:`VALID_HEALTH_LABELS`.
    """
    findings_payload = findings_payload or {}
    outcomes_payload = outcomes_payload or {}
    clusters_payload = clusters_payload or {}
    architect_accuracy_payload = architect_accuracy_payload or {}

    findings_summary = _summarise_findings(findings_payload)
    outcomes_summary = _summarise_outcomes(outcomes_payload)
    clusters_summary = _summarise_clusters(clusters_payload)
    architect_accuracy_summary = _summarise_architect_accuracy(
        architect_accuracy_payload
    )

    correlated_bias_count = _set_intersection_size(
        findings_summary["top_critical_architects"],
        architect_accuracy_summary["most_biased_architects"],
    )

    outcome_attached = (
        architect_accuracy_summary["outcome_attached_sim_count"]
    )
    simulations_with_findings = (
        findings_summary["simulations_with_findings"]
    )
    # Coverage = sims that have BOTH findings AND outcome. We
    # approximate via min(of-with-findings, of-with-outcome) when
    # the two sets aren't directly comparable — the route layer
    # could pass a precise count, but for the summary tile this
    # lower bound is sufficient.
    if simulation_count > 0:
        data_quality_score = (
            min(outcome_attached, simulations_with_findings)
            / simulation_count
        )
        # Clamp to [0, 1] — a defensive guard in case the route
        # accidentally passes a count > simulation_count.
        if data_quality_score > 1.0:
            data_quality_score = 1.0
        if data_quality_score < 0.0:
            data_quality_score = 0.0
    else:
        data_quality_score = 0.0

    overall_health = _overall_health(
        confidence_label=outcomes_summary["confidence_label"],
        needs_attention_count=(
            clusters_summary["needs_attention_count"]
        ),
        correlated_bias_count=correlated_bias_count,
        outcome_attached_count=outcome_attached,
        simulation_count=simulation_count,
    )

    key_recommendations = _build_recommendations(
        findings=findings_summary,
        outcomes=outcomes_summary,
        clusters=clusters_summary,
        architect_accuracy=architect_accuracy_summary,
        correlated_bias_count=correlated_bias_count,
        data_quality_score=data_quality_score,
        simulation_count=simulation_count,
    )
    next_action = _next_action(overall_health)

    return {
        "simulation_count": simulation_count,
        "findings_summary": findings_summary,
        "outcomes_summary": outcomes_summary,
        "clusters_summary": clusters_summary,
        "architect_accuracy_summary": architect_accuracy_summary,
        "correlated_bias_count": correlated_bias_count,
        "data_quality_score": round(data_quality_score, 6),
        "overall_health": overall_health,
        "key_recommendations": key_recommendations,
        "next_action": next_action,
    }


__all__ = [
    "LABEL_HEALTHY",
    "LABEL_NEEDS_ATTENTION",
    "LABEL_CRITICAL",
    "LABEL_INSUFFICIENT_DATA",
    "VALID_HEALTH_LABELS",
    "NEXT_ACTION_CRITICAL",
    "NEXT_ACTION_NEEDS_ATTENTION",
    "NEXT_ACTION_HEALTHY",
    "NEXT_ACTION_INSUFFICIENT_DATA",
    "VALID_NEXT_ACTIONS",
    "MAX_RECOMMENDATIONS",
    "build_portfolio_summary",
    "portfolio_to_csv",
]