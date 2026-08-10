"""
Statistical A/B test analysis for real-world landing-page experiments.

The simulation stack tells a founder *what to test* (pricing, messaging,
onboarding copy) and the validation-experiment planner says *how to run* a
concrete test. This module closes the loop: given two observed arms
(``visitors`` / ``conversions``), it computes whether the difference is
statistically meaningful and how much more traffic is needed.

Methodology
-----------

* Two-proportion z-test on the pooled conversion rate, with a two-sided
  p-value (conservative: no directional shortcut).
* A normal-approximation confidence interval for the absolute conversion
  uplift ``p_b - p_a``.
* Sample-size guidance via the standard two-proportion power formula
  (equal arms), computed both for the *observed* uplift and for a caller
  supplied minimum detectable effect (MDE).
* Verdict buckets: ``SIGNIFICANT`` (p < alpha), ``TRENDING``
  (alpha <= p < 0.20), ``INCONCLUSIVE`` (p >= 0.20), and
  ``INSUFFICIENT_DATA`` (too few visitors to justify any claim).

The module is pure (no DB, no I/O, no LLM) and deliberately conservative:
it refuses to report p-values for tiny samples, rejects malformed counts
instead of inventing numbers, and clamps every derived value to a finite
range so a bad observation can never poison the response.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from scipy.stats import norm

# ---------------------------------------------------------------------------
# Verdicts and thresholds
# ---------------------------------------------------------------------------

VERDICT_SIGNIFICANT: str = "SIGNIFICANT"
VERDICT_TRENDING: str = "TRENDING"
VERDICT_INCONCLUSIVE: str = "INCONCLUSIVE"
VERDICT_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VALID_VERDICTS: frozenset[str] = frozenset({
    VERDICT_SIGNIFICANT,
    VERDICT_TRENDING,
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT_DATA,
})

# Below these visitor counts the test does not yet justify a p-value: a
# founder could accidentally chase noise in the first few dozen sessions.
MIN_TOTAL_VISITORS: int = 40
MIN_VISITORS_PER_VARIANT: int = 10

# A p-value below this is called SIGNIFICANT; below this higher bound it is
# TRENDING (worth keeping the test running, not worth shipping on yet).
ALPHA_DEFAULT: float = 0.05
TRENDING_P_MAX: float = 0.20

# Sample-size recommendation defaults.
POWER_DEFAULT: float = 0.80
MDE_DEFAULT: float = 0.02

# Signal severity buckets — consistent with the rest of the dashboard.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


@dataclass(frozen=True)
class ExperimentVariant:
    """One normalised test arm."""

    label: str
    visitors: int
    conversions: int


# ---------------------------------------------------------------------------
# Defensive coercion helpers
# ---------------------------------------------------------------------------

def _safe_int(value: Any, default: int | None = None) -> int | None:
    """Coerce a count to an int, rejecting bools and non-integral floats."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return default
        value = int(value)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(
    value: Any,
    default: float | None = None,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> float | None:
    """Coerce a finite float within ``[lower, upper]`` or return default."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    if lower is not None and parsed < lower:
        return default
    if upper is not None and parsed > upper:
        return default
    return parsed


def _label(raw: Any, fallback: str) -> str:
    """Normalise a variant label to a bounded non-empty string."""
    text = str(raw or "").strip()
    if not text:
        text = fallback
    return text[:80]


def _normalise_variant(
    raw: Any,
    *,
    fallback_label: str,
) -> ExperimentVariant | None:
    """Parse a variant (dict or object) into counts, or ``None`` when unusable.

    A variant is unusable when its visitors/conversions are missing,
    non-integral, negative, or when conversions exceed visitors — the
    caller treats ``None`` as ``INSUFFICIENT_DATA`` rather than raising so a
    malformed row can never 500 the endpoint.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        label = _label(raw.get("label"), fallback_label)
        visitors = _safe_int(raw.get("visitors"))
        conversions = _safe_int(raw.get("conversions"))
    else:
        label = _label(getattr(raw, "label", None), fallback_label)
        visitors = _safe_int(getattr(raw, "visitors", None))
        conversions = _safe_int(getattr(raw, "conversions", None))
    if visitors is None or conversions is None:
        return None
    if visitors < 1 or conversions < 0:
        return None
    if conversions > visitors:
        return None
    return ExperimentVariant(
        label=label,
        visitors=visitors,
        conversions=conversions,
    )


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


# ---------------------------------------------------------------------------
# Sample-size and inference helpers
# ---------------------------------------------------------------------------

def _z_alpha(alpha: float) -> float:
    """Two-sided critical value for the configured alpha."""
    return float(norm.ppf(1.0 - alpha / 2.0))


def _z_beta(power: float) -> float:
    """One-sided critical value for the configured power."""
    return float(norm.ppf(power))


def _pooled_rate(a: ExperimentVariant, b: ExperimentVariant) -> float:
    return (a.conversions + b.conversions) / (a.visitors + b.visitors)


def _two_proportion_p_value(
    a: ExperimentVariant,
    b: ExperimentVariant,
) -> tuple[float | None, float | None]:
    """Return ``(z_score, two_sided_p)`` or ``(None, None)`` when undefined."""
    pa = a.conversions / a.visitors
    pb = b.conversions / b.visitors
    pooled = _pooled_rate(a, b)
    denominator = math.sqrt(
        pooled * (1.0 - pooled) * (1.0 / a.visitors + 1.0 / b.visitors)
    )
    if denominator == 0.0:
        return 0.0, 1.0
    z = (pb - pa) / denominator
    p = 2.0 * (1.0 - float(norm.cdf(abs(z))))
    # Clamp to the mathematically possible range — floating point can
    # produce 2.0 (or -0.0) at the tails.
    return z, max(0.0, min(1.0, p))


def _uplift_ci(
    a: ExperimentVariant,
    b: ExperimentVariant,
    alpha: float,
) -> tuple[float, float]:
    """Normal-approximation CI for ``p_b - p_a``, clamped to ``[-1, 1]``."""
    pa = a.conversions / a.visitors
    pb = b.conversions / b.visitors
    se = math.sqrt(
        pa * (1.0 - pa) / a.visitors
        + pb * (1.0 - pb) / b.visitors
    )
    half_width = _z_alpha(alpha) * se
    low = max(-1.0, (pb - pa) - half_width)
    high = min(1.0, (pb - pa) + half_width)
    return low, high


def _visitors_per_arm(
    control_rate: float,
    effect: float,
    alpha: float,
    power: float,
) -> int:
    """Equal-arm sample size to detect ``effect`` at alpha/power."""
    if effect <= 0.0:
        return 0
    variant_rate = min(0.9999, control_rate + effect)
    pooled = (control_rate + variant_rate) / 2.0
    z_alpha = _z_alpha(alpha)
    z_beta = _z_beta(power)
    numerator = (
        z_alpha * math.sqrt(2.0 * pooled * (1.0 - pooled))
        + z_beta * math.sqrt(
            control_rate * (1.0 - control_rate)
            + variant_rate * (1.0 - variant_rate)
        )
    ) ** 2
    return max(1, int(math.ceil(numerator / (effect ** 2))))


# ---------------------------------------------------------------------------
# Verdict / narrative builders
# ---------------------------------------------------------------------------

def _verdict(
    p_value: float | None,
    alpha: float,
    a: ExperimentVariant,
    b: ExperimentVariant,
) -> str:
    if p_value is None:
        return VERDICT_INSUFFICIENT_DATA
    if a.conversions == b.conversions == 0:
        return VERDICT_INCONCLUSIVE
    if p_value < alpha:
        return VERDICT_SIGNIFICANT
    if p_value < TRENDING_P_MAX:
        return VERDICT_TRENDING
    return VERDICT_INCONCLUSIVE


def _winner_label(a: ExperimentVariant, b: ExperimentVariant) -> str | None:
    pa = a.conversions / a.visitors
    pb = b.conversions / b.visitors
    if pb > pa:
        return b.label
    if pa > pb:
        return a.label
    return None


def _narrative(
    a: ExperimentVariant,
    b: ExperimentVariant,
    *,
    verdict: str,
    winner: str | None,
    p_value: float | None,
    uplift: float | None,
    alpha: float,
) -> str:
    if verdict == VERDICT_INSUFFICIENT_DATA:
        return (
            f"Not enough traffic yet — {a.visitors} visitor(s) on "
            f"{a.label!r} and {b.visitors} on {b.label!r} do not justify a "
            f"significance claim. Aim for at least {MIN_TOTAL_VISITORS} "
            f"total visitors (min {MIN_VISITORS_PER_VARIANT} per arm) "
            "before trusting the numbers."
        )
    if p_value is None or uplift is None:
        return "The test could not be scored — check the recorded counts."
    if verdict == VERDICT_SIGNIFICANT and winner is not None:
        return (
            f"{winner!r} is statistically significant at alpha={alpha:.2f} "
            f"(p={p_value:.4f}, absolute uplift {uplift:+.2%}). Ship it, but "
            "keep the post-launch outcome tracker running to confirm in "
            "production."
        )
    if verdict == VERDICT_TRENDING:
        return (
            f"{winner or 'Neither variant'} is ahead but not conclusive "
            f"(p={p_value:.4f}) — keep the test running before shipping."
        )
    return (
        "No meaningful difference detected "
        f"(p={p_value:.4f}) — consider more traffic, a bigger change, or a "
        "different hypothesis."
    )


def _recommendations(
    a: ExperimentVariant,
    b: ExperimentVariant,
    *,
    verdict: str,
    winner: str | None,
    uplift: float | None,
    needed_observed: int | None,
    needed_mde: int | None,
    mde: float,
) -> list[str]:
    out: list[str] = []
    if verdict == VERDICT_SIGNIFICANT and winner is not None:
        out.append(
            f"Adopt {winner!r} as the winning variant"
            + (
                f" ({uplift:+.2%} absolute conversion uplift)."
                if uplift is not None
                else "."
            )
        )
        out.append(
            "Record real outcomes against the chosen variant so the "
            "simulation's next calibration pass can learn from it."
        )
    elif verdict == VERDICT_TRENDING:
        out.append(
            f"Keep the test running — {winner or 'the leading variant'} is "
            "ahead but has not crossed the significance threshold yet."
        )
        if needed_observed is not None and needed_observed > 0:
            out.append(
                f"Roughly {needed_observed} visitor(s) per arm would give "
                "this test enough power to confirm the observed uplift."
            )
    elif verdict == VERDICT_INCONCLUSIVE:
        out.append(
            "No statistically meaningful difference yet — either gather "
            "more traffic, test a more impactful change, or accept the "
            "variants as equivalent."
        )
        if needed_mde is not None and needed_mde > 0:
            out.append(
                f"To detect a {mde:.1%} minimum uplift, plan for "
                f"roughly {needed_mde} visitor(s) per arm."
            )
    else:
        out.append(
            "Gather more traffic before drawing conclusions — a handful of "
            "sessions can look like a winner by pure chance."
        )
        if needed_mde is not None and needed_mde > 0:
            out.append(
                f"For a {mde:.1%} minimum detectable effect, plan "
                f"for roughly {needed_mde} visitor(s) per arm."
            )
    return out


def _variant_summary(raw: Any, fallback_label: str) -> dict[str, Any]:
    """Render a defensive variant summary even when the counts are bad."""
    if isinstance(raw, dict):
        label = _label(raw.get("label"), fallback_label)
        visitors = _safe_int(raw.get("visitors"), 0)
        conversions = _safe_int(raw.get("conversions"), 0)
    else:
        label = _label(getattr(raw, "label", None), fallback_label)
        visitors = _safe_int(getattr(raw, "visitors", None), 0)
        conversions = _safe_int(getattr(raw, "conversions", None), 0)
    return {
        "label": label,
        "visitors": max(0, visitors or 0),
        "conversions": max(0, conversions or 0),
        "conversion_rate": 0.0,
    }


def _severity_for_verdict(verdict: str) -> str:
    if verdict == VERDICT_SIGNIFICANT:
        return SIGNAL_OK
    if verdict in {VERDICT_TRENDING, VERDICT_INCONCLUSIVE}:
        return SIGNAL_WATCH
    return SIGNAL_CRITICAL


def _key_signals(
    *,
    verdict: str,
    winner: str | None,
    p_value: float | None,
    uplift: float | None,
    sample_size_sufficient: bool,
) -> list[dict[str, Any]]:
    verdict_severity = _severity_for_verdict(verdict)
    return [
        {
            "label": "verdict",
            "value": verdict,
            "severity": verdict_severity,
        },
        {
            "label": "winner",
            "value": winner,
            "severity": SIGNAL_OK if winner is not None else SIGNAL_WATCH,
        },
        {
            "label": "p_value",
            "value": _round(p_value, 6),
            "severity": (
                SIGNAL_OK
                if p_value is not None and p_value < ALPHA_DEFAULT
                else SIGNAL_WATCH
            ),
        },
        {
            "label": "absolute_uplift",
            "value": _round(uplift, 6),
            "severity": (
                SIGNAL_OK
                if uplift is not None and abs(uplift) > 0.0
                else SIGNAL_WATCH
            ),
        },
        {
            "label": "sample_size_sufficient",
            "value": sample_size_sufficient,
            "severity": (
                SIGNAL_OK if sample_size_sufficient else SIGNAL_WATCH
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_ab_test(
    variant_a: Any,
    variant_b: Any,
    *,
    alpha: float = ALPHA_DEFAULT,
    power: float = POWER_DEFAULT,
    mde: float = MDE_DEFAULT,
) -> dict[str, Any]:
    """Analyse two observed A/B arms and return a founder-ready verdict.

    Args:
        variant_a: first arm (dict or object with ``label``, ``visitors``,
            ``conversions``).
        variant_b: second arm (same shape).
        alpha: significance level in ``(0, 1)``.
        power: statistical power in ``(0, 1)``.
        mde: minimum detectable absolute effect in ``(0, 0.5]`` used when
            the observed uplift is too small (or absent) to power the
            sample-size recommendation.

    Returns:
        Dict matching :class:`AbTestAnalysisOut`.
    """
    safe_alpha = _safe_float(alpha, lower=0.0, upper=1.0)
    safe_power = _safe_float(power, lower=0.0, upper=1.0)
    safe_mde = _safe_float(mde, lower=0.0, upper=0.5)
    if safe_alpha is None or safe_power is None or safe_mde is None:
        raise ValueError(
            "alpha, power, and mde must be finite and within (0, 1) / "
            "(0, 0.5]"
        )
    if safe_alpha <= 0.0 or safe_alpha >= 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if safe_power <= 0.0 or safe_power >= 1.0:
        raise ValueError("power must be in (0, 1)")
    if safe_mde <= 0.0:
        raise ValueError("mde must be positive")

    a = _normalise_variant(variant_a, fallback_label="Control")
    b = _normalise_variant(variant_b, fallback_label="Variant")
    if a is None or b is None:
        malformed = "Both arms" if a is None and b is None else (
            "Arm A" if a is None else "Arm B"
        )
        return {
            "variant_a": _variant_summary(variant_a, "Control"),
            "variant_b": _variant_summary(variant_b, "Variant"),
            "winner": None,
            "pooled_conversion_rate": 0.0,
            "absolute_uplift": 0.0,
            "relative_uplift_pct": None,
            "z_score": None,
            "p_value": None,
            "confidence_interval": {"low": None, "high": None},
            "verdict": VERDICT_INSUFFICIENT_DATA,
            "significant": False,
            "confidence_level": round(1.0 - safe_alpha, 6),
            "visitors_needed_for_observed_uplift": None,
            "visitors_needed_for_mde": None,
            "narrative": (
                f"{malformed} has unusable visitor/conversion counts — "
                "conversions must be a finite whole number between 0 and "
                "visitors, and visitors must be at least 1."
            ),
            "recommendations": [
                "Fix the recorded counts and re-run the analysis."
            ],
            "key_signals": [
                {
                    "label": "verdict",
                    "value": VERDICT_INSUFFICIENT_DATA,
                    "severity": SIGNAL_CRITICAL,
                }
            ],
            "meta": {
                "alpha": safe_alpha,
                "power": safe_power,
                "mde": safe_mde,
                "min_total_visitors": MIN_TOTAL_VISITORS,
                "min_visitors_per_variant": MIN_VISITORS_PER_VARIANT,
                "malformed_input": True,
            },
        }

    total_visitors = a.visitors + b.visitors
    if (
        total_visitors < MIN_TOTAL_VISITORS
        or a.visitors < MIN_VISITORS_PER_VARIANT
        or b.visitors < MIN_VISITORS_PER_VARIANT
    ):
        pa = a.conversions / a.visitors
        pb = b.conversions / b.visitors
        uplift = pb - pa
        verdict = VERDICT_INSUFFICIENT_DATA
        needed_mde = _visitors_per_arm(
            pa, safe_mde, safe_alpha, safe_power
        )
        return {
            "variant_a": {
                "label": a.label,
                "visitors": a.visitors,
                "conversions": a.conversions,
                "conversion_rate": _round(pa),
            },
            "variant_b": {
                "label": b.label,
                "visitors": b.visitors,
                "conversions": b.conversions,
                "conversion_rate": _round(pb),
            },
            "winner": None,
            "pooled_conversion_rate": _round(_pooled_rate(a, b)),
            "absolute_uplift": _round(uplift),
            "relative_uplift_pct": (
                round((uplift / pa) * 100.0, 2) if pa > 0.0 else None
            ),
            "z_score": None,
            "p_value": None,
            "confidence_interval": {"low": None, "high": None},
            "verdict": verdict,
            "significant": False,
            "confidence_level": round(1.0 - safe_alpha, 6),
            "visitors_needed_for_observed_uplift": None,
            "visitors_needed_for_mde": needed_mde,
            "narrative": _narrative(
                a,
                b,
                verdict=verdict,
                winner=None,
                p_value=None,
                uplift=uplift,
                alpha=safe_alpha,
            ),
            "recommendations": _recommendations(
                a,
                b,
                verdict=verdict,
                winner=None,
                uplift=uplift,
                needed_observed=None,
                needed_mde=needed_mde,
                mde=safe_mde,
            ),
            "key_signals": _key_signals(
                verdict=verdict,
                winner=None,
                p_value=None,
                uplift=uplift,
                sample_size_sufficient=False,
            ),
            "meta": {
                "alpha": safe_alpha,
                "power": safe_power,
                "mde": safe_mde,
                "min_total_visitors": MIN_TOTAL_VISITORS,
                "min_visitors_per_variant": MIN_VISITORS_PER_VARIANT,
                "current_total_visitors": total_visitors,
                "malformed_input": False,
            },
        }

    pa = a.conversions / a.visitors
    pb = b.conversions / b.visitors
    uplift = pb - pa
    z_score, p_value = _two_proportion_p_value(a, b)
    low, high = _uplift_ci(a, b, safe_alpha)
    verdict = _verdict(p_value, safe_alpha, a, b)
    winner = _winner_label(a, b)

    needed_observed = None
    if uplift > 0.0:
        needed_observed = _visitors_per_arm(pa, uplift, safe_alpha, safe_power)
    needed_mde = _visitors_per_arm(pa, safe_mde, safe_alpha, safe_power)
    sample_size_sufficient = (
        needed_mde > 0
        and a.visitors >= needed_mde
        and b.visitors >= needed_mde
    )

    return {
        "variant_a": {
            "label": a.label,
            "visitors": a.visitors,
            "conversions": a.conversions,
            "conversion_rate": _round(pa),
        },
        "variant_b": {
            "label": b.label,
            "visitors": b.visitors,
            "conversions": b.conversions,
            "conversion_rate": _round(pb),
        },
        "winner": winner,
        "pooled_conversion_rate": _round(_pooled_rate(a, b)),
        "absolute_uplift": _round(uplift),
        "relative_uplift_pct": (
            round((uplift / pa) * 100.0, 2) if pa > 0.0 else None
        ),
        "z_score": _round(z_score, 4),
        "p_value": _round(p_value, 6),
        "confidence_interval": {
            "low": _round(low),
            "high": _round(high),
        },
        "verdict": verdict,
        "significant": verdict == VERDICT_SIGNIFICANT,
        "confidence_level": round(1.0 - safe_alpha, 6),
        "visitors_needed_for_observed_uplift": needed_observed,
        "visitors_needed_for_mde": needed_mde,
        "narrative": _narrative(
            a,
            b,
            verdict=verdict,
            winner=winner,
            p_value=p_value,
            uplift=uplift,
            alpha=safe_alpha,
        ),
        "recommendations": _recommendations(
            a,
            b,
            verdict=verdict,
            winner=winner,
            uplift=uplift,
            needed_observed=needed_observed,
            needed_mde=needed_mde,
            mde=safe_mde,
        ),
        "key_signals": _key_signals(
            verdict=verdict,
            winner=winner,
            p_value=p_value,
            uplift=uplift,
            sample_size_sufficient=sample_size_sufficient,
        ),
        "meta": {
            "alpha": safe_alpha,
            "power": safe_power,
            "mde": safe_mde,
            "min_total_visitors": MIN_TOTAL_VISITORS,
            "min_visitors_per_variant": MIN_VISITORS_PER_VARIANT,
            "current_total_visitors": total_visitors,
            "malformed_input": False,
        },
    }


__all__ = [
    "ALPHA_DEFAULT",
    "ExperimentVariant",
    "MDE_DEFAULT",
    "MIN_TOTAL_VISITORS",
    "MIN_VISITORS_PER_VARIANT",
    "POWER_DEFAULT",
    "TRENDING_P_MAX",
    "VALID_VERDICTS",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_INSUFFICIENT_DATA",
    "VERDICT_SIGNIFICANT",
    "VERDICT_TRENDING",
    "analyze_ab_test",
]
