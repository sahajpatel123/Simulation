from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentBehaviour:
    """
    Architect outputs override raw traits wherever available.
    Priority: architect output → raw trait → hardcoded default.
    """

    cluster_id: str
    agent_profile: dict[str, Any]
    architect_outputs: dict[str, Any]  # Conductor cluster_results[cluster_id]

    # ── convenience accessors ──
    def _pricing(self) -> dict:
        return self.architect_outputs.get("PricingArchitect", {}).get("metrics", {})

    def _onboarding(self) -> dict:
        return self.architect_outputs.get("OnboardingArchitect", {}).get("metrics", {})

    def _retention(self) -> dict:
        return self.architect_outputs.get("RetentionArchitect", {}).get("metrics", {})

    def _trust(self) -> dict:
        return self.architect_outputs.get("TrustArchitect", {}).get("metrics", {})

    def _trait(self, key: str, default: float = 0.5) -> float:
        return float(self.agent_profile.get(key, default))

    # ── decision functions ──

    def should_click_cta(self, price_visible: bool = False) -> bool:
        """
        Price visible → use PricingArchitect.will_pay_probability.
        Otherwise → motivation × trust.
        """
        if price_visible and self._pricing():
            will_pay = self._pricing().get("will_pay_probability", None)
            if will_pay is not None:
                return random.random() < float(will_pay)

        motivation = self._trait("motivation")
        trust_mult = self._trust().get("brand_deficit_multiplier", self._trait("trust"))
        return random.random() < (motivation * 0.6 + float(trust_mult) * 0.4)

    def should_abandon_form(self, field_count: int) -> bool:
        """
        OnboardingArchitect.progressive_disclosure_limit →
        high abandonment if form exceeds limit.
        """
        if self._onboarding():
            limit = int(self._onboarding().get("progressive_disclosure_limit", 6))
            if field_count > limit:
                abandon_prob = min(0.90, 0.50 + (field_count - limit) * 0.12)
                return random.random() < abandon_prob

        patience = self._trait("patience_score")
        return field_count > max(3, int(8 - patience * 5))

    def price_acceptance(self, price: float) -> bool:
        """
        PricingArchitect.price_ceiling is the most accurate gate.
        Falls back to income × price_sensitivity.
        """
        if self._pricing():
            ceiling = self._pricing().get("price_ceiling", None)
            if ceiling is not None:
                return price <= float(ceiling) * 1.05  # 5% tolerance
        income = self._trait("income_level") * 30000
        price_s = self._trait("price_sensitivity")
        ceiling = income * 0.08 / max(price_s, 0.1)
        return price <= ceiling

    def should_scroll(self, scroll_ratio: float) -> bool:
        """
        RetentionArchitect.session_depth_score → deep_work vs quick_check.
        scroll_ratio = current_scroll_px / page_height_px (0.0–1.0)
        """
        if self._retention():
            depth = self._retention().get("session_depth_score", None)
            if depth is not None:
                threshold = 0.80 if float(depth) >= 0.7 else 0.30 if float(depth) <= 0.3 else 0.55
                return scroll_ratio < threshold

        patience = self._trait("patience_score")
        return scroll_ratio < (0.35 + patience * 0.50)

    def should_add_to_cart(self, price: float) -> bool:
        """Combines price acceptance with motivation gate."""
        if not self.price_acceptance(price):
            return False
        motivation = self._trait("motivation")
        return random.random() < (motivation * 0.75)

    def should_request_support(self) -> bool:
        """SupportFrictionArchitect.support_ticket_likelihood."""
        sf = self.architect_outputs.get("SupportFrictionArchitect", {}).get("metrics", {})
        ticket_rate = sf.get("support_ticket_likelihood", None)
        if ticket_rate is not None:
            return random.random() < float(ticket_rate)
        return random.random() < (1 - self._trait("digital_literacy")) * 0.3

    def trust_gate(self) -> bool:
        """
        TrustArchitect.brand_deficit_multiplier — if too low, agent leaves.
        Called once at ARRIVE before any interaction.
        """
        if self._trust():
            bdm = self._trust().get("brand_deficit_multiplier", None)
            if bdm is not None:
                return float(bdm) >= 0.35
        return self._trait("trust") >= 0.25

    def get_interaction_delay(self) -> float:
        """Patience-driven delay between actions in seconds."""
        patience = self._trait("patience_score")
        base = 0.4 + (1 - patience) * 1.8
        return base + random.uniform(-0.2, 0.4)
