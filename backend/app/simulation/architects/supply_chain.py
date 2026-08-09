"""
SupplyChainArchitect — hardware component sourcing, manufacturing and
stockout risk across the 52 consumer clusters.

Hardware startups often fail before a customer ever sees the product:
the design works but the founder depends on one supplier, a component is
on allocation, the MOQ is unaffordable, tariffs eat the margin, or the
first batch misses its ship date. The rest of the engine models
distribution (getting the product to the customer), aftersales
(post-purchase) and manufacturing *cost*, but has no dedicated signal
for supply-chain *risk*: concentration on a single source, lead-time
and logistics exposure, and whether the founder's assumptions prove the
chain can actually deliver at scale.

What this architect does:

* **Exposure detection** — scans assumption text for three signal
  groups: supply-chain engagement (components, suppliers, manufacturing,
  procurement, inventory, lead time, tariffs), explicit risk language
  (shortages, disruptions, single/sole supplier, backorders, MOQ
  constraints), and mitigation planning (dual sourcing, local
  manufacturing, safety stock, long-term agreements). A hardware
  baseline keeps funnels neutral until the founder actually engages
  with supply-chain mechanics.
* **Concentration modelling** — mentioning a single/sole supplier or
  factory raises ``single_source_dependency`` sharply, and impatient,
  low-income and price-sensitive clusters amplify stockout risk: those
  are exactly the segments that abandon a hardware product when the
  chain stalls.
* **Credibility** — evidence of a working chain (signed supplier
  contracts, purchase orders issued, pilot runs, units produced, MOQ
  met, dual sourcing confirmed) raises ``supply_chain_credibility`` to
  1.0, softens the funnel suppressor and earns a small purchase-stage
  ``supply_chain_advantage_lift``. Evidence detection is negation- and
  intent-aware: "no supplier contracts signed", "supply not secured"
  and "we plan to secure suppliers" are gaps, never proof, while "No,
  we already have suppliers signed" stays evidence.
* **Markov overrides** — only when supply-chain exposure is active:
  BROWSE→CONSIDER / CONSIDER→DECIDE are multiplied by the suppressor,
  DECIDE→PURCHASE by ``1 + supply_chain_advantage_lift`` when a working
  chain exists.

Pure compute — no I/O, no DB, no LLM. The Conductor supplies clusters,
agent profiles, assumptions and env params.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from app.simulation.architects.base import (
    ArchitectOutput,
    BaseArchitect,
    DomainReport,
)
from app.simulation.clusters.definitions import ClusterDefinition

# ── Keyword groups (word-boundary, case-insensitive) ────────────────────

_CHAIN_KEYWORDS: tuple[str, ...] = (
    "supply chain", "supply-chain", "supply chain risk", "supply-chain risk",
    "sourcing", "component", "components", "supplier", "suppliers",
    "vendor", "vendors", "manufacturing", "manufacture", "production",
    "assembly", "bom", "bill of materials", "procurement", "inventory",
    "stock", "moq", "minimum order quantity", "lead time", "lead-time",
    "logistics", "shipping", "tariff", "tariffs", "import", "factory",
    "contract manufacturer", "foundry", "semiconductor", "chips",
    "wafer", "pcb", "printed circuit board",
)

_RISK_KEYWORDS: tuple[str, ...] = (
    "single supplier", "sole supplier", "one supplier", "only supplier",
    "single source", "sole source", "single vendor", "single factory",
    "single foundry", "one factory", "one foundry",
    "supply chain risk", "supply-chain risk", "disruption", "disruptions",
    "shortage", "shortages", "scarcity", "chip shortage",
    "semiconductor shortage", "long lead time", "long lead-time",
    "lead time", "lead-time", "backorder", "back-ordered", "backorders",
    "out of stock", "stockout", "stock-out", "unavailable", "allocation",
    "constrained", "bottleneck", "moq", "minimum order quantity",
    "dependency", "dependencies", "dependent", "reliant", "tariff",
    "tariffs", "customs", "import duty", "import duties", "trade war",
    "geopolitical",
)

_DEPENDENCY_KEYWORDS: tuple[str, ...] = (
    "single supplier", "sole supplier", "one supplier", "only supplier",
    "single source", "sole source", "single vendor", "single factory",
    "single foundry", "one factory", "one foundry",
    "relies on one", "rely on one", "depends on one",
    "dependent on one", "dependent on a single",
)

_MITIGATION_KEYWORDS: tuple[str, ...] = (
    "dual sourcing", "second source", "alternate supplier",
    "alternative supplier", "multiple suppliers", "multi-sourcing",
    "local manufacturing", "domestic sourcing", "local supplier",
    "safety stock", "buffer stock", "build inventory", "inventory buffer",
    "pre-order inventory", "forward contract", "long-term agreement",
    "multi-year agreement", "manufacturing partner", "supply agreement",
    "vendor agreement", "consignment", "diversify", "diversified",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "secured supply", "supply secured", "signed supplier",
    "suppliers signed", "supplier contracts signed", "contracts signed",
    "supplier agreements signed", "committed supplier", "confirmed supply",
    "locked-in", "purchase orders", "po issued", "production ready",
    "pilot run", "first batch", "prototypes produced",
    "manufacturing line ready", "moq met", "dual sourced",
    "second source confirmed", "local supplier confirmed",
    "inventory secured", "stock secured", "units produced",
    "initial production", "shipments started", "orders shipped",
)

_TARIFF_KEYWORDS: tuple[str, ...] = (
    "tariff", "tariffs", "customs", "import duty", "import duties",
    "trade war",
)

# Absence markers that qualify a matched phrase ("no supplier contracts
# signed", "supply not secured"). Discourse negation ("No, we already
# have suppliers signed") is handled separately.
_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks", "lacking",
    "missing", "absent", "absence", "unclear", "uncertain", "unknown",
    "unverified", "unconfirmed", "pending", "awaiting", "awaited",
    "outstanding", "incomplete", "suspended", "rejected", "denied",
    "withdrawn", "expired", "revoked", "void", "failed", "unavailable",
    "unsecured", "unsigned",
})

# Aspirational markers: a plan, requirement or roadmap is not proof that
# the chain works. "We plan to secure suppliers", "will issue purchase
# orders" and "need MOQ met" describe intent, not shipped reality.
_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "would", "intend", "intends", "intended",
    "aim", "aims", "hoping", "hope", "hopes", "want", "wants", "wanted",
    "scheduled", "upcoming", "due", "target", "targets", "targeting",
    "looking", "explore", "exploring", "evaluate", "evaluating",
})

# Contracted negations are expanded before matching so "we don't have a
# supplier contract" and "MOQ isn't met" are gaps, never evidence. The
# optional apostrophe also covers no-apostrophe spellings ("dont",
# "havent").
_CONTRACTION_SUFFIXES: dict[str, str] = {
    "isn": "is not", "aren": "are not", "wasn": "was not",
    "weren": "were not", "don": "do not", "doesn": "does not",
    "didn": "did not", "haven": "have not", "hasn": "has not",
    "hadn": "had not", "won": "will not", "wouldn": "would not",
    "can": "cannot", "couldn": "could not", "shouldn": "should not",
    "mustn": "must not", "needn": "need not", "ain": "is not",
}
_CONTRACTION_PATTERN = re.compile(
    r"\b((?:isn|aren|wasn|weren|don|doesn|didn|haven|hasn|hadn|won|"
    r"wouldn|can|couldn|shouldn|mustn|needn|ain))'?t\b"
)
_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[.,;:!?—–\n]|\b(?:but|yet|though|although|whereas|however|while)\b",
    re.IGNORECASE,
)

# Neutral baseline so hardware runs that never mention supply-chain
# mechanics stay unchanged; explicit signals drive real exposure.
_EXPOSURE_BASELINE: float = 0.12
_SIGNAL_STEP: float = 0.18
_EXPOSURE_CAP: float = 0.95
_ACTIVE_THRESHOLD: float = 0.15
_MAX_SUPPRESSION: float = 0.40
_SUPPRESSOR_FLOOR: float = 0.55
_MAX_ADVANTAGE_LIFT: float = 0.10
_SINGLE_SOURCE_BLOCKER: float = 0.55
_WARNING_RISK: float = 0.35


@lru_cache(maxsize=8)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _normalise(text: str) -> str:
    """Lowercase and expand contracted negations for gap detection."""
    lowered = text.lower().replace("’", "'")
    return _CONTRACTION_PATTERN.sub(
        lambda m: _CONTRACTION_SUFFIXES[m.group(1)], lowered
    )


def _assumption_texts(
    assumptions: list[dict[str, Any]] | None,
) -> list[str]:
    """Normalise every assumption to searchable text."""
    texts: list[str] = []
    for assumption in assumptions or []:
        if isinstance(assumption, dict):
            raw = str(assumption.get("text", assumption.get("assumption", "")))
        else:
            raw = str(assumption)
        texts.append(_normalise(raw))
    return texts


def _clause_token_windows(
    text: str,
    start: int,
    end: int,
) -> tuple[list[str], list[str]]:
    """Return the (before, after) token windows within the same clause."""
    before_matches = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = before_matches[-1].end() if before_matches else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-8:]

    after_matches = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = after_matches[0].start() if after_matches else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:6]
    return before, after


def _is_discourse_negation(text: str, start: int) -> bool:
    """True when the only leading negator is discourse ("No, we already…")."""
    prefix = text[:start]
    boundary = max(prefix.rfind(c) for c in ".!?;")
    clause = prefix[boundary + 1:]
    return bool(re.match(r"^\s*(?:no|not|never)\s*[,:;]", clause))


def _is_negated(text: str, start: int, end: int) -> bool:
    """True when a negation/absence marker qualifies a match."""
    before, after = _clause_token_windows(text, start, end)
    if not before and not after:
        return False
    if _is_discourse_negation(text, start):
        before = [t for t in before if t not in {"no", "not", "never"}]
    return bool(
        (set(before[-6:]) | set(after[:4])) & _NEGATION_MARKERS
    )


def _is_intent(text: str, start: int, end: int) -> bool:
    """True when planning/requirement language surrounds an evidence match."""
    before, after = _clause_token_windows(text, start, end)
    return bool(
        (set(before[-6:]) | set(after[:4])) & _INTENT_MARKERS
    )


def _has_keyword(
    assumptions: list[dict[str, Any]] | None,
    keywords: tuple[str, ...],
    *,
    guard_negation: bool = False,
    guard_intent: bool = False,
) -> bool:
    """
    True when any assumption text contains any keyword (word-boundary).

    With ``guard_negation`` a match is ignored when a negation marker
    appears in the same clause, so "no supplier contracts signed" never
    counts as mitigation or evidence. With ``guard_intent`` a match is
    also ignored when planning language ("will", "plan to", "need")
    qualifies it, so aspirations never count as a working supply chain.
    """
    pattern = _keyword_pattern(keywords)
    for text in _assumption_texts(assumptions):
        for match in pattern.finditer(text):
            if guard_negation and _is_negated(
                text, match.start(), match.end()
            ):
                continue
            if guard_intent and _is_intent(
                text, match.start(), match.end()
            ):
                continue
            return True
    return False


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


class SupplyChainArchitect(BaseArchitect):
    """Evaluates hardware component sourcing and stockout risk."""

    @property
    def name(self) -> str:
        return "SupplyChainArchitect"

    @property
    def product_types(self) -> list[str]:
        # Supply-chain mechanics only apply to physical hardware
        # categories; software has no components, MOQs or shipping.
        return [
            "consumer_hardware", "health_hardware", "iot_hardware",
            "wearable", "b2b_hardware", "smart_home",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        patience = _trait(traits, "patience_score")
        income = _trait(traits, "income_level")
        risk_av = _trait(traits, "risk_aversion")
        price_sens = _trait(traits, "price_sensitivity")

        chain_mentioned = _has_keyword(assumptions, _CHAIN_KEYWORDS)
        risk_mentioned = _has_keyword(
            assumptions, _RISK_KEYWORDS, guard_negation=True
        )
        dependency_mentioned = _has_keyword(
            assumptions, _DEPENDENCY_KEYWORDS, guard_negation=True
        )
        mitigation_plan = _has_keyword(
            assumptions, _MITIGATION_KEYWORDS, guard_negation=True
        )
        evidence = _has_keyword(
            assumptions,
            _EVIDENCE_KEYWORDS,
            guard_negation=True,
            guard_intent=True,
        )
        tariff_mentioned = _has_keyword(
            assumptions, _TARIFF_KEYWORDS, guard_negation=True
        )

        # Mitigation planning dampens risk below; it must not inflate
        # exposure the way risk language does.
        mentioned = int(chain_mentioned) + int(risk_mentioned)
        exposure = round(
            min(
                _EXPOSURE_CAP,
                _EXPOSURE_BASELINE + _SIGNAL_STEP * mentioned,
            ),
            4,
        )
        active = exposure > _ACTIVE_THRESHOLD or (
            evidence and mentioned > 0
        )

        # ── Concentration risk ─────────────────────────────────────────
        if evidence:
            single_source_dependency = 0.05
        elif dependency_mentioned:
            single_source_dependency = _clamp(
                0.55 + exposure * 0.50
            )
        else:
            single_source_dependency = exposure * 0.35
        single_source_dependency = round(
            _clamp(single_source_dependency), 4
        )

        # ── Lead-time / sourcing risk ──────────────────────────────────
        if evidence:
            lead_time_risk = 0.05
        else:
            lead_time_risk = exposure * (
                0.40 + 0.60 * float(risk_mentioned)
            )
            if mitigation_plan:
                lead_time_risk *= 0.75
        lead_time_risk = round(_clamp(lead_time_risk), 4)

        sourcing_risk = (
            0.05
            if evidence
            else (
                0.50 * single_source_dependency
                + 0.30 * lead_time_risk
                + 0.20 * exposure
            )
        )
        sourcing_risk = round(_clamp(sourcing_risk), 4)

        # ── Stockout risk (cluster-dependent) ──────────────────────────
        if evidence:
            stockout_risk = 0.05
        else:
            impatience = 1.0 - patience
            cluster_blend = (
                0.45 * impatience
                + 0.25 * (1.0 - income)
                + 0.15 * risk_av
                + 0.15 * price_sens
            )
            stockout_risk = exposure * (
                0.35 + 1.15 * cluster_blend
            )
            if mitigation_plan:
                stockout_risk *= 0.70
        stockout_risk = round(_clamp(stockout_risk), 4)

        # ── Tariff / logistics exposure ────────────────────────────────
        if evidence:
            logistics_tariff_risk = 0.05
        else:
            logistics_tariff_risk = (
                exposure * 0.30 + 0.45 * float(tariff_mentioned)
            )
            if mitigation_plan:
                logistics_tariff_risk *= 0.80
        logistics_tariff_risk = round(_clamp(logistics_tariff_risk), 4)

        credibility = (
            1.0
            if evidence
            else round(max(0.10, 1.0 - exposure * 0.85), 4)
        )

        if not active:
            suppressor = 1.0
        else:
            raw_suppression = max(sourcing_risk, stockout_risk) * (
                0.85 if evidence else 1.0
            )
            suppressor = 1.0 - min(_MAX_SUPPRESSION, raw_suppression)
        suppressor = round(
            _clamp(suppressor, _SUPPRESSOR_FLOOR, 1.0), 4
        )

        lift = (
            round(min(_MAX_ADVANTAGE_LIFT, exposure * 0.10), 4)
            if evidence and active and mentioned > 0
            else 0.0
        )

        flags: dict[str, bool] = {
            "single_source_blocker": (
                single_source_dependency >= _SINGLE_SOURCE_BLOCKER
                and not evidence
            ),
            "sourcing_gap": (
                sourcing_risk >= _WARNING_RISK and not evidence
            ),
            "stockout_gap": (
                stockout_risk >= _WARNING_RISK and not evidence
            ),
            "logistics_tariff_gap": (
                logistics_tariff_risk >= _WARNING_RISK and not evidence
            ),
            "supply_chain_advantage": (
                evidence and active and mentioned > 0
            ),
        }

        severity = (
            "CRITICAL"
            if flags["single_source_blocker"]
            else "WARNING"
            if (
                flags["sourcing_gap"]
                or flags["stockout_gap"]
                or flags["logistics_tariff_gap"]
            )
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "supply_chain_exposure": exposure,
                "single_source_dependency": single_source_dependency,
                "lead_time_risk": lead_time_risk,
                "sourcing_risk": sourcing_risk,
                "stockout_risk": stockout_risk,
                "logistics_tariff_risk": logistics_tariff_risk,
                "supply_chain_credibility": credibility,
                "funnel_suppressor": suppressor,
                "supply_chain_advantage_lift": lift,
            },
            flags=flags,
            narrative_findings=[
                (
                    f"Exposure: {exposure:.2f} | Sourcing: "
                    f"{sourcing_risk:.2f} | Single-source: "
                    f"{single_source_dependency:.2f}"
                ),
                (
                    f"Stockout: {stockout_risk:.2f} | Tariff/logistics: "
                    f"{logistics_tariff_risk:.2f} | Credibility: "
                    f"{credibility:.2f} | Evidence: {evidence}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        exposure = float(
            output.metrics.get("supply_chain_exposure", 0.0)
        )
        advantage = bool(output.flags.get("supply_chain_advantage"))
        if exposure <= _ACTIVE_THRESHOLD and not advantage:
            return {}
        suppressor = float(output.metrics.get("funnel_suppressor", 1.0))
        lift = float(
            output.metrics.get("supply_chain_advantage_lift", 0.0)
        )
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
            o for o in outputs if o.flags.get("single_source_blocker")
        ]
        warning = [
            o
            for o in outputs
            if (
                o.flags.get("sourcing_gap")
                or o.flags.get("stockout_gap")
                or o.flags.get("logistics_tariff_gap")
            )
        ]
        affected = list(
            dict.fromkeys(o.cluster_id for o in critical + warning)
        )
        if not critical and not warning:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No supply-chain blockers detected across clusters"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Keep documenting supplier commitments and "
                    "production evidence as volumes scale"
                ),
                severity="INFO",
            )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters exposed to single-source "
                f"supply risk; {len(warning)} exposed to sourcing, "
                "stockout or tariff gaps"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.05, 3),
            conversion_impact=round(
                len(critical) * 0.05 + len(warning) * 0.02, 3
            ),
            recommended_action=(
                "Dual-source critical components, secure signed supplier "
                "contracts and MOQ-confirmed production before launch"
                if critical
                else (
                    "Mitigate sourcing, stockout and tariff exposure with "
                    "safety stock and confirmed supplier commitments"
                )
            ),
            severity="CRITICAL" if critical else "WARNING",
        )


__all__ = ["SupplyChainArchitect"]
