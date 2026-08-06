"""
Pure unit-economics analysis for completed simulation results.

Answers the founder's "is this business profitable per customer?" question
by combining three simulation signals into dollar-agnostic unit economics:

* **Price** — ``PricingArchitect.price_ceiling`` says what each cluster will
  actually pay; the effective price is ``min(AOV, ceiling)`` so clusters that
  cannot afford the list price are priced at their ceiling instead of being
  silently counted at full AOV.
* **Retention** — ``RetentionArchitect`` day-30/day-90 survival is
  extrapolated into an expected lifetime (months) with a constant monthly
  retention rate, capped at 120 months.
* **Acquisition cost** — the channel-attribution engine's per-cluster
  ``cac_multiplier`` scales the founder's blended CAC (or a derived
  default of half an average order) so organic-led clusters are cheaper to
  acquire than paid-led ones.

Each cluster then gets ``LTV`` (contribution x lifetime), ``CAC``,
``LTV:CAC``, ``payback_months`` and a health verdict; market-level reads are
demand-weighted (population weight x realised conversion) so a cluster that
barely converts cannot dominate the blended verdict. CAC scenarios show what
the blended ratio looks like if acquisition cost scales 0.5x-3x, and price
scenarios show the mechanical per-customer effect of -20%/+20% price moves
(explicitly holding retention and conversion volume constant).

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect metrics)
and ``cluster_registry``; all arithmetic is deterministic.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.unit_economics import (
    CacScenario,
    ClusterUnitEconomics,
    PriceScenario,
    UnitEconomicsOut,
)

# Defaults for founder-supplied assumptions. The CAC default (half an
# average order per acquisition) is a conservative early-stage baseline —
# pass the real blended CAC to get actionable numbers.
DEFAULT_GROSS_MARGIN: float = 0.60
DEFAULT_PURCHASE_FREQUENCY_PER_YEAR: float = 12.0
DEFAULT_CAC_FRACTION_OF_AOV: float = 0.5

LTV_CAC_TARGET: float = 3.0
MAX_LIFETIME_MONTHS: float = 120.0
MAX_PAYBACK_MONTHS: float = 18.0

VERDICT_STRONG: str = "STRONG"
VERDICT_VIABLE: str = "VIABLE"
VERDICT_MARGINAL: str = "MARGINAL"
VERDICT_UNPROFITABLE: str = "UNPROFITABLE"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

STRONG_RATIO: float = 3.0
VIABLE_RATIO: float = 1.5
MARGINAL_RATIO: float = 1.0

CAC_SCENARIO_MULTIPLIERS: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0)
PRICE_SCENARIO_MULTIPLIERS: tuple[tuple[str, float], ...] = (
    ("PRICE_DOWN_20", 0.8),
    ("BASE_PRICE", 1.0),
    ("PRICE_UP_20", 1.2),
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _cluster_rate(raw: Any) -> float:
    """Extract a clamped conversion rate from a cluster breakdown entry."""
    if raw is None:
        return 0.0
    if isinstance(raw, dict):
        rate = raw.get("conversion_rate")
        if rate is None:
            rate = raw.get("conversion")
    else:
        rate = raw
    return max(0.0, min(1.0, _safe_float(rate)))


def _channel_map(
    conductor_results: dict[str, Any] | None,
    cluster_registry: list[dict[str, Any]],
    product_type: str,
) -> dict[str, tuple[str, float]]:
    """Per-cluster ``(primary_channel, cac_multiplier)`` via the channel engine.

    Falls back to neutral ``("", 1.0)`` values when the engine cannot run
    (malformed conductor payloads) so unit economics still render.
    """
    if not conductor_results:
        return {}
    try:
        from app.simulation.channel_attribution import ChannelAttributionEngine

        result = ChannelAttributionEngine().generate(
            generated_ui_id=0,
            conductor_results=conductor_results,
            cluster_registry=cluster_registry,
            product_type=product_type,
        )
    except (TypeError, ValueError, KeyError):
        return {}
    mapping: dict[str, tuple[str, float]] = {}
    for profile in result.cluster_profiles:
        multiplier = max(0.1, _safe_float(profile.cac_multiplier, 1.0))
        mapping[profile.cluster_id] = (
            str(profile.primary_channel or ""),
            multiplier,
        )
    return mapping


def _pricing_metrics(arch: dict[str, Any]) -> dict[str, Any]:
    return arch.get("PricingArchitect", {}).get("metrics", {}) or {}


def _retention_metrics(arch: dict[str, Any]) -> dict[str, Any]:
    return arch.get("RetentionArchitect", {}).get("metrics", {}) or {}


def _lifetime_months(day30: float, day90: float) -> float:
    """Expected months a customer stays, from the day-30/90 survival curve.

    Monthly retention ``r = (day90/day30)^(1/2)`` (two months elapse between
    the two observations); survival at month ``m`` is ``day30 * r^(m-1)`` so
    expected lifetime is ``day30 / (1 - r)``, capped at 120 months.
    """
    if day30 <= 0.0:
        return 0.0
    if day90 >= day30:
        # Flat/improving survival — treat as near-perfect retention rather
        # than dividing by zero.
        monthly_retention = 0.99
    else:
        monthly_retention = math.sqrt(day90 / day30)
        monthly_retention = max(0.0, min(0.99, monthly_retention))
    return round(min(MAX_LIFETIME_MONTHS, day30 / (1.0 - monthly_retention)), 2)


def _verdict(ratio: float, ltv: float) -> str:
    if ltv <= 0.0 or ratio < MARGINAL_RATIO:
        return VERDICT_UNPROFITABLE
    if ratio >= STRONG_RATIO:
        return VERDICT_STRONG
    if ratio >= VIABLE_RATIO:
        return VERDICT_VIABLE
    return VERDICT_MARGINAL


def _weighted_sum(weights: dict[str, float], values: dict[str, float]) -> float:
    return sum(w * values.get(cid, 0.0) for cid, w in weights.items())


def _recommendations(
    *,
    blended_ratio: float,
    blended_payback: float | None,
    blended_cac: float,
    affordable_ceiling: float,
    unprofitable_share: float,
    at_ceiling_share: float,
    margin: float,
    best: ClusterUnitEconomics | None,
    cheap_channels: list[str],
) -> list[str]:
    recs: list[str] = []

    if affordable_ceiling > 0.0:
        usage = blended_cac / affordable_ceiling * 100.0 if blended_cac > 0 else 0.0
        recs.append(
            f"Blended CAC ({blended_cac:.2f}) uses {usage:.0f}% of the "
            f"{affordable_ceiling:.2f} ceiling that keeps LTV:CAC at 3:1 — "
            "that is the most you can spend per acquisition."
        )

    if unprofitable_share >= 0.30:
        channels = ", ".join(cheap_channels[:2]) if cheap_channels else "organic/referral"
        recs.append(
            f"{unprofitable_share * 100:.0f}% of projected demand is below "
            "break-even LTV:CAC — shift acquisition toward low-CAC channels "
            f"like {channels} before scaling spend."
        )

    if blended_payback is not None and blended_payback > MAX_PAYBACK_MONTHS:
        recs.append(
            f"Blended payback of {blended_payback:.1f} months exceeds the "
            f"{MAX_PAYBACK_MONTHS:.0f}-month bar — reduce CAC or raise gross "
            "margin before paying for growth."
        )

    if at_ceiling_share >= 0.50:
        recs.append(
            f"{at_ceiling_share * 100:.0f}% of demand is already at its "
            "willingness-to-pay ceiling — pricing upside is capped, so "
            "improve retention or margins instead of raising price."
        )

    if best is not None and best.ltv_cac_ratio >= STRONG_RATIO:
        channel = f" via {best.primary_channel}" if best.primary_channel else ""
        recs.append(
            f"Best unit economics: {best.cluster_name or best.cluster_id} "
            f"({best.ltv_cac_ratio:.1f} LTV:CAC, {best.payback_months:.1f} mo "
            f"payback){channel} — a double-down candidate."
        )

    if margin < 0.50 and blended_ratio > 0.0:
        lifted = blended_ratio * 0.70 / margin if margin > 0.0 else blended_ratio
        recs.append(
            f"Gross margin of {margin * 100:.0f}% caps unit economics; at a "
            f"70% margin the blended LTV:CAC would reach about {lifted:.1f}."
        )

    if not recs and blended_ratio > 0.0:
        recs.append(
            f"Blended LTV:CAC of {blended_ratio:.1f} is "
            + (
                "healthy — defend retention and keep CAC inside the ceiling."
                if blended_ratio >= STRONG_RATIO
                else "workable — push retention or margin to reach 3:1."
            )
        )
    return recs


def build_unit_economics(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    average_order_value: float = 999.0,
    gross_margin: float = DEFAULT_GROSS_MARGIN,
    purchase_frequency_per_year: float = DEFAULT_PURCHASE_FREQUENCY_PER_YEAR,
    assumed_cac: float = 0.0,
) -> UnitEconomicsOut:
    """Compose the unit-economics payload for a completed run.

    Args:
        results: simulation ``results_json`` (dict or JSON string). Expected
            keys: ``cluster_breakdown`` (cluster id -> rate or dict),
            ``product_type_detected``.
        conductor_results: optional per-cluster architect outputs
            (cluster id -> architect name -> ``{"metrics": ...}``) used for
            price ceilings, survival curves and channel CAC multipliers.
            When missing, clusters fall back to AOV pricing, default
            retention and neutral CAC multipliers.
        cluster_registry: optional list of cluster rows with ``cluster_id``,
            ``name`` and ``population_weight``. Missing clusters are weighted
            uniformly from the breakdown keys.
        average_order_value: list price per purchase / month.
        gross_margin: fraction of revenue retained after cost of goods.
        purchase_frequency_per_year: purchases per customer per year.
        assumed_cac: founder-observed blended CAC per acquired customer.
            ``<= 0`` derives a default of half an average order value.
    """
    data = _coerce_results(results)
    breakdown = data.get("cluster_breakdown")
    if not isinstance(breakdown, dict):
        breakdown = {}

    effective_aov = max(0.0, _safe_float(average_order_value))
    effective_margin = max(0.0, min(1.0, _safe_float(gross_margin, DEFAULT_GROSS_MARGIN)))
    effective_frequency = max(1.0, _safe_float(purchase_frequency_per_year, 1.0))
    base_cac = max(0.0, _safe_float(assumed_cac))
    if base_cac <= 0.0:
        base_cac = effective_aov * DEFAULT_CAC_FRACTION_OF_AOV
    effective_base_cac = base_cac
    cac_source = "founder_input" if _safe_float(assumed_cac) > 0.0 else "derived_default"
    product_type = str(data.get("product_type_detected", "saas") or "saas")

    registry = list(cluster_registry or [])
    if not registry and cluster_registry is None and breakdown:
        n = len(breakdown)
        registry = [
            {"cluster_id": cid, "name": cid, "population_weight": 1.0 / n}
            for cid in breakdown
        ]
    registry_ids = [str(r.get("cluster_id", "")) for r in registry if r.get("cluster_id")]

    channels = _channel_map(conductor_results, registry, product_type)

    profiles: list[ClusterUnitEconomics] = []
    for cluster_info in registry:
        cid = str(cluster_info.get("cluster_id", ""))
        if not cid:
            continue
        cname = str(cluster_info.get("name", cid) or cid)
        pop_weight = max(0.0, _safe_float(cluster_info.get("population_weight")))
        conversion = _cluster_rate(breakdown.get(cid))
        arch = (conductor_results or {}).get(cid, {})
        pm = _pricing_metrics(arch)
        rm = _retention_metrics(arch)

        price_ceiling = max(0.0, _safe_float(pm.get("price_ceiling")))
        will_pay = _safe_float(pm.get("will_pay_probability"))
        if will_pay <= 0.0:
            if price_ceiling > 0.0 and effective_aov > 0.0:
                will_pay = max(0.0, min(1.0, price_ceiling / effective_aov))
            else:
                # No willingness-to-pay data — fall back to list-price
                # purchase (consistent with AOV pricing below).
                will_pay = 1.0
        effective_price = (
            min(effective_aov, price_ceiling)
            if price_ceiling > 0.0
            else effective_aov
        )

        day30 = max(0.0, min(1.0, _safe_float(rm.get("day30_survival"), 0.18)))
        day90 = max(0.0, min(1.0, _safe_float(rm.get("day90_survival"), 0.10)))
        lifetime = _lifetime_months(day30, day90)

        monthly_revenue = effective_price * effective_frequency / 12.0
        monthly_contribution = monthly_revenue * effective_margin
        ltv = round(monthly_contribution * lifetime, 2)

        primary_channel, cac_multiplier = channels.get(cid, ("", 1.0))
        cac = round(base_cac * cac_multiplier, 2)
        ratio = round(ltv / cac, 2) if cac > 0.0 and ltv > 0.0 else 0.0
        payback = round(cac / monthly_contribution, 2) if monthly_contribution > 0.0 else None
        affordable_cac = round(ltv / LTV_CAC_TARGET, 2) if ltv > 0.0 else 0.0

        profiles.append(
            ClusterUnitEconomics(
                cluster_id=cid,
                cluster_name=cname,
                population_weight=round(pop_weight, 6),
                conversion_rate=round(conversion, 6),
                demand_weight=round(pop_weight * conversion, 6),
                effective_price=round(effective_price, 2),
                price_ceiling=round(price_ceiling, 2),
                will_pay_probability=round(will_pay, 4),
                monthly_contribution=round(monthly_contribution, 2),
                average_lifetime_months=lifetime,
                ltv=ltv,
                cac=cac,
                cac_multiplier=cac_multiplier,
                primary_channel=primary_channel,
                ltv_cac_ratio=ratio,
                payback_months=payback,
                affordable_cac=affordable_cac,
                verdict=_verdict(ratio, ltv),
            )
        )

    total_clusters = len(registry_ids)
    if not profiles:
        return UnitEconomicsOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            signal_quality=signal_quality,
            product_type=product_type,
            aov=round(effective_aov, 2),
            gross_margin=round(effective_margin, 4),
            purchase_frequency_per_year=round(effective_frequency, 2),
            base_cac=round(effective_base_cac, 2),
            effective_base_cac=round(effective_base_cac, 2),
            verdict=VERDICT_INSUFFICIENT,
            total_clusters=total_clusters,
            clusters_with_data=0,
            meta={
                "lifetime_model": (
                    "day30/day90 survival extrapolated with constant monthly "
                    "retention, capped at 120 months"
                ),
                "cac_source": cac_source,
                "price_scenario_note": (
                    "per-customer economics only; retention and conversion "
                    "volume are held constant"
                ),
            },
        )

    # Demand weights: population weight x realised conversion, normalised so
    # the blended verdict reflects where demand actually is. Clusters with no
    # breakdown entry fall back to population weight only; clusters that are
    # present in the breakdown but convert at 0.0 carry no demand and drop out
    # of the blend entirely.
    raw_weights: dict[str, float] = {}
    for p in profiles:
        if p.cluster_id in breakdown:
            raw_weights[p.cluster_id] = p.demand_weight
        else:
            raw_weights[p.cluster_id] = p.population_weight
    total_weight = sum(raw_weights.values())
    if total_weight <= 0.0:
        weights = {p.cluster_id: 1.0 / len(profiles) for p in profiles}
    else:
        weights = {cid: w / total_weight for cid, w in raw_weights.items()}

    def blend(attr: str) -> float:
        return round(
            sum(w * getattr(p, attr) for cid, w in weights.items() for p in profiles if p.cluster_id == cid),
            4,
        )

    blended_ltv = blend("ltv")
    blended_cac = blend("cac")
    blended_ratio = round(blended_ltv / blended_cac, 2) if blended_cac > 0.0 else 0.0
    blended_monthly = blend("monthly_contribution")
    blended_lifetime = blend("average_lifetime_months")
    blended_price = blend("effective_price")
    blended_payback = (
        round(blended_cac / blended_monthly, 1) if blended_monthly > 0.0 else None
    )
    affordable_ceiling = round(blended_ltv / LTV_CAC_TARGET, 2) if blended_ltv > 0.0 else 0.0

    strong_share = round(
        sum(w for p in profiles if p.ltv_cac_ratio >= STRONG_RATIO for cid, w in weights.items() if cid == p.cluster_id),
        4,
    )
    profitable_share = round(
        sum(w for p in profiles if p.ltv_cac_ratio >= MARGINAL_RATIO for cid, w in weights.items() if cid == p.cluster_id),
        4,
    )
    unprofitable_share = round(max(0.0, 1.0 - profitable_share), 4)

    # Price scenarios (mechanical per-customer read; retention/volume held
    # constant). Up-scenarios cap at the cluster's willingness-to-pay ceiling.
    price_scenarios: list[PriceScenario] = []
    for label, multiplier in PRICE_SCENARIO_MULTIPLIERS:
        scenario_ltv: dict[str, float] = {}
        scenario_price: dict[str, float] = {}
        capped: dict[str, float] = {}
        for p in profiles:
            w = weights.get(p.cluster_id, 0.0)
            if w <= 0.0:
                continue
            raw_price = p.effective_price * multiplier
            is_capped = False
            if multiplier > 1.0 and p.price_ceiling > 0.0:
                if raw_price > p.price_ceiling:
                    raw_price = p.price_ceiling
                    is_capped = p.effective_price > 0.0
            monthly = raw_price * effective_frequency / 12.0 * effective_margin
            scenario_ltv[p.cluster_id] = round(monthly * p.average_lifetime_months, 2)
            scenario_price[p.cluster_id] = round(raw_price, 2)
            capped[p.cluster_id] = w if is_capped else 0.0
        s_ltv = round(_weighted_sum(weights, scenario_ltv), 2)
        s_cac = blended_cac
        s_ratio = round(s_ltv / s_cac, 2) if s_cac > 0.0 else 0.0
        price_scenarios.append(
            PriceScenario(
                label=label,
                price_multiplier=multiplier,
                blended_price=round(_weighted_sum(weights, scenario_price), 2),
                blended_ltv=s_ltv,
                blended_ltv_cac_ratio=s_ratio,
                capped_share=round(sum(capped.values()), 4),
            )
        )
    at_ceiling_share = price_scenarios[-1].capped_share if price_scenarios else 0.0

    # CAC scenarios: scale the blended acquisition cost and re-blend.
    cac_scenarios: list[CacScenario] = []
    for multiplier in CAC_SCENARIO_MULTIPLIERS:
        scenario_cac = round(
            sum(w * p.cac * multiplier for p in profiles for cid, w in weights.items() if cid == p.cluster_id),
            2,
        )
        scenario_ratio = round(blended_ltv / scenario_cac, 2) if scenario_cac > 0.0 else 0.0
        cac_scenarios.append(
            CacScenario(
                label=f"CAC_X{multiplier:g}",
                cac_multiplier=multiplier,
                blended_cac=scenario_cac,
                blended_ltv_cac_ratio=scenario_ratio,
            )
        )

    scored = [p for p in profiles if p.ltv > 0.0]
    best = max(scored, key=lambda p: p.ltv_cac_ratio) if scored else None
    worst = min(scored, key=lambda p: p.ltv_cac_ratio) if scored else None
    cheap_channels = sorted(
        {p.primary_channel for p in profiles if p.primary_channel},
        key=lambda ch: min(
            (p.cac_multiplier for p in profiles if p.primary_channel == ch),
            default=1.0,
        ),
    )

    recommendations = _recommendations(
        blended_ratio=blended_ratio,
        blended_payback=blended_payback,
        blended_cac=blended_cac,
        affordable_ceiling=affordable_ceiling,
        unprofitable_share=unprofitable_share,
        at_ceiling_share=at_ceiling_share,
        margin=effective_margin,
        best=best,
        cheap_channels=cheap_channels,
    )

    return UnitEconomicsOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        signal_quality=signal_quality,
        product_type=product_type,
        aov=round(effective_aov, 2),
        gross_margin=round(effective_margin, 4),
        purchase_frequency_per_year=round(effective_frequency, 2),
        base_cac=round(effective_base_cac, 2),
        effective_base_cac=round(effective_base_cac, 2),
        blended_price=blended_price,
        blended_monthly_contribution=blended_monthly,
        blended_lifetime_months=blended_lifetime,
        blended_ltv=blended_ltv,
        blended_cac=blended_cac,
        blended_ltv_cac_ratio=blended_ratio,
        blended_payback_months=blended_payback,
        affordable_cac_ceiling=affordable_ceiling,
        verdict=_verdict(blended_ratio, blended_ltv),
        strong_share=strong_share,
        profitable_share=profitable_share,
        unprofitable_share=unprofitable_share,
        at_ceiling_share=at_ceiling_share,
        best_cluster_id=best.cluster_id if best else None,
        best_cluster_name=best.cluster_name if best else "",
        worst_cluster_id=worst.cluster_id if worst else None,
        worst_cluster_name=worst.cluster_name if worst else "",
        total_clusters=total_clusters,
        clusters_with_data=len(profiles),
        recommendations=recommendations,
        cac_scenarios=cac_scenarios,
        price_scenarios=price_scenarios,
        cluster_profiles=sorted(profiles, key=lambda p: -p.ltv_cac_ratio),
        meta={
            "lifetime_model": (
                "day30/day90 survival extrapolated with constant monthly "
                "retention, capped at 120 months"
            ),
            "cac_source": cac_source,
            "price_scenario_note": (
                "per-customer economics only; retention and conversion "
                "volume are held constant"
            ),
        },
    )


__all__ = [
    "DEFAULT_GROSS_MARGIN",
    "DEFAULT_PURCHASE_FREQUENCY_PER_YEAR",
    "DEFAULT_CAC_FRACTION_OF_AOV",
    "LTV_CAC_TARGET",
    "MAX_LIFETIME_MONTHS",
    "VERDICT_STRONG",
    "VERDICT_VIABLE",
    "VERDICT_MARGINAL",
    "VERDICT_UNPROFITABLE",
    "VERDICT_INSUFFICIENT",
    "build_unit_economics",
]
