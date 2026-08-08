"""
RegulatoryComplianceArchitect — privacy, financial, health, certification and
consumer-protection exposure across the 52 consumer clusters.

Startups fail (or stall) when their regulatory path is unmapped: data-privacy
requirements scare off privacy-sensitive buyers, certification gaps block
hardware/health purchases, missing refund and warranty policies raise
liability concerns, and unresolved compliance questions depress trust. The
rest of the engine models price, trust, retention and distribution, but has
no dedicated signal for the regulatory burden baked into the founder's own
assumptions.

What this architect does:

* **Exposure detection** — scans assumption text for five regulatory signal
  groups (privacy/data, financial, health, certification, consumer
  protection). The product type contributes a small baseline only; explicit
  signals drive the real exposure so funnels stay unchanged for runs that
  never mention regulation.
* **Concern modelling** — privacy concern scales with cluster distrust,
  risk aversion, literacy and income; refund/liability concern scales with
  price sensitivity and low income; certification barriers are raised for
  hardware/health/enterprise categories.
* **Credibility** — compliance evidence markers (certified, approved,
  licensed, audited, ISO, privacy policy, ...) raise ``compliance_credibility``
  to 1.0, remove the ``certification_gate`` flag and soften the funnel
  suppressor, and earn a small purchase-stage ``regulatory_advantage_lift``.
  Evidence and consumer-policy detection is negation-aware: statements such
  as "not yet certified", "no approval obtained" or "no refund policy" are
  treated as gaps, never as evidence, and broad words such as "legal" or
  "returns" only count inside concrete phrases ("legal team", "return
  policy") so legal risk and ROI talk cannot clear the compliance gate.
* **Markov overrides** — only when explicit regulatory exposure exists:
  BROWSE→CONSIDER / CONSIDER→DECIDE are multiplied by the suppressor,
  DECIDE→PURCHASE by ``1 + regulatory_advantage_lift`` when compliance
  evidence is present.

Pure compute — no I/O, no DB, no LLM. The Conductor supplies clusters,
agent profiles, assumptions and env params.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition

# ── Keyword groups (word-boundary, case-insensitive) ────────────────────

_PRIVACY_KEYWORDS: tuple[str, ...] = (
    "privacy", "personal data", "data protection", "dpdp", "gdpr",
    "consent", "opt-in", "biometric", "health data", "location data",
    "telemetry", "data breach", "surveillance", "camera",
    "microphone", "encryption", "anonymised", "anonymized",
)

_FINANCIAL_KEYWORDS: tuple[str, ...] = (
    "rbi", "sebi", "kyc", "payment", "payments", "pci", "escrow",
    "lending", "loan", "insurance", "upi", "gst", "tax", "fintech",
    "money transfer", "wallet", "crypto", "securities", "credit",
    "interest", "prepaid",
)

_HEALTH_KEYWORDS: tuple[str, ...] = (
    "fda", "cdsco", "medical", "clinical", "drug", "diagnostic",
    "health data", "hospital", "doctor", "pharmacy", "medication",
    "vaccine", "blood pressure", "glucose", "prescription",
)

_CERTIFICATION_KEYWORDS: tuple[str, ...] = (
    "certification", "certified", "approval", "approved", "bis", "iso",
    "ce mark", "fssai", "licence", "license", "licensed", "compliance",
    "compliant", "regulatory", "regulated", "audit", "audited",
    "quality standard", "agmark", "epr", "registration",
)

_CONSUMER_PROTECTION_KEYWORDS: tuple[str, ...] = (
    "liability", "recall", "consumer protection",
)

_CONSUMER_POLICY_KEYWORDS: tuple[str, ...] = (
    "refund", "refundable", "return policy", "returns policy",
    "free returns", "easy returns", "30-day returns", "60-day returns",
    "money-back guarantee", "satisfaction guarantee", "quality guarantee",
    "guaranteed refund", "warranty", "replacement policy", "repair policy",
    "cancellation policy",
)

_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "certified", "certification", "approved", "compliant", "licensed",
    "audited", "iso", "ce mark", "fssai", "fda approved", "cdsco",
    "rbi approved", "dpdp compliant", "gdpr compliant", "privacy policy",
    "terms of service", "encryption", "consent", "opt-in",
    "refund policy", "return policy", "warranty", "compliance team",
    "privacy by design", "data minimisation", "data minimization",
    "legal team", "legal review", "legal counsel", "legal clearance",
    "legal approval", "legal compliance", "legally compliant",
    "legal department", "legal advisor", "legal advisory",
)

# Negation / absence / pending markers that void an evidence or policy
# keyword when they appear within a few words of the match.
_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks",
    "lacking", "missing", "absent", "absence", "unclear", "uncertain",
    "unknown", "unverified", "unapproved", "unlicensed", "pending",
    "awaiting", "awaited", "outstanding", "void", "expired", "lapsed",
    "revoked", "rejected", "denied", "withdrawn", "incomplete",
    "suspended",
})

# Signal → exposure contribution once detected.
_SIGNAL_EXPOSURE: dict[str, float] = {
    "privacy": 0.35,
    "financial": 0.35,
    "health": 0.40,
    "certification": 0.30,
    "consumer_protection": 0.25,
}

# Small product-type baseline so categories that are inherently regulated
# never read as zero, while staying below the 0.15 override/concern threshold
# until an explicit assumption signal appears.
_EXPOSURE_BASELINE: float = 0.08
_EXPOSURE_CAP: float = 0.95
_OVERRIDE_THRESHOLD: float = 0.15

# Certification barrier floor per product type (approvals/safety marks).
_PRODUCT_CERT_BASE: dict[str, float] = {
    "health_hardware": 0.35,
    "consumer_hardware": 0.25,
    "iot_hardware": 0.25,
    "wearable": 0.25,
    "b2b_hardware": 0.25,
    "smart_home": 0.25,
    "enterprise_software": 0.25,
    "marketplace": 0.20,
    "b2b_marketplace": 0.20,
    "d2c": 0.20,
    "mobile_app": 0.15,
    "consumer_app": 0.15,
    "saas": 0.10,
    "productivity_tool": 0.10,
}

_CONSUMER_PRODUCT_TYPES: frozenset[str] = frozenset({
    "d2c",
    "marketplace",
    "b2b_marketplace",
    "consumer_hardware",
    "mobile_app",
    "consumer_app",
    "smart_home",
    "wearable",
})


def _has_any_keyword(
    assumptions: list[dict[str, Any]],
    keywords: tuple[str, ...],
    *,
    guard_negation: bool = False,
) -> bool:
    """
    True when any assumption text contains any keyword (word-boundary).

    With ``guard_negation``, a match is ignored when negation/absence/pending
    markers appear within a few words around it, so "not yet certified" does
    not count as compliance evidence.
    """
    if not assumptions:
        return False
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )
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


class RegulatoryComplianceArchitect(BaseArchitect):
    """Evaluates regulatory/compliance exposure across consumer clusters."""

    @property
    def name(self) -> str:
        return "RegulatoryComplianceArchitect"

    @property
    def product_types(self) -> list[str]:
        # Empty means active for every product type — privacy, certification
        # and refund/liability expectations exist for software, hardware,
        # marketplaces and B2B alike.
        return []

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        trust = _trait(traits, "trust")
        risk_av = _trait(traits, "risk_aversion")
        literacy = _trait(traits, "digital_literacy")
        income = _trait(traits, "income_level")
        price_sens = _trait(traits, "price_sensitivity")
        product_type = str(env_params.get("product_type", "saas")).lower()

        signals = {
            "privacy": _has_any_keyword(assumptions, _PRIVACY_KEYWORDS),
            "financial": _has_any_keyword(assumptions, _FINANCIAL_KEYWORDS),
            "health": _has_any_keyword(assumptions, _HEALTH_KEYWORDS),
            "certification": _has_any_keyword(
                assumptions, _CERTIFICATION_KEYWORDS
            ),
            "consumer_protection": _has_any_keyword(
                assumptions, _CONSUMER_PROTECTION_KEYWORDS
            ),
        }
        evidence = _has_any_keyword(
            assumptions, _EVIDENCE_KEYWORDS, guard_negation=True
        )
        policy_present = _has_any_keyword(
            assumptions, _CONSUMER_POLICY_KEYWORDS, guard_negation=True
        )

        exposure = _EXPOSURE_BASELINE + sum(
            _SIGNAL_EXPOSURE[name]
            for name, detected in signals.items()
            if detected
        )
        exposure = round(min(_EXPOSURE_CAP, exposure), 4)
        active = exposure > _OVERRIDE_THRESHOLD

        # ── Privacy / health-data concern ─────────────────────────────────
        privacy_signal = signals["privacy"] or signals["health"]
        privacy_blend = (
            0.45 * (1.0 - trust)
            + 0.30 * risk_av
            + 0.15 * literacy
            + 0.10 * income
        )
        privacy_concern = _clamp(
            exposure * (0.25 + 0.75 * float(privacy_signal)) * privacy_blend
        )

        # ── Certification / approval barrier ─────────────────────────────
        cert_barrier = _PRODUCT_CERT_BASE.get(product_type, 0.10)
        if signals["certification"] or signals["health"]:
            cert_barrier += 0.30
        if evidence:
            cert_barrier *= 0.55
        cert_barrier = round(_clamp(cert_barrier), 4)

        # ── Refund / liability concern ───────────────────────────────────
        consumer_type = product_type in _CONSUMER_PRODUCT_TYPES
        consumer_risk_driven = (
            signals["consumer_protection"] or consumer_type
        )
        refund_exposure = exposure if consumer_risk_driven else 0.0
        policy_factor = 0.45 if policy_present else 1.0
        refund_concern = _clamp(
            refund_exposure
            * (0.55 + 0.45 * float(consumer_type))
            * (0.55 + 0.55 * price_sens)
            * (0.65 + 0.55 * (1.0 - income))
            * policy_factor
        )

        # ── Consent friction ─────────────────────────────────────────────
        consent_friction = _clamp(
            exposure
            * (
                0.40 * (1.0 - trust)
                + 0.30 * risk_av
                + 0.30 * literacy
            )
            * (0.30 + 0.70 * float(privacy_signal))
        )

        # ── Funnel suppressor + compliance credibility ───────────────────
        if not active:
            suppressor = 1.0
        else:
            raw_suppression = exposure * (
                0.45 * (1.0 - trust)
                + 0.35 * risk_av
                + 0.20 * literacy
            )
            if evidence:
                raw_suppression *= 0.45
            suppressor = 1.0 - min(0.40, raw_suppression)
        suppressor = round(_clamp(suppressor, 0.55, 1.0), 4)

        credibility = 1.0 if evidence else max(
            0.10, 1.0 - exposure * 0.9
        )
        credibility = round(_clamp(credibility), 4)
        lift = (
            round(min(0.15, exposure * 0.12), 4)
            if evidence and active
            else 0.0
        )

        flags: dict[str, bool] = {
            "privacy_blocker": privacy_concern >= 0.45,
            "certification_gate": (
                cert_barrier >= 0.60 and not evidence
            ),
            "refund_policy_risk": (
                refund_concern >= 0.35
                and not policy_present
            ),
            "compliance_unknown": exposure > 0.40 and not evidence,
            "regulatory_advantage": evidence and exposure > 0.30,
        }

        severity = (
            "CRITICAL"
            if flags["privacy_blocker"] or flags["certification_gate"]
            else "WARNING"
            if flags["refund_policy_risk"] or flags["compliance_unknown"]
            else "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "regulatory_exposure": exposure,
                "privacy_concern_intensity": round(privacy_concern, 4),
                "certification_barrier": cert_barrier,
                "refund_liability_concern": round(refund_concern, 4),
                "consent_friction": round(consent_friction, 4),
                "compliance_credibility": credibility,
                "regulatory_suppressor": suppressor,
                "regulatory_advantage_lift": lift,
            },
            flags=flags,
            narrative_findings=[
                (
                    f"Regulatory exposure: {exposure:.2f} | Privacy: "
                    f"{privacy_concern:.2f} | Cert barrier: {cert_barrier:.2f}"
                ),
                (
                    f"Compliance credibility: {credibility:.2f} | "
                    f"Funnel suppressor: {suppressor:.2f}"
                ),
            ],
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        exposure = float(output.metrics.get("regulatory_exposure", 0.0))
        if exposure <= _OVERRIDE_THRESHOLD:
            return {}
        suppressor = float(output.metrics.get("regulatory_suppressor", 1.0))
        lift = float(output.metrics.get("regulatory_advantage_lift", 0.0))
        return {
            ("BROWSE", "CONSIDER"): _clamp(suppressor, 0.55, 0.999),
            ("CONSIDER", "DECIDE"): _clamp(suppressor + 0.06, 0.60, 0.999),
            ("DECIDE", "PURCHASE"): _clamp(1.0 + lift, 0.55, 1.15),
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        critical = [
            o
            for o in outputs
            if o.flags.get("privacy_blocker")
            or o.flags.get("certification_gate")
        ]
        warning = [
            o
            for o in outputs
            if o.flags.get("refund_policy_risk")
            or o.flags.get("compliance_unknown")
        ]
        affected = list(
            dict.fromkeys(o.cluster_id for o in critical + warning)
        )
        if not critical and not warning:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No regulatory compliance blockers detected across clusters"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Keep documenting compliance evidence as the product scales"
                ),
                severity="INFO",
            )
        return DomainReport(
            architect_name=self.name,
            primary_finding=(
                f"{len(critical)} clusters blocked by privacy/certification "
                f"gates; {len(warning)} exposed to compliance uncertainty"
            ),
            affected_cluster_ids=affected,
            population_fraction=round(len(affected) * 0.05, 3),
            conversion_impact=round(
                len(critical) * 0.05 + len(warning) * 0.02, 3
            ),
            recommended_action=(
                "Map the regulatory path (privacy, certifications, refund "
                "policy) and publish compliance evidence before scaling"
            ),
            severity="CRITICAL" if critical else "WARNING",
        )


__all__ = ["RegulatoryComplianceArchitect"]
