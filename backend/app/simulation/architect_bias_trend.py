"""
Pure helpers for the per-architect bias trend endpoint.

When the architect-accuracy bridge surfaces a biased
architect (e.g. PricingArchitect with OVER_PREDICTS), the
founder wants to see whether the bias is recent or has been
there all along. The per-cluster trend endpoint answers
this for clusters; this sibling answers it for architects.

The helper takes a sequence of
``(created_at, predicted, actual, findings)`` rows and bins
the named architect's per-sim ``calibration_variance``
(predicted − actual, taken only on sims where the architect
flagged findings) by month / week / day.

Pure-Python (no SQL, no I/O) — the route layer joins
``simulations`` with ``outcomes`` and ``domain_findings``
before invoking.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime

# Reuse the bin / trend constants from cluster_trend so the
# dashboard's wording stays consistent.
from app.simulation.cluster_trend import (
    BIN_DAY,
    BIN_MONTH,
    BIN_WEEK,
    STABLE_DELTA_THRESHOLD,
    TREND_STABLE,
    TREND_UNKNOWN,
    _bin_key,
    _bin_sort_key,
    normalise_bin,
)

# Bias-direction labels — distinct from the cluster trend
# direction labels because the semantics differ: cluster
# trend tracks conversion (UP = good), bias trend tracks
# |calibration_variance| (DOWN = good, the bias is shrinking).
LABEL_IMPROVING: str = "IMPROVING"
LABEL_DEGRADING: str = "DEGRADING"
LABEL_STABLE: str = "STABLE"
LABEL_WELL_CALIBRATED: str = "WELL_CALIBRATED"
LABEL_BIASED: str = "BIASED"
LABEL_UNKNOWN: str = "UNKNOWN"
VALID_BIAS_LABELS: frozenset[str] = frozenset({
    LABEL_IMPROVING,
    LABEL_DEGRADING,
    LABEL_STABLE,
    LABEL_WELL_CALIBRATED,
    LABEL_BIASED,
    LABEL_UNKNOWN,
})


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float or return None."""
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


def _architect_flagged(
    findings: list[dict],
    architect_name: str,
) -> bool:
    """True when any finding in the list was emitted by the
    named architect."""
    target = architect_name.casefold()
    for f in findings:
        if not isinstance(f, dict):
            continue
        if str(f.get("architect_name", "")).casefold() == target:
            return True
    return False


def _direction_from_variance(
    first_abs: float | None, last_abs: float | None
) -> str:
    """Translate |variance| delta into a bias-direction label.

    IMPROVING when the bias shrank (|variance_last| <
    |variance_first|). DEGRADING when it grew. STABLE within
    :data:`STABLE_DELTA_THRESHOLD`. UNKNOWN when either side
    is missing.
    """
    if first_abs is None or last_abs is None:
        return TREND_UNKNOWN
    delta = last_abs - first_abs
    if abs(delta) < STABLE_DELTA_THRESHOLD:
        return TREND_STABLE
    if delta < 0:
        return LABEL_IMPROVING
    return LABEL_DEGRADING


def _bias_label(mean_abs_variance: float | None) -> str:
    """Bucket the absolute variance into a wellness label.

    Below 2pp → WELL_CALIBRATED. Above → BIASED. None →
    UNKNOWN (no data).
    """
    if mean_abs_variance is None:
        return LABEL_UNKNOWN
    if mean_abs_variance < 0.02:
        return LABEL_WELL_CALIBRATED
    return LABEL_BIASED


def build_architect_bias_trend(
    architect_name: str,
    rows: list[
        tuple[object, object, object, list[dict] | None]
    ],
    *,
    bin_size: str = BIN_MONTH,
) -> dict:
    """Build the per-architect bias-trend payload.

    Args:
        architect_name: the canonical architect name
            (PascalCase). Case-insensitive match against
            findings.
        rows: list of ``(created_at, predicted, actual,
            findings)`` tuples. ``created_at`` may be a
            datetime (preferred) or ISO 8601 string.
            ``predicted`` / ``actual`` may be None (missing
            outcome → sim skipped). ``findings`` is the list
            of finding dicts from the sim's
            ``domain_findings``.
        bin_size: ``BIN_MONTH`` (default) / ``BIN_WEEK`` /
            ``BIN_DAY``.

    Returns:
        A dict matching :class:`ArchitectBiasTrendOut`:

        * ``architect_name`` / ``bin_size`` — echoed.
        * ``bins`` — per-bin dict sorted chronologically.
          Each row: ``bin``, ``bin_start`` (ISO 8601 UTC),
          ``mean_abs_variance``, ``mean_signed_variance``,
          ``observation_count``.
        * ``overall_direction`` — IMPROVING / DEGRADING /
          STABLE bucketed from first vs last bin's
          |variance|.
        * ``first_bin_abs_variance`` /
          ``last_bin_abs_variance`` — for the dashboard's
          headline ("X% → Y%").
        * ``mean_abs_delta`` — last − first, or None when
          fewer than 2 bins have data.
        * ``current_bias_label`` — WELL_CALIBRATED / BIASED /
          UNKNOWN bucketed from the LAST bin's
          |variance|.
    """
    effective_bin = normalise_bin(bin_size)
    bins: dict[str, dict] = {}
    for created_at, predicted, actual, findings in rows:
        # Normalise created_at to UTC datetime.
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

        # Sim must have a numeric predicted + actual outcome.
        pred = _safe_float(predicted)
        act = _safe_float(actual)
        if pred is None or act is None:
            continue
        # Sim must have at least one finding from the named
        # architect.
        if not _architect_flagged(findings or [], architect_name):
            continue

        variance = pred - act
        key = _bin_key(dt, effective_bin)
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

        slot = bins.setdefault(
            key,
            {
                "bin": key,
                "bin_start": ts.isoformat(),
                "abs_variances": [],
                "signed_variances": [],
            },
        )
        slot["abs_variances"].append(abs(variance))
        slot["signed_variances"].append(variance)

    rows_out: list[dict] = []
    for key in sorted(
        bins.keys(), key=lambda k: _bin_sort_key(k, effective_bin)
    ):
        slot = bins[key]
        abs_vals = slot["abs_variances"]
        signed_vals = slot["signed_variances"]
        mean_abs = sum(abs_vals) / len(abs_vals) if abs_vals else 0.0
        mean_signed = (
            sum(signed_vals) / len(signed_vals)
            if signed_vals
            else 0.0
        )
        rows_out.append({
            "bin": key,
            "bin_start": slot["bin_start"],
            "mean_abs_variance": round(mean_abs, 6),
            "mean_signed_variance": round(mean_signed, 6),
            "observation_count": len(abs_vals),
        })

    # Direction from first to last bin's |variance|.
    if len(rows_out) < 2:
        mean_delta = None
        first_abs = (
            rows_out[0]["mean_abs_variance"] if rows_out else None
        )
        last_abs = first_abs
    else:
        first_abs = rows_out[0]["mean_abs_variance"]
        last_abs = rows_out[-1]["mean_abs_variance"]
        mean_delta = round(last_abs - first_abs, 6)

    overall = _direction_from_variance(first_abs, last_abs)
    current_bias_label = _bias_label(last_abs)

    # Per-bin bias direction distribution. Each bin is
    # classified by its signed mean_variance:
    #   signed > 0 → OVER_PREDICTS (model over-promised)
    #   signed < 0 → UNDER_PREDICTS (model under-promised)
    #   signed == 0 → BALANCED
    # The dashboard uses this to render "this architect has
    # over-predicted in 3 of 5 bins" without iterating.
    direction_distribution = {
        "over_predicts": 0,
        "under_predicts": 0,
        "balanced": 0,
    }
    for r in rows_out:
        signed = r["mean_signed_variance"]
        if signed > 0:
            direction_distribution["over_predicts"] += 1
        elif signed < 0:
            direction_distribution["under_predicts"] += 1
        else:
            direction_distribution["balanced"] += 1

    # Peak bias bin — the bin with the highest
    # mean_abs_variance. Tiebreaker: latest bin_start (stable).
    # ``None`` when no bins have data.
    peak_payload: dict | None = None
    if rows_out:
        peak_row = max(
            rows_out,
            key=lambda r: (r["mean_abs_variance"], r["bin_start"]),
        )
        signed = peak_row["mean_signed_variance"]
        if signed > 0:
            peak_direction = "OVER_PREDICTS"
        elif signed < 0:
            peak_direction = "UNDER_PREDICTS"
        else:
            peak_direction = "BALANCED"
        peak_payload = {
            "bin": peak_row["bin"],
            "bin_start": peak_row["bin_start"],
            "mean_abs_variance": peak_row["mean_abs_variance"],
            "mean_signed_variance": peak_row["mean_signed_variance"],
            "direction": peak_direction,
        }

    return {
        "architect_name": architect_name,
        "bin_size": effective_bin,
        "bins": rows_out,
        "overall_direction": overall,
        "first_bin_abs_variance": (
            round(first_abs, 6) if first_abs is not None else None
        ),
        "last_bin_abs_variance": (
            round(last_abs, 6) if last_abs is not None else None
        ),
        "mean_abs_delta": mean_delta,
        "current_bias_label": current_bias_label,
        "bias_direction_distribution": direction_distribution,
        "peak_bias_bin": peak_payload,
    }


def _timedelta(**kwargs):
    from datetime import timedelta
    return timedelta(**kwargs)


__all__ = [
    "LABEL_IMPROVING",
    "LABEL_DEGRADING",
    "LABEL_STABLE",
    "LABEL_WELL_CALIBRATED",
    "LABEL_BIASED",
    "LABEL_UNKNOWN",
    "VALID_BIAS_LABELS",
    "build_architect_bias_trend",
]
