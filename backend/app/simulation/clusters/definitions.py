"""
ClusterDefinition dataclass — the schema for every consumer cluster in TheCee.

The 8 required trait keys (must match the cluster_parameters DB table):
  income_level, digital_literacy, motivation, trust,
  price_sensitivity, risk_aversion, patience_score, social_orientation

All trait values are normalised floats in [0.0, 1.0]:
  0.0 = absolute minimum for the trait
  1.0 = absolute maximum for the trait

trait_variance values represent one standard deviation, also in [0.0, 1.0].
"""
from __future__ import annotations

from dataclasses import dataclass

REQUIRED_TRAITS: frozenset[str] = frozenset({
    "income_level",
    "digital_literacy",
    "motivation",
    "trust",
    "price_sensitivity",
    "risk_aversion",
    "patience_score",
    "social_orientation",
})


@dataclass(frozen=True)
class ClusterDefinition:
    """
    Immutable specification for a single consumer cluster.

    Attributes:
        cluster_id:                Snake-case unique identifier.
                                   Must match cluster_parameters.cluster_id.
        name:                      Human-readable display name.
        description:               One-sentence summary used in narrative reports.
        population_weight:         Fraction of the total simulated population
                                   this cluster represents. All weights across
                                   the 52 clusters must sum to 1.0 ± 0.001.
        base_traits:               Central tendency for each of the 8 required
                                   traits. Synced to cluster_parameters.base_value
                                   by ClusterRegistry.sync_to_db().
        trait_variance:            Per-trait standard deviation used when
                                   sampling individual agent profiles.
        dominant_behavior_pattern: Single sentence describing how this cluster
                                   typically moves through the conversion funnel.
        known_failure_modes:       List of scenario descriptions where this
                                   cluster reliably fails to convert.
        product_affinities:        List of product type strings this cluster
                                   converts well on. Used by
                                   ClusterRegistry.clusters_for_product_type().
        demographic_profile:       Key demographic tags (geography, age_bracket,
                                   device_primary, etc.).
    """
    cluster_id:                str
    name:                      str
    description:               str
    population_weight:         float
    base_traits:               dict[str, float]
    trait_variance:            dict[str, float]
    dominant_behavior_pattern: str
    known_failure_modes:       list[str]
    product_affinities:        list[str]
    demographic_profile:       dict[str, str]
