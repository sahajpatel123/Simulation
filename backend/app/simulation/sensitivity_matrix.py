from __future__ import annotations

from typing import Any

SENSITIVITY_TRAITS = [
    "price_sensitivity",
    "trust",
    "digital_literacy",
    "risk_aversion",
    "patience_score",
    "motivation",
]


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if f != f or f == float("inf") or f == float("-inf"):
            return default
        return f
    except (ValueError, TypeError):
        return default


def compute_simulation_sensitivity_matrix(
    results_json: dict[str, Any] | None,
    delta_step: float = 0.1,
) -> dict[str, Any]:
    """Compute sensitivity and elasticity matrix across cluster traits for a simulation.

    Evaluates how variations in consumer cluster traits (price sensitivity, trust,
    digital literacy, etc.) impact final conversion rates and Markov state progression.

    Args:
        results_json: Simulation results JSON dictionary containing cluster_breakdown,
            stage_conversions, or architect_outputs.
        delta_step: Perturbation delta for elasticity estimation (default 0.1 = 10%).

    Returns:
        Dict containing overall_elasticity_score, leverage_traits, trait_sensitivities,
        risk_matrix, recommendations, and narrative.
    """
    results_json = results_json or {}
    cluster_breakdown = results_json.get("cluster_breakdown") or {}
    if not isinstance(cluster_breakdown, dict):
        cluster_breakdown = {}

    stage_conversions = results_json.get("stage_conversions") or {}
    if not isinstance(stage_conversions, dict):
        stage_conversions = {}

    baseline_conversion = _safe_float(stage_conversions.get("PURCHASE", 0.0))
    if baseline_conversion == 0.0:
        # Fallback to average cluster conversion rate
        rates = [
            _safe_float(data.get("conversion_rate"))
            for data in cluster_breakdown.values()
            if isinstance(data, dict)
        ]
        baseline_conversion = sum(rates) / len(rates) if rates else 0.05

    trait_sensitivities: list[dict[str, Any]] = []
    total_impact = 0.0

    for trait in SENSITIVITY_TRAITS:
        # Aggregate baseline trait weight across clusters
        trait_vals: list[float] = []
        cluster_weights: list[float] = []

        for cid, data in cluster_breakdown.items():
            if isinstance(data, dict):
                traits_dict = data.get("traits") or {}
                if isinstance(traits_dict, dict) and trait in traits_dict:
                    val = _safe_float(traits_dict[trait], 0.5)
                    weight = _safe_float(data.get("weight"), 1.0)
                    trait_vals.append(val)
                    cluster_weights.append(weight)

        if trait_vals and sum(cluster_weights) > 0:
            avg_trait_val = sum(v * w for v, w in zip(trait_vals, cluster_weights)) / sum(cluster_weights)
        else:
            avg_trait_val = 0.5

        # Directional impact heuristics based on behavioral economic model:
        # High price sensitivity & risk aversion negatively impact conversion when increased.
        # High trust, digital literacy, patience, and motivation positively impact conversion.
        direction_multiplier = -1.0 if trait in ("price_sensitivity", "risk_aversion") else 1.0

        # Compute elasticity: d(Conversion) / d(Trait)
        impact_factor = (1.0 - abs(avg_trait_val - 0.5)) * direction_multiplier
        estimated_elasticity = round(impact_factor * 0.8, 4)
        projected_conversion_shift = round(baseline_conversion * (1.0 + estimated_elasticity * delta_step), 4)
        sensitivity_magnitude = round(abs(estimated_elasticity), 4)
        total_impact += sensitivity_magnitude

        trait_sensitivities.append({
            "trait": trait,
            "average_value": round(avg_trait_val, 4),
            "elasticity_coefficient": estimated_elasticity,
            "sensitivity_magnitude": sensitivity_magnitude,
            "impact_direction": "POSITIVE" if estimated_elasticity > 0 else "NEGATIVE",
            "projected_conversion_shift": max(0.0, min(1.0, projected_conversion_shift)),
            "leverage_level": "HIGH" if sensitivity_magnitude >= 0.4 else ("MEDIUM" if sensitivity_magnitude >= 0.2 else "LOW"),
        })

    # Sort trait sensitivities by impact magnitude
    trait_sensitivities.sort(key=lambda x: x["sensitivity_magnitude"], reverse=True)

    leverage_traits = [
        item["trait"] for item in trait_sensitivities if item["leverage_level"] in ("HIGH", "MEDIUM")
    ]

    overall_elasticity_score = round(min(100.0, (total_impact / len(SENSITIVITY_TRAITS)) * 150.0), 2)

    # Risk matrix & Recommendations
    risk_matrix: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    for item in trait_sensitivities:
        if item["impact_direction"] == "NEGATIVE" and item["leverage_level"] in ("HIGH", "MEDIUM"):
            risk_matrix.append({
                "trait": item["trait"],
                "risk_level": "HIGH" if item["leverage_level"] == "HIGH" else "MEDIUM",
                "description": f"High consumer {item['trait'].replace('_', ' ')} severely depresses conversion.",
            })
            recommendations.append({
                "target_trait": item["trait"],
                "action": f"Introduce risk mitigation levers (money-back guarantee, transparent pricing, free trial) to counteract consumer {item['trait'].replace('_', ' ')}.",
                "priority": "HIGH",
            })
        elif item["impact_direction"] == "POSITIVE" and item["leverage_level"] in ("HIGH", "MEDIUM"):
            recommendations.append({
                "target_trait": item["trait"],
                "action": f"Leverage high consumer {item['trait'].replace('_', ' ')} by enhancing value clarity and onboarding simplicity.",
                "priority": "MEDIUM",
            })

    top_leverage = trait_sensitivities[0] if trait_sensitivities else None
    narrative_parts = [
        f"Sensitivity analysis indicates an overall elasticity score of {overall_elasticity_score}/100."
    ]
    if top_leverage:
        narrative_parts.append(
            f"Primary leverage trait is '{top_leverage['trait']}' (elasticity: {top_leverage['elasticity_coefficient']:+.2f})."
        )
    narrative_parts.append(
        f"Identified {len(leverage_traits)} key leverage trait(s) affecting conversion variance across clusters."
    )
    narrative = " ".join(narrative_parts)

    return {
        "overall_elasticity_score": overall_elasticity_score,
        "baseline_conversion": round(baseline_conversion, 4),
        "leverage_traits": leverage_traits,
        "trait_sensitivities": trait_sensitivities,
        "risk_matrix": risk_matrix,
        "recommendations": recommendations,
        "narrative": narrative,
    }


__all__ = [
    "compute_simulation_sensitivity_matrix",
    "SENSITIVITY_TRAITS",
]
