"""
Conductor — orchestrates 52 clusters × architect stack per product type,
applies ClusterReweightingEngine, and optionally persists cluster_run_summaries
for the learning system.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import delete

from app.simulation.architects.base import ArchitectOutput, DomainReport
from app.simulation.cluster_reweighting import ClusterReweightingEngine
from app.simulation.cognitive_state import CognitiveStateMutator
from app.simulation.clusters.definitions import ClusterDefinition
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.product_type import ProductType


# Keyword → ProductType scoring
PRODUCT_TYPE_KEYWORDS: dict[ProductType, list[str]] = {
    ProductType.SAAS: [
        "saas", "subscription software", "web app", "dashboard", "api platform",
        "crm", "erp", "b2b software",
    ],
    ProductType.MARKETPLACE: [
        "marketplace", "platform connecting", "two-sided", "buyers and sellers",
        "gig", "freelance platform",
    ],
    ProductType.MOBILE_APP: [
        "mobile app", "ios app", "android app", "consumer app", "smartphone app",
        "flutter", "react native",
    ],
    ProductType.DEVELOPER_TOOL: [
        "developer tool", "sdk", "api", "cli", "devops", "ide plugin",
        "open source", "github", "npm",
    ],
    ProductType.ENTERPRISE_SOFTWARE: [
        "enterprise", "fortune 500", "procurement", "b2b enterprise", "compliance",
        "sso", "on-premise",
    ],
    ProductType.CONSUMER_HARDWARE: [
        "hardware", "device", "gadget", "bluetooth", "speaker", "camera",
        "smart device", "consumer electronics",
    ],
    ProductType.HEALTH_HARDWARE: [
        "health device", "wearable health", "blood pressure", "glucose",
        "heart rate monitor", "medical device", "health monitor",
    ],
    ProductType.IOT_HARDWARE: [
        "iot", "smart home", "connected device", "sensor", "automation",
        "smart plug", "hub", "zigbee", "matter",
    ],
    ProductType.WEARABLE: [
        "smartwatch", "fitness tracker", "wearable", "band", "watch", "ring wearable",
    ],
    ProductType.B2B_HARDWARE: [
        "b2b hardware", "b2b", "enterprise hardware", "pos device", "pos ", "kiosk",
        "ruggedized", "rugged", "fleet device", "retail fleet",
    ],
}

_HARDWARE_PRIORITY: tuple[ProductType, ...] = (
    ProductType.WEARABLE,
    ProductType.HEALTH_HARDWARE,
    ProductType.IOT_HARDWARE,
    ProductType.B2B_HARDWARE,
    ProductType.CONSUMER_HARDWARE,
)

ARCHITECT_STACKS: dict[ProductType, list[str]] = {
    ProductType.SAAS: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PricingArchitect", "OnboardingArchitect",
        "FeatureAdoptionArchitect", "RetentionArchitect",
        "SupportFrictionArchitect", "ViralityArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
    ProductType.MARKETPLACE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PricingArchitect", "OnboardingArchitect",
        "RetentionArchitect", "SupportFrictionArchitect", "ViralityArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
    ProductType.MOBILE_APP: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PricingArchitect", "OnboardingArchitect",
        "FeatureAdoptionArchitect", "RetentionArchitect", "ViralityArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
    ProductType.DEVELOPER_TOOL: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PricingArchitect", "OnboardingArchitect",
        "FeatureAdoptionArchitect", "RetentionArchitect", "ViralityArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
    ProductType.ENTERPRISE_SOFTWARE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PricingArchitect", "OnboardingArchitect",
        "FeatureAdoptionArchitect", "RetentionArchitect",
        "SupportFrictionArchitect", "MacroeconomicArchitect",
        "DemographicInteractionArchitect", "AssumptionCascadeArchitect",
    ],
    ProductType.CONSUMER_HARDWARE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PurchaseDecisionArchitect", "PhysicalSensoryArchitect",
        "PerformanceThresholdArchitect", "SetupFirstUseArchitect",
        "EcosystemCompatibilityArchitect", "DistributionChannelArchitect",
        "AftersalesLifecycleArchitect", "ViralityArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
    ProductType.HEALTH_HARDWARE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "HealthSafetyHardwareArchitect",
        "PurchaseDecisionArchitect", "PhysicalSensoryArchitect",
        "PerformanceThresholdArchitect", "SetupFirstUseArchitect",
        "EcosystemCompatibilityArchitect", "AftersalesLifecycleArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
    ProductType.IOT_HARDWARE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PurchaseDecisionArchitect",
        "PerformanceThresholdArchitect", "SetupFirstUseArchitect",
        "EcosystemCompatibilityArchitect", "DistributionChannelArchitect",
        "AftersalesLifecycleArchitect", "MacroeconomicArchitect",
        "DemographicInteractionArchitect", "AssumptionCascadeArchitect",
    ],
    ProductType.WEARABLE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PurchaseDecisionArchitect", "PhysicalSensoryArchitect",
        "PerformanceThresholdArchitect", "SetupFirstUseArchitect",
        "EcosystemCompatibilityArchitect", "DistributionChannelArchitect",
        "AftersalesLifecycleArchitect", "MacroeconomicArchitect",
        "DemographicInteractionArchitect", "AssumptionCascadeArchitect",
    ],
    ProductType.B2B_HARDWARE: [
        "MarketTimingArchitect", "CompetitiveDynamicsArchitect",
        "TrustArchitect", "PurchaseDecisionArchitect",
        "PerformanceThresholdArchitect", "SetupFirstUseArchitect",
        "DistributionChannelArchitect", "AftersalesLifecycleArchitect",
        "MacroeconomicArchitect", "DemographicInteractionArchitect",
        "AssumptionCascadeArchitect",
    ],
}

# Inter-architect dependency map
# key = architect that needs input, value = {param_name: (source_architect, metric_key)}
DEPENDENCY_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "RetentionArchitect": {
        "feature_depth_score":        ("FeatureAdoptionArchitect", "feature_depth_score"),
        "onboarding_completion_rate": ("OnboardingArchitect",      "onboarding_completion_rate"),
    },
    "SupportFrictionArchitect": {
        "onboarding_completion_rate": ("OnboardingArchitect", "onboarding_completion_rate"),
    },
    "ViralityArchitect": {
        "day30_survival":       ("RetentionArchitect",       "day30_survival"),
        "feature_depth_score":  ("FeatureAdoptionArchitect", "feature_depth_score"),
    },
    "PricingArchitect": {
        "switching_friction":   ("CompetitiveDynamicsArchitect", "incumbent_switching_friction"),
    },
    "AssumptionCascadeArchitect": {
        "viral_coefficient":           ("ViralityArchitect",     "viral_coefficient"),
        "day30_survival":              ("RetentionArchitect",    "day30_survival"),
        "onboarding_completion_rate":  ("OnboardingArchitect",   "onboarding_completion_rate"),
    },
    "AftersalesLifecycleArchitect": {
        "oob_setup_completion_rate": ("SetupFirstUseArchitect", "oob_setup_completion_rate"),
        "brand_deficit_multiplier":  ("TrustArchitect",         "brand_deficit_multiplier"),
    },
    "PurchaseDecisionArchitect": {
        "brand_deficit_multiplier":    ("TrustArchitect",        "brand_deficit_multiplier"),
        "problem_urgency_intensity": ("MarketTimingArchitect",   "problem_urgency_intensity"),
        "technology_adoption_score": ("MarketTimingArchitect",   "technology_adoption_score"),
    },
    "PhysicalSensoryArchitect": {
        "brand_deficit_multiplier":  ("TrustArchitect",        "brand_deficit_multiplier"),
        "gift_purchase_probability": ("PurchaseDecisionArchitect", "gift_purchase_probability"),
    },
    "DistributionChannelArchitect": {
        "problem_urgency_intensity": ("MarketTimingArchitect", "problem_urgency_intensity"),
    },
    "EcosystemCompatibilityArchitect": {
        "brand_deficit_multiplier": ("TrustArchitect", "brand_deficit_multiplier"),
    },
    "HealthSafetyHardwareArchitect": {
        "day30_survival": ("RetentionArchitect", "day30_survival"),
    },
    "CompetitiveDynamicsArchitect": {
        "switching_cost_depth":      ("MarketTimingArchitect", "switching_cost_depth"),
        "problem_urgency_intensity": ("MarketTimingArchitect", "problem_urgency_intensity"),
    },
}


@dataclass
class ConductorResult:
    product_type:                   ProductType
    cluster_results:                dict[str, dict[str, ArchitectOutput]]
    population_weighted_conversion: float
    domain_reports:                 list[DomainReport]
    cluster_breakdown:              dict[str, float]
    architect_accountability:       dict[str, float]
    per_cluster_matrices:           dict[str, dict[tuple[str, str], float]]
    signal_quality:                 float = 0.0


def _mean_metric(output: ArchitectOutput) -> float:
    nums = [v for v in output.metrics.values() if isinstance(v, (int, float))]
    if not nums:
        return 0.5
    return float(sum(nums) / len(nums))


def _build_architect_registry() -> dict[str, Any]:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect
    from app.simulation.architects.distribution_channel import DistributionChannelArchitect
    from app.simulation.architects.ecosystem_compatibility import EcosystemCompatibilityArchitect
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect
    from app.simulation.architects.health_safety_hardware import HealthSafetyHardwareArchitect
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect
    from app.simulation.architects.market_timing import MarketTimingArchitect
    from app.simulation.architects.onboarding import OnboardingArchitect
    from app.simulation.architects.performance_threshold import PerformanceThresholdArchitect
    from app.simulation.architects.physical_sensory import PhysicalSensoryArchitect
    from app.simulation.architects.pricing import PricingArchitect
    from app.simulation.architects.purchase_decision import PurchaseDecisionArchitect
    from app.simulation.architects.retention import RetentionArchitect
    from app.simulation.architects.setup_first_use import SetupFirstUseArchitect
    from app.simulation.architects.support_friction import SupportFrictionArchitect
    from app.simulation.architects.trust import TrustArchitect
    from app.simulation.architects.virality import ViralityArchitect

    return {
        "MarketTimingArchitect":           MarketTimingArchitect(),
        "CompetitiveDynamicsArchitect":    CompetitiveDynamicsArchitect(),
        "TrustArchitect":                  TrustArchitect(),
        "PricingArchitect":                PricingArchitect(),
        "OnboardingArchitect":             OnboardingArchitect(),
        "FeatureAdoptionArchitect":        FeatureAdoptionArchitect(),
        "RetentionArchitect":              RetentionArchitect(),
        "SupportFrictionArchitect":        SupportFrictionArchitect(),
        "ViralityArchitect":               ViralityArchitect(),
        "MacroeconomicArchitect":          MacroeconomicArchitect(),
        "DemographicInteractionArchitect": DemographicInteractionArchitect(),
        "AssumptionCascadeArchitect":      AssumptionCascadeArchitect(),
        "PurchaseDecisionArchitect":       PurchaseDecisionArchitect(),
        "PhysicalSensoryArchitect":        PhysicalSensoryArchitect(),
        "PerformanceThresholdArchitect":   PerformanceThresholdArchitect(),
        "SetupFirstUseArchitect":          SetupFirstUseArchitect(),
        "EcosystemCompatibilityArchitect": EcosystemCompatibilityArchitect(),
        "DistributionChannelArchitect":    DistributionChannelArchitect(),
        "AftersalesLifecycleArchitect":    AftersalesLifecycleArchitect(),
        "HealthSafetyHardwareArchitect":   HealthSafetyHardwareArchitect(),
    }


_ARCHITECTS = _build_architect_registry()


class Conductor:
    """Orchestrates cluster × architect simulation runs."""

    def __init__(self) -> None:
        self._registry   = ClusterRegistry()
        self._architects = _ARCHITECTS
        self._mutator    = CognitiveStateMutator()

    def detect_product_type(
        self,
        description: str,
        assumptions: list[dict],
    ) -> ProductType:
        parts = [description] + [
            str(a.get("text", a.get("assumption", ""))) for a in assumptions
        ]
        text = " ".join(parts).lower()

        scores: dict[ProductType, int] = {pt: 0 for pt in ProductType}
        for pt, keywords in PRODUCT_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    scores[pt] += 1

        best = max(scores, key=lambda p: scores[p])
        if scores[best] == 0:
            return ProductType.SAAS

        best_score = scores[best]
        tied = [p for p in ProductType if scores[p] == best_score]
        if len(tied) > 1:
            for hw in _HARDWARE_PRIORITY:
                if hw in tied:
                    return hw
        return best

    def _reweight_clusters(
        self,
        product_type: ProductType,
        env_slice: dict[str, Any],
    ) -> dict[str, float]:
        """Return normalized cluster weights for a product type (used by tests and tooling)."""
        reweighter = ClusterReweightingEngine()
        return reweighter.compute_weights(
            product_type=product_type,
            aov=float(env_slice.get("average_order_value", 999)),
            geography=str(env_slice.get("geography", "ALL_INDIA")),
            segment=str(env_slice.get("target_segment", "B2C")),
            age_target=str(env_slice.get("age_target", "ALL")),
        )

    def _resolve_deps(
        self,
        architect_name: str,
        cluster_outputs: dict[str, ArchitectOutput],
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        deps = DEPENDENCY_MAP.get(architect_name, {})
        for param_name, (source_arch, metric_key) in deps.items():
            if source_arch in cluster_outputs:
                val = cluster_outputs[source_arch].metrics.get(metric_key)
                if val is not None:
                    resolved[param_name] = val
        return resolved

    def run(
        self,
        agents: list[Any],
        env_params: dict[str, Any],
        assumptions: list[dict[str, Any]],
        product_type: ProductType | None = None,
        simulation_id: int | None = None,
        user_id: int | None = None,
        signal_quality: float = 0.0,
        db: Any = None,
        simulation: Any | None = None,
    ) -> ConductorResult:
        if product_type is None:
            desc = str(env_params.get("description", ""))
            product_type = self.detect_product_type(desc, assumptions)

        env_params = {**env_params, "product_type": product_type.value}
        reweighter = ClusterReweightingEngine()
        cluster_weights = reweighter.compute_weights(
            product_type=product_type,
            aov=float(env_params.get("average_order_value", 999)),
            geography=str(env_params.get("geography", "ALL_INDIA")),
            segment=str(env_params.get("target_segment", "B2C")),
            age_target=str(env_params.get("age_target", "ALL")),
        )

        sq = float(signal_quality or 0.0)
        if simulation is not None and getattr(simulation, "signal_quality", None) is not None:
            sq = float(simulation.signal_quality)
        claim_conf_dist = None
        if simulation is not None:
            claim_conf_dist = getattr(simulation, "claim_confidence_distribution", None)
        stack = ARCHITECT_STACKS.get(product_type, ARCHITECT_STACKS[ProductType.SAAS])
        all_clusters = self._registry.all_clusters()

        total_agents = len(agents) if agents else 10000
        cluster_agent_counts = {
            c.cluster_id: max(1, int(cluster_weights.get(c.cluster_id, 0) * total_agents))
            for c in all_clusters
        }

        cluster_results: dict[str, dict[str, ArchitectOutput]] = {}
        cluster_breakdown: dict[str, float] = {}
        per_cluster_matrices: dict[str, dict[tuple[str, str], float]] = {}
        cluster_mutation_logs: dict[str, dict[str, float]] = {}

        for cluster in all_clusters:
            cluster_outputs: dict[str, ArchitectOutput] = {}
            _mutation_log: dict[str, float] = {}
            cluster_working = cluster

            for arch_name in stack:
                architect = self._architects.get(arch_name)
                if architect is None:
                    continue
                pt_ok = (
                    product_type.value in architect.product_types
                    or len(architect.product_types) == 0
                )
                if not pt_ok:
                    continue

                deps = self._resolve_deps(arch_name, cluster_outputs)
                agent_profile: dict[str, Any] = {
                    **cluster_working.base_traits,
                    **deps,
                }

                # Step 68d: MarketTiming + CompetitiveDynamics are in cluster_outputs;
                # mutator runs before TrustArchitect.compute (and before transition overrides).
                if arch_name == "TrustArchitect":
                    mutation_result = self._mutator.apply(
                        cluster_id=cluster.cluster_id,
                        agent_profile=agent_profile,
                        architect_outputs=dict(cluster_outputs),
                        assumptions=assumptions,
                    )
                    if mutation_result.any_mutation_fired:
                        for m in mutation_result.mutations_applied:
                            _mutation_log[m.trigger_name] = abs(m.delta)
                        new_traits = dict(cluster_working.base_traits)
                        for k, v in mutation_result.mutated_profile.items():
                            if k in cluster_working.base_traits:
                                new_traits[k] = float(v)
                        cluster_working = replace(
                            cluster_working, base_traits=new_traits
                        )
                        agent_profile = {
                            **cluster_working.base_traits,
                            **deps,
                        }

                try:
                    output = architect.compute(
                        cluster=cluster_working,
                        agent_profile=agent_profile,
                        assumptions=assumptions,
                        env_params=env_params,
                    )
                    cluster_outputs[arch_name] = output
                except Exception:
                    logger.exception(
                        "Architect %s failed for cluster %s",
                        arch_name,
                        cluster.cluster_id,
                    )

            cluster_mutation_logs[cluster.cluster_id] = _mutation_log
            cluster_results[cluster.cluster_id] = cluster_outputs

            conversion = self._estimate_cluster_conversion(cluster_outputs)
            cluster_breakdown[cluster.cluster_id] = conversion

            overrides_acc: dict[tuple[str, str], float] = {}
            for arch_name, output in cluster_outputs.items():
                arch = self._architects.get(arch_name)
                if arch:
                    overrides_acc.update(arch.transition_overrides(output))
            per_cluster_matrices[cluster.cluster_id] = overrides_acc

        pwc = sum(
            cluster_breakdown.get(c.cluster_id, 0.0) * cluster_weights.get(c.cluster_id, 0.0)
            for c in all_clusters
        )

        domain_reports: list[DomainReport] = []
        for arch_name in stack:
            architect = self._architects.get(arch_name)
            if not architect:
                continue
            arch_outputs = [
                cluster_results[c.cluster_id][arch_name]
                for c in all_clusters
                if arch_name in cluster_results.get(c.cluster_id, {})
            ]
            if arch_outputs:
                try:
                    domain_reports.append(architect.generate_report(arch_outputs))
                except Exception as _exc:
                    logger.debug(
                        "%s suppressed: %s",
                        __name__,
                        _exc,
                    )

        architect_accountability = self._compute_accountability(
            cluster_results, cluster_weights, all_clusters
        )

        result = ConductorResult(
            product_type=product_type,
            cluster_results=cluster_results,
            population_weighted_conversion=round(pwc, 6),
            domain_reports=domain_reports,
            cluster_breakdown=cluster_breakdown,
            architect_accountability=architect_accountability,
            per_cluster_matrices=per_cluster_matrices,
            signal_quality=sq,
        )

        if db is not None and simulation_id is not None:
            self._write_cluster_summaries(
                db,
                simulation_id,
                cluster_results,
                cluster_breakdown,
                cluster_agent_counts,
                sq,
                product_type.value,
                claim_confidence_distribution=claim_conf_dist,
                cluster_mutation_logs=cluster_mutation_logs,
            )

        if db is not None and user_id is not None:
            from app.simulation.blindspot_detector import BlindspotDetector

            BlindspotDetector().scan(
                user_id=user_id,
                simulation=simulation,
                cluster_weights=cluster_weights,
                conductor_result=result,
                db=db,
            )

        return result

    def _estimate_cluster_conversion(
        self,
        cluster_outputs: dict[str, ArchitectOutput],
    ) -> float:
        from app.simulation.markov import ClusterTransitionMatrix, MarkovBehaviourModel

        # Find the cluster definition for this set of outputs
        cluster_def = None
        for output in cluster_outputs.values():
            if output.cluster_id:
                cluster_def = self._registry.get_cluster(output.cluster_id)
                if cluster_def:
                    break

        if cluster_def:
            try:
                result = MarkovBehaviourModel.build(
                    env_params={},
                    assumptions=[],
                    cluster=cluster_def,
                    architect_outputs=cluster_outputs,
                )
                if isinstance(result, ClusterTransitionMatrix):
                    return round(float(result.conversion_estimate), 6)
            except Exception:
                pass

        # Fallback: chain product with architect overrides applied to
        # BASE_TRANSITIONS scalars. The previous hardcoded 0.5/0.8/0.7/0.6
        # magic numbers diverged from BASE_TRANSITIONS by 60%+ and produced
        # a 0.168 default that contradicted the canonical 0.077 chain.
        from app.simulation.markov import BASE_TRANSITIONS, State

        decide_purchase = float(BASE_TRANSITIONS[State.DECIDE][State.PURCHASE])
        arrive_browse = float(BASE_TRANSITIONS[State.ARRIVE][State.BROWSE])
        browse_consider = float(BASE_TRANSITIONS[State.BROWSE][State.CONSIDER])
        consider_decide = float(BASE_TRANSITIONS[State.CONSIDER][State.DECIDE])

        for arch_name, output in cluster_outputs.items():
            architect = self._architects.get(arch_name)
            if not architect:
                continue
            overrides = architect.transition_overrides(output)
            if ("DECIDE", "PURCHASE") in overrides:
                decide_purchase = max(0.01, min(0.95, overrides[("DECIDE", "PURCHASE")]))
            if ("ARRIVE", "BROWSE") in overrides:
                arrive_browse *= overrides[("ARRIVE", "BROWSE")]
            if ("BROWSE", "CONSIDER") in overrides:
                browse_consider *= overrides[("BROWSE", "CONSIDER")]
            if ("CONSIDER", "DECIDE") in overrides:
                consider_decide *= overrides[("CONSIDER", "DECIDE")]

        macro_out = cluster_outputs.get("MacroeconomicArchitect")
        if macro_out:
            macro_mult = macro_out.metrics.get("overall_conversion_correction", 1.0)
            if isinstance(macro_mult, (int, float)):
                decide_purchase *= float(macro_mult)

        demo_out = cluster_outputs.get("DemographicInteractionArchitect")
        if demo_out:
            demo_mult = demo_out.metrics.get("overall_demographic_correction", 1.0)
            if isinstance(demo_mult, (int, float)):
                arrive_browse *= float(demo_mult)

        conversion = (
            max(0.01, min(0.95, arrive_browse)) *
            max(0.01, min(0.95, browse_consider)) *
            max(0.01, min(0.95, consider_decide)) *
            max(0.01, min(0.95, decide_purchase))
        )
        return round(max(0.0, min(0.95, conversion)), 6)

    def _compute_accountability(
        self,
        cluster_results: dict[str, dict[str, ArchitectOutput]],
        cluster_weights: dict[str, float],
        all_clusters: list[ClusterDefinition],
    ) -> dict[str, float]:
        accountability: dict[str, float] = {}
        for c in all_clusters:
            outputs = cluster_results.get(c.cluster_id, {})
            weight = cluster_weights.get(c.cluster_id, 0.0)
            for arch_name, output in outputs.items():
                if output.severity in ("CRITICAL", "WARNING"):
                    accountability[arch_name] = accountability.get(arch_name, 0.0) + weight
        total = sum(accountability.values()) or 1.0
        return {k: round(v / total, 4) for k, v in accountability.items()}

    def _write_cluster_summaries(
        self,
        db: Any,
        simulation_id: int,
        cluster_results: dict[str, dict[str, ArchitectOutput]],
        cluster_breakdown: dict[str, float],
        cluster_agent_counts: dict[str, int],
        signal_quality: float,
        product_type: str,
        claim_confidence_distribution: dict | None = None,
        cluster_mutation_logs: dict[str, dict[str, float]] | None = None,
    ) -> None:
        from app.models.cluster_run_summary import ClusterRunSummary

        try:
            db.execute(
                delete(ClusterRunSummary).where(
                    ClusterRunSummary.simulation_id == simulation_id
                )
            )
        except Exception:
            logger.exception(
                "cluster_run_summaries delete failed for sim=%s", simulation_id
            )
            # The PG transaction is now aborted; roll back so the per-cluster
            # db.add() and final commit below operate on a clean session,
            # then surface the failure so the Celery task can retry instead
            # of silently keeping stale rows in cluster_run_summaries.
            try:
                db.rollback()
            except Exception:
                logger.debug(
                    "%s rollback suppressed", __name__, exc_info=True
                )
            raise

        for cluster_id, arch_outputs in cluster_results.items():
            conversion_rate = cluster_breakdown.get(cluster_id, 0.0)
            total_agents = cluster_agent_counts.get(cluster_id, 0)
            converted = int(total_agents * float(conversion_rate))

            arrive = total_agents
            browse = int(arrive * 0.82)
            consider = int(browse * 0.65)
            decide = int(consider * 0.55)
            purchase = converted

            drop_dist = {
                "ARRIVE":   arrive - browse,
                "BROWSE":   browse - consider,
                "CONSIDER": consider - decide,
                "DECIDE":   decide - purchase,
            }
            mean_drop = max(drop_dist, key=drop_dist.get)

            architect_scores = {
                name: _mean_metric(o) for name, o in arch_outputs.items()
            }
            mlog = (cluster_mutation_logs or {}).get(cluster_id, {})
            architect_scores["CognitiveState_trust_delta"] = mlog.get("trust_delta", 0.0)
            architect_scores["CognitiveState_frustration"] = mlog.get("frustration", 0.0)
            architect_scores["CognitiveState_intent_clarity"] = mlog.get(
                "intent_clarity", 0.0
            )
            primary_trigger = (
                min(architect_scores, key=architect_scores.get) if architect_scores else None
            )

            try:
                db.add(
                    ClusterRunSummary(
                        simulation_id=simulation_id,
                        cluster_id=cluster_id,
                        agents_assigned=total_agents,
                        agents_converted=converted,
                        conversion_rate=float(conversion_rate),
                        drop_state_distribution=drop_dist,
                        mean_drop_state=mean_drop,
                        architect_scores=architect_scores,
                        primary_drop_trigger=primary_trigger,
                        signal_quality=signal_quality,
                        claim_confidence_distribution=claim_confidence_distribution,
                        product_type=product_type,
                    )
                )
            except Exception as e:
                print(f"WARN: ClusterRunSummary ORM add failed for {cluster_id}: {e}")
        try:
            db.commit()
        except Exception:
            logger.exception(
                "cluster_run_summaries commit failed for sim=%s", simulation_id
            )
            try:
                db.rollback()
            except Exception:
                logger.debug(
                    "%s rollback suppressed", __name__, exc_info=True
                )
            raise
