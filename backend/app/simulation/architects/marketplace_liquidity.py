"""
MarketplaceLiquidityArchitect — two-sided marketplace cold-start and
liquidity risk across the 52 consumer clusters.

Marketplaces die when one side of the market is empty: buyers browse but
there are no sellers or listings, or sellers sign up but there is no demand.
The rest of the engine models virality, pricing, trust and distribution,
but has no dedicated signal for whether the founder's own assumptions
address marketplace liquidity and the chicken-and-egg problem.

What this architect does:

* **Exposure detection** — scans assumption text for three signal groups:
  explicit liquidity language (cold start, network effects, two-sided
  matching), supply-side planning (sellers, inventory, onboarding), and
  demand-side planning (buyers, waitlist, acquisition). A small baseline
  keeps funnels neutral until the founder actually mentions the market.
* **Cold-start modelling** — exposure scales with distrustful,
  price-sensitive, low-literacy and low-income clusters, which are exactly
  the clusters that abandon an empty marketplace first. Supply/demand
  plans reduce but do not eliminate side risk; evidence (signed-up sellers,
  buyer waitlist, pre-orders, anchor supply) is the only proof that clears
  a cold-start blocker.
* **Credibility** — liquidity evidence raises ``liquidity_credibility`` to
  1.0, softens the funnel suppressor and earns a small purchase-stage
  ``liquidity_advantage_lift``. Evidence detection is negation-aware:
  "no sellers signed up", "no buyer waitlist" or "pre-orders not confirmed"
  are treated as gaps, never proof.
* **Markov overrides** — only when liquidity exposure is active:
  BROWSE→CONSIDER / CONSIDER→DECIDE are multiplied by the suppressor,
  DECIDE→PURCHASE by ``1 + liquidity_advantage_lift`` when evidence exists.

Pure compute — no I/O, no DB, no LLM. The Conductor supplies clusters,
agent profiles, assumptions and env params.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition

# ── Keyword groups (word-boundary, case-insensitive) ────────────────────

_LIQUIDITY_KEYWORDS: tuple[str, ...] = (
    "liquidity", "two-sided", "two sided", "buyers and sellers",
    "sellers and buyers", "supply and demand", "demand and supply",
    "chicken and egg", "chicken-and-egg", "cold start", "cold-start",
    "critical mass", "network effects", "network effect", "matching",
    "matchmaking", "market depth", "marketplace",
)

_SUPPLY_KEYWORDS: tuple[str, ...] = (
    "supply side", "supply-side", "suppliers", "supplier onboarding",
    "seller onboarding", "onboard sellers", "recruit sellers",
    "vendor", "vendors", "inventory", "listings", "sellers",
    "supply", "sourcing", "fulfillment", "fulfilment", "seed supply",
)

_DEMAND_KEYWORDS: tuple[str, ...] = (
    "demand side", "demand-side", "buyers", "buyer acquisition",
    "recruit buyers", "waitlist", "pre-orders", "preorders",
    "early access", "demand generation", "customer acquisition",
    "demand",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "secured supply", "signed up sellers", "signed-up sellers",
    "sellers signed up", "buyers signed up", "sellers onboarded",
    "buyers onboarded", "supply secured", "demand secured",
    "seller commitments", "supply agreements", "supplier contracts",
    "letters of intent", "pre-registered sellers",
    "preregistered sellers", "launch inventory", "anchor sellers",
    "anchor suppliers", "launch partners", "pilot customers",
    "pilot sellers", "buyer waitlist", "pre-orders", "preorders",
    "guaranteed supply", "guaranteed inventory", "guaranteed buyers",
    "committed sellers", "contracts with suppliers",
    "confirmed supply", "confirmed demand",
)

_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks",
    "lacking", "missing", "absent", "absence", "unclear", "uncertain",
    "unknown", "unverified", "unconfirmed", "pending", "awaiting",
    "awaited", "outstanding", "void", "expired", "revoked", "rejected",
    "denied", "withdrawn", "incomplete", "suspended", "unavailable",
})

# Neutral baseline so runs that never mention marketplace mechanics stay
# unchanged; marketplaces always carry some liquidity risk, but below the
# override threshold until an explicit signal appears.
_BASELINE_EXPOSURE: float = 0.12
_SIGNAL_STEP: float = 0.20
_EXPOSURE_CAP: float = 0.95
_ACTIVE_THRESHOLD: float = 0.15
_SUPPRESSOR_MIN: float = 0.55
_MAX_SUPPRESSION: float = 0.40
_MAX_ADVANTAGE_LIFT: float = 0.12
_COLD_START_BLOCKER: float = 0.55
_SIDE_RISK_FLAG: float = 0.35


@lru_cache(maxsize=8)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _has_any_keyword(
    assumptions: list[dict[str, Any]] | None,
    keywords: tuple[str, ...],
    *,
    guard_negation: bool = False,
) -> bool:
    """
    True when any assumption text contains any keyword (word-boundary).

    With ``guard_negation``, a match is ignored when a negation/absence
    marker appears within ~5 words around it, so "no sellers signed up"
    or "pre-orders not confirmed" never counts as liquidity evidence.
    """
    if not assumptions:
        return False
    pattern = _keyword_pattern(keywords)
    for assumption in assumptions:
        if isinstance(assumption, dict):
            text = str(
                assumption.get("text", assumption.get("assumption", ""))
            ).lower()
        else:
            text = str(assumption).lower()
        if not guard_negation:
            if pattern.search(text):
                return True
            continue
        for match in pattern.finditer(text):
            if not _is_negated(text, match.start(), match.end()):
                return True
    return False


def _is_negated(text: str, start: int, end: int) -> bool:
    """True when a negation/absence marker sits within ~5 words of a match."""
    before = re.findall(r"[a-z]+", text[max(0, start - 120):start])[-5:]
    after = re.findall(r"[a-z]+", text[end:end + 120])[:5]
    return bool(set(before + after) & _NEGATION_MARKERS)


def _trait(traits: dict[str, Any], key: str, default: float = 0.5) -> float:
    """Parse one trait value, falling back to ``default`` on garbage input."""
    value = traits.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class MarketplaceLiquidityArchitect(BaseArchitect):
    """Evaluates two-sided marketplace liquidity and cold-start risk."""

    @property
    def name(self) -> str:
        return "MarketplaceLiquidityArchitect"

    @property
    def product_types(self) -> list[str]:
        # Two-sided liquidity mechanics only apply to marketplace categories;
        # other product types have no matching/supply-demand cold-start.
        return ["marketplace", "b2b_marketplace"]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        trust = _trait(traits, "trust")
        price_sens = _trait(traits, "price_sensitivity")
        literacy = _trait(traits, "digital_literacy")
        income = _trait(traits, "income_level")

        liquidity_mentioned = _has_any_keyword(
            assumptions, _LIQUIDITY_KEYWORDS
        )
        supply_mentioned = _has_any_keyword(
            assumptions, _SUPPLY_KEYWORDS
        )
        demand_mentioned = _has_any_keyword(
            assumptions, _DEMAND_KEYWORDS
        )
        # Negated mentions ("no sellers signed up", "buyer waitlist
        # missing") raise exposure but do not count as a plan.
        supply_plan = _has_any_keyword(
            assumptions, _SUPPLY_KEYWORDS, guard_negation=True
        )
        demand_plan = _has_any_keyword(
            assumptions, _DEMAND_KEYWORDS, guard_negation=True
        )
        evidence = _has_any_keyword(
            assumptions, _EVIDENCE_KEYWORDS, guard_negation=True
        )

        mentioned = (
            int(liquidity_mentioned)
            + int(supply_mentioned)
            + int(demand_mentioned)
        )
        exposure = round(
            min(
                _EXPOSURE_CAP,
                _BASELINE_EXPOSURE + _SIGNAL_STEP * mentioned,
            ),
            4,
        )
        active = exposure > _ACTIVE_THRESHOLD or (
            evidence and mentioned > 0
        )

        # ── Cold-start risk ─────────────────────────────────────────────
        # Distrustful, price-sensitive, low-literacy and low-income
        # clusters abandon an empty marketplace first.
        cluster_blend = (
            0.45 * (1.0 - trust)
            + 0.30 * price_sens
            + 0.15 * (1.0 - literacy)
            + 0.10 * (1.0 - income)
        )
        cold_start_risk = _clamp(
            exposure * (0.30 + 1.25 * cluster_blend)
        )
        if evidence:
            cold_start_risk *= 0.45
        cold_start_risk = round(_clamp(cold_start_risk), 4)

        # ── Supply / demand side risk ───────────────────────────────────
        # A stated plan reduces (but does not eliminate) side risk;
        # evidence is the only signal that removes it entirely.
        if evidence:
            supply_side_risk = 0.05
            demand_side_risk = 0.05
        else:
            supply_side_risk = _clamp(
                exposure * (0.55 + 0.55 * float(not supply_plan))
            )
            demand_side_risk = _clamp(
                exposure * (0.55 + 0.55 * float(not demand_plan))
            )
        supply_side_risk = round(supply_side_risk, 4)
        demand_side_risk = round(demand_side_risk, 4)

        # ── Matching friction + credibility + funnel impact ─────────────
        matching_friction = round(
            _clamp(
                cold_start_risk
                * (0.40 + 0.60 * (1.0 - trust))
            ),
            4,
        )
        credibility = (
            1.0 if evidence else max(0.10, 1.0 - exposure * 0.85)
        )
        credibility = round(_clamp(credibility), 4)

        if not active:
            suppressor = 1.0
        else:
            raw_suppression = cold_start_risk * (
                0.80 if evidence else 1.0
            )
            suppressor = 1.0 - min(_MAX_SUPPRESSION, raw_suppression)
        suppressor = round(_clamp(suppressor, _SUPPRESSOR_MIN, 1.0), 4)

        lift = (
            round(min(_MAX_ADVANTAGE_LIFT, exposure * 0.10), 4)
            if evidence and active and mentioned > 0
            else 0.0
        )

        flags: dict[str, bool] = {
            "cold_start_blocker": (
                cold_start_risk >= _COLD_START_BLOCKER and not evidence
            ),
            "supply_side_gap": (
                supply_side_risk >= _SIDE_RISK_FLAG and not evidence
            ),
            "demand_side_gap": (
                demand_side_risk >= _SIDE_RISK_FLAG and not evidence
            ),
            "liquidity_advantage": evidence and mentioned > 0,
        }

        severity = (
            "CRITICAL"
            if flags["cold_start_blocker"]
            else "WARNING"
            if flags["supply_side_gap"] or flags["demand_side_gap"]
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "marketplace_liquidity_exposure": exposure,
                "cold_start_risk": cold_start_risk,
                "supply_side_risk": supply_side_risk,
                "demand_side_risk": demand_side_risk,
                "matching_friction": matching_friction,
                "liquidity_credibility": credibility,
                "funnel_suppressor": suppressor,
                "liquidity_advantage_lift": lift,
            },
            flags=flags,
            narrative_findings=[
                (
                    f"Liquidity exposure: {exposure:.2f} | "
                    f"Cold-start: {cold_start_risk:.2f} | "
                    f"Supply: {supply_side_risk:.2f} | "
                    f"Demand: {demand_side_risk:.2f}"
                ),
                (
                    f"Credibility: {credibility:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f} | "
                    f"Evidence: {evidence}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        exposure = float(
            output.metrics.get("marketplace_liquidity_exposure", 0.0)
        )
        if exposure <= _ACTIVE_THRESHOLD:
            return {}
        suppressor = float(output.metrics.get("funnel_suppressor", 1.0))
        lift = float(output.metrics.get("liquidity_advantage_lift", 0.0))
        overrides: dict[tuple[str, str], float] = {}
        if suppressor < 1.0:
            overrides[("BROWSE", "CONSIDER")] = _clamp(
                suppressor, 0.55, 0.999
            )
            overrides[("CONSIDER", "DECIDE")] = _clamp(
                suppressor + 0.05, 0.60, 0.999
            )
        if lift > 0.0:
            overrides[("DECIDE", "PURCHASE")] = _clamp(
                1.0 + lift, 0.55, 1.15
            )
        return overrides

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [
            o
            for o in outputs
            if o.flags.get("cold_start_blocker")
        ]
        warning = [
            o
            for o in outputs
            if o.flags.get("supply_side_gap")
            or o.flags.get("demand_side_gap")
        ]
        affected = list(
            dict.fromkeys(o.cluster_id for o in critical + warning)
        )
        if not critical and not warning:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No marketplace liquidity blockers detected across clusters"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Keep documenting supply/demand evidence as the "
                    "marketplace scales"
                ),
                severity="INFO",
            )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters blocked by marketplace cold start; "
                f"{len(warning)} exposed to one-sided liquidity gaps"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.05, 3),
            conversion_impact=round(
                len(critical) * 0.05 + len(warning) * 0.02, 3
            ),
            recommended_action=(
                "Seed both sides before launch: signed-up sellers, buyer "
                "waitlist, anchor supply and guaranteed demand"
            ),
            severity="CRITICAL" if critical else "WARNING",
        )


__all__ = ["MarketplaceLiquidityArchitect"]
