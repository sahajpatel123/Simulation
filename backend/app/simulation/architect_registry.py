"""Architect instance registry — neutral home for ``_ARCHITECTS``.

Lives apart from the conductor so that modules which need live architect
instances (e.g. ``app.simulation.markov``, which applies
``transition_overrides()`` while building per-cluster transition matrices)
can import them without reaching into ``app.simulation.conductor``. That
keeps the conductor ↔ markov import graph acyclic: both depend on this
module, and nothing here depends on either of them.

Instantiation happens once at first import — the same eager pattern the
conductor used when the builder lived there.
"""

from __future__ import annotations

from typing import Any


def build_architect_registry() -> dict[str, Any]:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect
    from app.simulation.architects.ai_skepticism import AISkepticismArchitect
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect
    from app.simulation.architects.behavioral_economics import (
        BehavioralEconomicsArchitect,
    )
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect
    from app.simulation.architects.cultural_context import CulturalContextArchitect
    from app.simulation.architects.demographic_interaction import DemographicInteractionArchitect
    from app.simulation.architects.distribution_channel import DistributionChannelArchitect
    from app.simulation.architects.ecosystem_compatibility import EcosystemCompatibilityArchitect
    from app.simulation.architects.enterprise_procurement import EnterpriseProcurementArchitect
    from app.simulation.architects.feature_adoption import FeatureAdoptionArchitect
    from app.simulation.architects.founder_execution import (
        FounderExecutionArchitect,
    )
    from app.simulation.architects.health_safety_hardware import HealthSafetyHardwareArchitect
    from app.simulation.architects.integration_friction import (
        IntegrationFrictionArchitect,
    )
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect
    from app.simulation.architects.market_timing import MarketTimingArchitect
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )
    from app.simulation.architects.messaging_clarity import (
        MessagingClarityArchitect,
    )
    from app.simulation.architects.onboarding import OnboardingArchitect
    from app.simulation.architects.payment_friction import PaymentFrictionArchitect
    from app.simulation.architects.performance_threshold import PerformanceThresholdArchitect
    from app.simulation.architects.physical_sensory import PhysicalSensoryArchitect
    from app.simulation.architects.platform_dependency import (
        PlatformDependencyArchitect,
    )
    from app.simulation.architects.pricing import PricingArchitect
    from app.simulation.architects.purchase_decision import PurchaseDecisionArchitect
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )
    from app.simulation.architects.retention import RetentionArchitect
    from app.simulation.architects.runway import RunwayArchitect
    from app.simulation.architects.setup_first_use import SetupFirstUseArchitect
    from app.simulation.architects.supply_chain import SupplyChainArchitect
    from app.simulation.architects.support_friction import SupportFrictionArchitect
    from app.simulation.architects.sustainability import SustainabilityArchitect
    from app.simulation.architects.trust import TrustArchitect
    from app.simulation.architects.virality import ViralityArchitect

    return {
        "MarketTimingArchitect":           MarketTimingArchitect(),
        "CompetitiveDynamicsArchitect":    CompetitiveDynamicsArchitect(),
        "CulturalContextArchitect":       CulturalContextArchitect(),
        "AccessibilityInclusionArchitect": AccessibilityInclusionArchitect(),
        "SustainabilityArchitect":        SustainabilityArchitect(),
        "MarketplaceLiquidityArchitect":  MarketplaceLiquidityArchitect(),
        "TrustArchitect":                  TrustArchitect(),
        "PaymentFrictionArchitect":        PaymentFrictionArchitect(),
        "PlatformDependencyArchitect":     PlatformDependencyArchitect(),
        "PricingArchitect":                PricingArchitect(),
        "OnboardingArchitect":             OnboardingArchitect(),
        "FeatureAdoptionArchitect":        FeatureAdoptionArchitect(),
        "RetentionArchitect":              RetentionArchitect(),
        "SupportFrictionArchitect":        SupportFrictionArchitect(),
        "ViralityArchitect":               ViralityArchitect(),
        "MacroeconomicArchitect":          MacroeconomicArchitect(),
        "DemographicInteractionArchitect": DemographicInteractionArchitect(),
        "MessagingClarityArchitect":       MessagingClarityArchitect(),
        "AssumptionCascadeArchitect":      AssumptionCascadeArchitect(),
        "PurchaseDecisionArchitect":       PurchaseDecisionArchitect(),
        "PhysicalSensoryArchitect":        PhysicalSensoryArchitect(),
        "PerformanceThresholdArchitect":   PerformanceThresholdArchitect(),
        "SetupFirstUseArchitect":          SetupFirstUseArchitect(),
        "EcosystemCompatibilityArchitect": EcosystemCompatibilityArchitect(),
        "EnterpriseProcurementArchitect":  EnterpriseProcurementArchitect(),
        "DistributionChannelArchitect":    DistributionChannelArchitect(),
        "SupplyChainArchitect":            SupplyChainArchitect(),
        "AftersalesLifecycleArchitect":    AftersalesLifecycleArchitect(),
        "HealthSafetyHardwareArchitect":   HealthSafetyHardwareArchitect(),
        "RegulatoryComplianceArchitect":   RegulatoryComplianceArchitect(),
        "RunwayArchitect":                 RunwayArchitect(),
        "AISkepticismArchitect":           AISkepticismArchitect(),
        "FounderExecutionArchitect":       FounderExecutionArchitect(),
        "BehavioralEconomicsArchitect":    BehavioralEconomicsArchitect(),
        "IntegrationFrictionArchitect":    IntegrationFrictionArchitect(),
    }


# Single shared registry instance — one per process, like the conductor's
# previous module-level ``_ARCHITECTS``.
ARCHITECTS: dict[str, Any] = build_architect_registry()

__all__ = ["ARCHITECTS", "build_architect_registry"]
