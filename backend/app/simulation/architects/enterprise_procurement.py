"""
EnterpriseProcurementArchitect — B2B security-review, vendor-panel,
procurement-cycle and PoC/pilot friction across the 52 consumer clusters.

Startups leak enterprise revenue in the sales cycle, not the funnel: a
security team blocks the vendor for missing SOC 2, procurement refuses a
product that is not on the approved vendor list, legal stalls on MSA/DPA,
and buyers need a 30-day PoC before finance signs off. The rest of the
engine models price, trust, payment and regulatory exposure, but has no
dedicated signal for the procurement machinery that sits between "we want
the product" and "we signed the contract".

What this architect does:

* **Signal detection** — scans assumption text for procurement, security,
  evaluation (PoC/pilot) and sales-led motion signals. A small baseline
  keeps funnels neutral until the founder mentions enterprise buying.
* **Friction modelling** — security-review and vendor-list barriers scale
  with B2B cluster intensity, risk aversion and brand deficit; the
  procurement cycle lengthens with approval depth and shortens with
  self-serve motions; PoC requirement rises when the brief promises pilot
  or evaluation programs without completed evidence.
* **Credibility** — evidence markers (SOC 2, ISO 27001, completed pen
  tests, signed MSA/DPA, approved vendor status, completed pilot) raise
  ``procurement_credibility`` to 1.0, soften the funnel suppressor and
  earn a small purchase-stage ``procurement_advantage_lift``. Detection is
  negation- and intent-aware: "no SOC 2", "not yet approved", "plan to get
  SOC 2" and "vendor panel pending" are gaps, never evidence, while
  "No, we already have SOC 2" stays evidence.
* **Markov overrides** — only when procurement friction is active:
  CONSIDER→DECIDE is multiplied by the suppressor and DECIDE→PURCHASE by
  ``1 - friction/2 + advantage_lift`` when evidence exists.

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

_PROCUREMENT_KEYWORDS: tuple[str, ...] = (
    "procurement", "vendor panel", "approved vendor list", "vendor approval",
    "vendor approvals", "vendor onboarding", "purchase order", "po required",
    "rfp", "request for proposal", "rfq", "request for quotation", "tender",
    "budget approval", "finance approval", "approval chain", "sign-off",
    "committee approval", "stakeholder approval", "multi-stakeholder",
    "contract review", "legal review", "msa", "dpa",
    "master service agreement", "data processing agreement",
    "vendor risk", "third-party risk", "sourcing", "vendor evaluation",
    "procurement cycle", "procurement team", "vendor list",
)

_SECURITY_KEYWORDS: tuple[str, ...] = (
    "security review", "security audit", "security assessment",
    "soc 2", "soc2", "iso 27001", "iso27001", "penetration test",
    "pen test", "pentest", "vulnerability assessment",
    "security questionnaire", "vendor risk assessment",
    "third-party risk", "vapt", "data processing agreement",
)

_EVALUATION_KEYWORDS: tuple[str, ...] = (
    "proof of concept", "poc", "pilot", "pilot program", "pilot customers",
    "evaluation", "evaluation period", "evaluation license",
    "technical review", "architecture review", "30-day evaluation",
    "90-day pilot", "vendor evaluation", "demo", "trial",
)

_SALES_KEYWORDS: tuple[str, ...] = (
    "sales-led", "sales led", "sales team", "sales cycle",
    "account executive", "account executives", "sales call",
    "sales engagement", "field sales", "direct sales", "enterprise sales",
    "sales assistance", "sales motion",
)

_SELF_SERVE_KEYWORDS: tuple[str, ...] = (
    "self-serve", "self serve", "self service", "self-serve plan",
    "self-serve signup", "self-serve sign up", "self onboarding",
    "free trial", "no sales", "no sales calls", "no sales team",
    "self service signup",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "soc 2", "soc2", "soc 2 type ii", "soc 2 type 2", "soc 2 report",
    "soc 2 attested", "iso 27001", "iso27001", "iso 27001 certified",
    "iso 27001 certification", "penetration test completed",
    "pen test completed", "pentest completed", "vapt completed",
    "security review passed", "security audit passed",
    "security assessment completed", "security questionnaire completed",
    "vendor risk assessment completed", "msa signed", "dpa signed",
    "data processing agreement signed", "master service agreement signed",
    "signed msa", "signed dpa", "approved vendor", "vendor panel approved",
    "on approved vendor list", "vendor approved", "vendor onboarding complete",
    "procurement approved", "purchase order issued", "legal approved",
    "legal clearance", "contract signed", "pilot completed", "poc completed",
    "proof of concept completed", "poc validated", "pilot validated",
    "evaluation completed", "case study", "reference customer",
    "enterprise customers", "security review complete",
)

# Absence markers that qualify a matched phrase ("no SOC 2", "vendor
# approval missing", "contract not signed"). Discourse negation
# ("No, we already have SOC 2") is handled separately.
_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks", "lacking",
    "missing", "absent", "absence", "unclear", "uncertain", "unknown",
    "unverified", "unapproved", "unsigned", "unavailable", "unreleased",
    "unsupported", "unconfirmed", "pending", "awaiting", "awaited",
    "outstanding", "incomplete", "suspended", "rejected", "denied",
    "withdrawn", "expired", "revoked", "void", "failed",
})

# Aspirational markers: a plan, requirement or roadmap is not evidence.
# "We plan to get SOC 2", "will add MSA/DPA templates", "vendor panel
# scheduled for Q3" describe intent, not a working procurement path.
_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "intend", "intends", "intended", "add",
    "adding", "build", "building", "aim", "aims", "hoping", "hope",
    "hopes", "want", "wants", "wanted", "scheduled", "upcoming", "due",
    "set", "setting", "setup", "integrate", "integrating", "getting",
    "get", "obtain", "obtaining", "pursue", "pursuing", "working on",
    "in progress", "to be",
})

# Contracted negations are expanded before matching so "don't have SOC 2"
# and "vendor approval isn't complete" are gaps, never evidence. The
# optional apostrophe also covers no-apostrophe spellings ("dont", "arent").
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

_B2B_PRODUCT_TYPES: tuple[str, ...] = (
    "saas", "developer_tool", "enterprise_software",
    "b2b_hardware", "b2b_marketplace", "productivity_tool",
)

_B2B_AFFINITIES: frozenset[str] = frozenset({
    "saas", "developer_tool", "enterprise_software",
    "b2b_hardware", "b2b_marketplace", "productivity_tool",
    "marketplace",
})

_B2B_TOKEN_WEIGHTS: dict[str, float] = {
    "enterprise": 0.50,
    "b2b": 0.50,
    "smb": 0.40,
    "procurement": 0.50,
    "decision_maker": 0.40,
    "it_decision": 0.40,
    "technical_founder": 0.40,
    "co_founder": 0.30,
    "founder": 0.20,
    "gatekeeper": 0.50,
    "business_owner": 0.30,
    "evaluator": 0.30,
    "professional": 0.10,
}

# Neutral baseline so runs that never mention enterprise buying stay
# unchanged; explicit signals drive the real exposure.
_EXPOSURE_BASELINE: float = 0.06
_SIGNAL_STEP: float = 0.22
_EXPOSURE_CAP: float = 0.95
_ACTIVE_THRESHOLD: float = 0.15
_MAX_FRICTION: float = 0.85
_SUPPRESSOR_FLOOR: float = 0.25
_ADVANTAGE_LIFT: float = 0.08
_GATE_CRITICAL_THRESHOLD: float = 0.50


@lru_cache(maxsize=8)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one word-boundary pattern per keyword group (cached)."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )


def _normalise(text: str) -> str:
    """Lowercase and expand common contracted negations."""
    lowered = text.lower()
    return _CONTRACTION_PATTERN.sub(
        lambda m: f"{_CONTRACTION_SUFFIXES[m.group(1)]} not", lowered
    )


def _assumption_texts(assumptions: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for assumption in assumptions:
        if isinstance(assumption, dict):
            raw = str(assumption.get("text", assumption.get("assumption", "")))
        else:
            raw = str(assumption)
        texts.append(_normalise(raw))
    return texts


def _has_signal(
    assumptions: list[dict[str, Any]],
    keywords: tuple[str, ...],
) -> bool:
    pattern = _keyword_pattern(keywords)
    return any(pattern.search(text) for text in _assumption_texts(assumptions))


def _is_discourse_negation(before_tokens: list[str]) -> bool:
    """True for "not only" openings that do not void the matched phrase."""
    return before_tokens[:2] == ["not", "only"]


def _match_is_voided(
    text: str,
    start: int,
    end: int,
) -> bool:
    """True when negation or intent markers qualify an evidence match."""
    clause_matches_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = clause_matches_before[-1].end() if clause_matches_before else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-8:]

    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:8]

    if _is_discourse_negation(before):
        return False
    if after and after[0] in {"and", "or", "then", "also", "plus", "too"}:
        after = []
    before_text = " ".join(before)
    after_text = " ".join(after)
    if any(
        phrase in f"{before_text} {after_text}"
        for phrase in ("working on", "in progress", "to be")
    ):
        return True
    return bool(
        set(before + after) & (_NEGATION_MARKERS | _INTENT_MARKERS)
    )


def _has_evidence(assumptions: list[dict[str, Any]]) -> bool:
    pattern = _keyword_pattern(_EVIDENCE_KEYWORDS)
    for text in _assumption_texts(assumptions):
        for match in pattern.finditer(text):
            if not _match_is_voided(text, match.start(), match.end()):
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


class EnterpriseProcurementArchitect(BaseArchitect):
    """Evaluates B2B procurement friction across consumer clusters."""

    @property
    def name(self) -> str:
        return "EnterpriseProcurementArchitect"

    @property
    def product_types(self) -> list[str]:
        # Active for products with a meaningful B2B buying motion. Consumer
        # product types are deliberately excluded; their buyers do not run
        # security reviews or vendor panels.
        return list(_B2B_PRODUCT_TYPES)

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        risk_av = _trait(traits, "risk_aversion")
        product_type = str(env_params.get("product_type", "saas")).lower()
        brand_deficit = _trait(
            agent_profile, "brand_deficit_multiplier", default=0.8
        )
        urgency = _trait(
            agent_profile, "problem_urgency_intensity", default=0.5
        )

        b2b_rel = self._b2b_relevance(cluster, product_type)
        proc_signal = _has_signal(assumptions, _PROCUREMENT_KEYWORDS)
        sec_signal = _has_signal(assumptions, _SECURITY_KEYWORDS)
        eval_signal = _has_signal(assumptions, _EVALUATION_KEYWORDS)
        sales_signal = _has_signal(assumptions, _SALES_KEYWORDS)
        self_serve = _has_signal(assumptions, _SELF_SERVE_KEYWORDS)
        evidence = _has_evidence(assumptions)

        signal_count = sum(
            bool(sig) for sig in (proc_signal, sec_signal, eval_signal, sales_signal)
        )
        exposure = round(
            min(
                _EXPOSURE_CAP,
                (_EXPOSURE_BASELINE + signal_count * _SIGNAL_STEP)
                * (0.35 + 0.65 * b2b_rel),
            ),
            4,
        )
        active = exposure > _ACTIVE_THRESHOLD and b2b_rel > 0.2

        approval_depth = self._approval_depth(cluster, risk_av)
        security_barrier = self._security_barrier(
            sec_signal, evidence, b2b_rel, risk_av, brand_deficit
        )
        vendor_barrier = self._vendor_barrier(
            cluster, proc_signal, evidence, b2b_rel
        )
        poc_requirement = self._poc_requirement(
            eval_signal, evidence, risk_av, approval_depth
        )
        cycle_days = self._cycle_days(
            cluster, proc_signal, evidence, risk_av, urgency, self_serve
        )
        sales_assistance = self._sales_assistance(
            sales_signal, self_serve, approval_depth
        )

        if active:
            friction = _clamp(
                (
                    0.35 * security_barrier
                    + 0.25 * vendor_barrier
                    + 0.20 * min(1.0, cycle_days / 90.0)
                    + 0.20 * poc_requirement
                )
                * (0.55 + 0.45 * approval_depth),
                high=_MAX_FRICTION,
            )
            credibility = 1.0 if evidence else 0.88
            suppressor = max(
                _SUPPRESSOR_FLOOR,
                1.0 - friction,
            )
            advantage_lift = _ADVANTAGE_LIFT if evidence else 0.0
        else:
            friction = 0.0
            credibility = 1.0
            suppressor = 1.0
            advantage_lift = 0.0
            # Keep all benchmarked friction metrics neutral when the
            # founder's brief never mentions enterprise buying, so the
            # architect cannot outrank unrelated failure domains in
            # accountability on pure cluster demographics.
            security_barrier = 0.0
            vendor_barrier = 0.0
            poc_requirement = 0.0
            cycle_days = 0.0
            sales_assistance = 0.0

        security_blocker = (
            active and sec_signal and not evidence and security_barrier >= 0.35
        )
        vendor_blocked = (
            active and proc_signal and not evidence and vendor_barrier >= 0.35
        )
        poc_required = (
            active and eval_signal and poc_requirement >= 0.45
        )
        sales_required = active and sales_assistance >= 0.50
        gate_critical = active and friction >= _GATE_CRITICAL_THRESHOLD

        severity = (
            "CRITICAL"
            if gate_critical or (security_blocker and vendor_blocked)
            else "WARNING"
            if security_blocker or vendor_blocked or poc_required or sales_required
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "procurement_relevance":         round(b2b_rel, 4),
                "procurement_exposure":          exposure,
                "approval_chain_depth":          round(approval_depth, 4),
                "security_review_barrier":       round(security_barrier, 4),
                "vendor_list_barrier":           round(vendor_barrier, 4),
                "procurement_cycle_days":        round(cycle_days, 1),
                "poc_requirement":               round(poc_requirement, 4),
                "sales_assistance_requirement":  round(sales_assistance, 4),
                "procurement_friction":          round(friction, 4),
                "procurement_credibility":       round(credibility, 4),
                "funnel_suppressor":             round(suppressor, 4),
                "procurement_advantage_lift":    round(advantage_lift, 4),
            },
            flags={
                "procurement_gate_critical":     gate_critical,
                "security_review_blocker":       security_blocker,
                "vendor_panel_blocked":          vendor_blocked,
                "poc_required":                  poc_required,
                "sales_assistance_required":     sales_required,
                "procurement_advantage":         active and evidence,
            },
            narrative_findings=[
                f"Procurement exposure: {exposure * 100:.0f}% | "
                f"Friction: {friction:.2f}",
                f"Security review: {security_barrier:.2f} | "
                f"Cycle: {cycle_days:.0f} days",
            ],
            severity=severity,
        )

    def _b2b_relevance(
        self,
        cluster: ClusterDefinition,
        product_type: str,
    ) -> float:
        if product_type not in _B2B_PRODUCT_TYPES:
            return 0.0
        score = 0.0
        for token, weight in _B2B_TOKEN_WEIGHTS.items():
            if token in cluster.cluster_id:
                score += weight
        if any(aff in _B2B_AFFINITIES for aff in cluster.product_affinities):
            score += 0.2
        return _clamp(score)

    def _approval_depth(
        self,
        cluster: ClusterDefinition,
        risk_av: float,
    ) -> float:
        if any(
            token in cluster.cluster_id
            for token in ("enterprise_procurement_gatekeeper", "senior_enterprise")
        ):
            base = 0.85
        elif any(
            token in cluster.cluster_id
            for token in ("mid_market", "it_decision", "non_technical", "technical_founder")
        ):
            base = 0.65
        elif any(
            token in cluster.cluster_id
            for token in ("smb", "business_owner", "founder")
        ):
            base = 0.40
        else:
            base = 0.20
        return _clamp(base + risk_av * 0.15)

    def _security_barrier(
        self,
        sec_signal: bool,
        evidence: bool,
        b2b_rel: float,
        risk_av: float,
        brand_deficit: float,
    ) -> float:
        if sec_signal:
            barrier = 0.55 + risk_av * 0.20 + (1.0 - brand_deficit) * 0.15
        else:
            barrier = 0.12 * b2b_rel
        if evidence:
            barrier *= 0.15
        return _clamp(barrier)

    def _vendor_barrier(
        self,
        cluster: ClusterDefinition,
        proc_signal: bool,
        evidence: bool,
        b2b_rel: float,
    ) -> float:
        if "enterprise_procurement_gatekeeper" in cluster.cluster_id:
            barrier = 0.75 if proc_signal else 0.45
        elif any(
            token in cluster.cluster_id
            for token in ("senior_enterprise", "mid_market", "it_decision")
        ):
            barrier = 0.45 if proc_signal else 0.25
        else:
            barrier = 0.25 * proc_signal + 0.10 * b2b_rel
        if evidence:
            barrier *= 0.15
        return _clamp(barrier)

    def _poc_requirement(
        self,
        eval_signal: bool,
        evidence: bool,
        risk_av: float,
        approval_depth: float,
    ) -> float:
        if eval_signal:
            requirement = 0.55 + risk_av * 0.25
            if approval_depth > 0.6:
                requirement += 0.10
        else:
            requirement = 0.10 + 0.10 * approval_depth
        if evidence:
            requirement *= 0.20
        return _clamp(requirement)

    def _cycle_days(
        self,
        cluster: ClusterDefinition,
        proc_signal: bool,
        evidence: bool,
        risk_av: float,
        urgency: float,
        self_serve: bool,
    ) -> float:
        if any(
            token in cluster.cluster_id
            for token in ("enterprise_procurement_gatekeeper", "senior_enterprise")
        ):
            base = 42.0
        elif any(
            token in cluster.cluster_id
            for token in ("mid_market", "it_decision", "non_technical")
        ):
            base = 21.0
        else:
            base = 7.0
        cycle = (
            base
            + risk_av * 28.0
            - urgency * 12.0
            + (10.0 if proc_signal else 0.0)
            - (12.0 if self_serve else 0.0)
        )
        if evidence:
            cycle *= 0.55
        return _clamp(cycle, low=3.0, high=180.0)

    def _sales_assistance(
        self,
        sales_signal: bool,
        self_serve: bool,
        approval_depth: float,
    ) -> float:
        if self_serve:
            return 0.10
        if sales_signal:
            return _clamp(0.50 + approval_depth * 0.35, high=0.90)
        return _clamp(0.15 + approval_depth * 0.25, high=0.70)

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        suppressor = float(output.metrics.get("funnel_suppressor", 1.0))
        friction = float(output.metrics.get("procurement_friction", 0.0))
        advantage_lift = float(output.metrics.get("procurement_advantage_lift", 0.0))
        if suppressor >= 1.0 and friction <= 0.0:
            return {}
        return {
            ("CONSIDER", "DECIDE"): max(
                0.05, min(0.95, suppressor)
            ),
            ("DECIDE", "PURCHASE"): max(
                0.05, min(1.05, 1.0 - friction * 0.5 + advantage_lift)
            ),
        }

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        critical = [o for o in outputs if o.flags.get("procurement_gate_critical")]
        blockers = [
            o for o in outputs
            if o.flags.get("security_review_blocker")
            or o.flags.get("vendor_panel_blocked")
        ]
        affected = list({o.cluster_id for o in critical + blockers})
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters blocked by procurement gates; "
                f"{len(blockers)} with security/vendor review gaps"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.03, 3),
            conversion_impact=round(
                len(critical) * 0.04 + len(blockers) * 0.02, 3
            ),
            recommended_action=(
                "Publish SOC 2/security evidence, MSA/DPA templates and a "
                "PoC/pilot path; support procurement sign-off"
            ),
            severity="CRITICAL" if critical else "WARNING" if blockers else "INFO",
        )


__all__ = ["EnterpriseProcurementArchitect"]
