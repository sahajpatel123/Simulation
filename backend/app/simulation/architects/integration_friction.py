"""
IntegrationFrictionArchitect — existing-toolchain compatibility founder insight.

Why it exists
-------------
TheCee models demand, price, trust, onboarding, retention, platform
dependence and execution capability across the 52 clusters, but nothing in
the live funnel accounts for the most common software buying failure after
price: the product does not fit the consumer's existing workflow. A B2B
team that cannot sync with Salesforce, a developer who finds no API/SDK,
or an SMB that would have to re-type data from Excel will stop at the
consideration stage no matter how good the pitch is. This architect models
exactly that.

What this architect does
------------------------
* **Signal extraction** — reads the project description plus scored
  assumption texts and scores five evidence classes:
  - *API/SDK*: API, REST/GraphQL, SDK, webhooks, CLI, API keys/docs.
  - *native integrations*: named tools (Slack, Salesforce, Zapier,
    QuickBooks, ...) and connectors/plugins.
  - *import/export*: CSV import/export, migration tools, backups,
    portability, self-hosting.
  - *SSO/enterprise auth*: SSO, SAML, SCIM, LDAP, Okta, RBAC, audit logs.
  - *workflow compatibility*: works with, syncs with, cross-platform,
    offline mode, calendar/meeting embedding.
  Detection is negation- and intent-aware: "no API" and "does not
  integrate with Slack" are gaps, never evidence, while "No, we already
  have an API" stays evidence and "we plan to add an API" is aspirational,
  not a claim.
* **Friction modelling** — combines per-cluster traits (low digital
  literacy, low patience and high risk aversion raise the cost of manual
  work and lock-in) with product-type expectations (enterprise software,
  developer tools, B2B marketplaces and SaaS expect integration depth) into
  a 0-1 ``integration_friction`` score. The model is deliberately neutral
  when the brief never discusses integration at all.
* **Funnel suppression** — when the pitch admits integration gaps and the
  segment genuinely needs workflow fit, CONSIDER→DECIDE is suppressed
  (the offer stays "nice to look at" but never makes the shortlist). When
  the pitch names concrete API/integration/import/SSO evidence, the same
  transition gets a small workflow-fit lift.
* **Founder insight** — the cross-cluster report names which segments stop
  short on workflow fit and which evidence class (API/SDK, native
  integrations, import/export, SSO, workflow compatibility) is missing
  from the pitch.

Pure compute — no I/O, no DB, no LLM, no randomness.
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

# ── Model constants ─────────────────────────────────────────────────────

_ACTIVE_FRICTION_THRESHOLD: float = 0.35
_CRITICAL_FRICTION_THRESHOLD: float = 0.60
_SUPPRESSOR_FLOOR: float = 0.55
_MAX_SUPPRESSION: float = 0.30
_STRONG_EVIDENCE_THRESHOLD: float = 0.60
_EVIDENCE_LIFT: float = 0.06

_SUPPORTED_PRODUCT_TYPES: frozenset[str] = frozenset({
    "saas", "marketplace", "developer_tool", "enterprise_software",
    "b2b_marketplace", "productivity_tool", "mobile_app", "consumer_app",
})

_HIGH_EXPECTATION_TYPES: frozenset[str] = frozenset({
    "saas", "developer_tool", "enterprise_software",
    "b2b_marketplace", "productivity_tool",
})

_EVIDENCE_CLASS_NAMES: tuple[str, ...] = (
    "API/SDK",
    "native integrations",
    "import/export",
    "SSO/enterprise auth",
    "workflow compatibility",
)

_EVIDENCE_SCORES: dict[int, float] = {
    0: 0.0,
    1: 0.3,
    2: 0.6,
    3: 0.9,
    4: 1.0,
    5: 1.0,
}


# ── Evidence vocabulary (word-boundary, case-insensitive) ───────────────

_API_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "rest api", "graphql", "software development kit", "developer api",
    "public api", "open api", "api access", "api documentation",
    "api docs", "developer portal", "api keys", "api key",
    "python sdk", "javascript sdk", "typescript sdk", "mobile sdk",
    "webhook", "webhooks", "command line", "cli",
    "api", "sdk",
)

_INTEGRATION_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "integration with", "integrates with", "integrated with",
    "native integration", "native integrations", "integrations",
    "connector", "connectors", "plug-in", "plugins", "plug-ins",
    "zapier", "make automation", "n8n", "salesforce", "hubspot",
    "slack", "gmail", "outlook", "google workspace", "microsoft 365",
    "microsoft teams", "google sheets", "excel", "quickbooks", "xero",
    "shopify", "notion", "linear", "jira", "asana", "trello",
    "calendly", "stripe", "github", "gitlab", "postgres", "mysql",
    "snowflake", "bigquery", "datadog", "zendesk", "intercom",
    "whatsapp", "telegram", "discord", "figma",
    "chrome extension", "browser extension",
)

_IMPORT_EXPORT_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "import from", "import your", "import existing", "one-click import",
    "one click import", "csv import", "bulk import", "data import",
    "import wizard", "migrate from", "migration tool", "migration tools",
    "data migration", "export to", "export your", "csv export",
    "data export", "bulk export", "export options", "backup and restore",
    "data portability", "portable", "exportable", "bring your own data",
    "self-host", "self hosted", "on-premise", "on prem",
    "open source", "data ownership",
)

_SSO_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "single sign-on", "single sign on", "active directory", "azure ad",
    "role-based access", "role based access", "audit log", "audit logs",
    "team permissions", "admin console", "workspace admin",
    "enterprise controls", "user provisioning", "just-in-time provisioning",
    "jit provisioning",
    "sso", "okta", "scim", "ldap", "saml", "oauth", "rbac",
)

_WORKFLOW_EVIDENCE_KEYWORDS: tuple[str, ...] = (
    "works with", "works alongside", "works in", "compatible with",
    "runs on", "available on", "ios and android", "android and ios",
    "cross-platform", "offline mode", "offline-first", "offline first",
    "mobile and web", "web and mobile", "syncs with", "sync with",
    "syncs to", "syncs your", "fits into", "fits in", "slot into",
    "lives in", "native app", "home screen widget", "widget",
    "calendar", "meeting", "meetings",
)

_EVIDENCE_GROUPS: tuple[tuple[str, ...], ...] = (
    _API_EVIDENCE_KEYWORDS,
    _INTEGRATION_EVIDENCE_KEYWORDS,
    _IMPORT_EXPORT_EVIDENCE_KEYWORDS,
    _SSO_EVIDENCE_KEYWORDS,
    _WORKFLOW_EVIDENCE_KEYWORDS,
)


# ── Gap vocabulary (self-negating phrases are the signal itself) ────────

_INTEGRATION_GAP_KEYWORDS: tuple[str, ...] = (
    # Manual work
    "manual data entry", "manually enter", "manually entering",
    "copy and paste", "copy paste", "copy-paste", "type it in",
    "manual import", "manually import", "manual sync", "manually sync",
    "manual setup", "setup by hand", "retype", "key in",
    "no import", "no data import", "cannot import", "can't import",
    "no migration", "no data migration", "no csv",
    # Closed system
    "no api", "no sdk", "no webhook", "no webhooks",
    "no api access", "no api documentation", "no developer portal",
    "no integration", "no integrations", "no connectors", "no connector",
    "no plugins", "no plugin", "no extension", "no extensions",
    "does not integrate", "doesn't integrate", "do not integrate",
    "don't integrate", "cannot integrate", "can't integrate",
    "not integrated with", "not integrated",
    "closed system", "fully closed", "standalone",
    "no export", "no data export", "cannot export", "can't export",
    "no export function", "data locked in", "data locked",
    "no sso", "no single sign-on", "no saml", "no scim", "no ldap",
    "no active directory", "no oauth",
    "does not connect", "doesn't connect", "do not connect",
    "cannot connect", "can't connect", "not connected", "no connection",
    "not linked", "no linking", "no sync", "doesn't sync", "does not sync",
    "no data portability", "no way to integrate", "no way to import",
    "no way to export", "no way to sync",
)

# "No API key required" is a convenience claim, not an integration gap.
_GAP_EXCLUSION_PATTERN = re.compile(
    r"\bno\s+api\s+keys?\b|\bno\s+api\s+keys?\s+required\b",
    re.IGNORECASE,
)

# Generic negated integration actions ("we are not connected to your CRM",
# "the tool never syncs") that are not enumerated as explicit phrases.
_NEGATED_INTEGRATION_ACTION_RE = re.compile(
    r"\b(?:is|are|was|were|does|do|did|will|would|can|could|should|"
    r"must|has|have|had)\s+"
    r"(?:not|never|no longer)\s+"
    r"(?:integrat(?:e|es|ed|ing)|connect(?:s|ed|ing)?|"
    r"sync(?:s|ed|ing)?|link(?:s|ed|ing)?|"
    r"import(?:s|ed|ing)?|export(?:s|ed|ing)?|"
    r"work with|works with|compatible)\b",
    re.IGNORECASE,
)


# ── Text helpers (shared with the other negation-aware architects) ──────

_NEGATION_MARKERS: frozenset[str] = frozenset({
    "no", "not", "never", "non", "without", "lack", "lacks",
    "lacking", "missing", "absent", "absence", "unclear", "uncertain",
    "unknown", "unverified", "unconfirmed", "pending", "awaiting",
    "void", "none", "nothing", "neither", "nor",
})

_INTENT_MARKERS: frozenset[str] = frozenset({
    "plan", "planned", "planning", "roadmap", "future", "eventually",
    "todo", "need", "needs", "needed", "require", "requires", "required",
    "must", "should", "will", "would", "intend", "intends", "intended",
    "add", "adding", "build", "building", "aim", "aims", "hoping",
    "hope", "hopes", "want", "wants", "wanted", "scheduled", "upcoming",
    "due", "set", "setting", "setup", "getting", "get", "obtain",
    "obtaining", "pursue", "pursuing", "working on", "in progress",
    "to be", "seek", "seeks", "seeking", "look for", "looking for",
})

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
    r"[.,;:!?—–\-\n]|\b(?:but|yet|though|although|whereas|however|while)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=32)
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
        lambda m: _CONTRACTION_SUFFIXES[m.group(1)], lowered
    )


def _collect_texts(
    assumptions: list[dict[str, Any]] | None,
    env_params: dict[str, Any] | None,
) -> list[str]:
    """Gather pitch texts: scored assumptions plus project description.

    Null or blank entries are not evidence, and identical texts are
    de-duplicated so the same claim repeated in an assumption and the
    description is not counted multiple times.
    """
    texts: list[str] = []
    for assumption in assumptions or []:
        if isinstance(assumption, dict):
            raw = assumption.get("text", assumption.get("assumption", ""))
        else:
            raw = assumption
        if raw is None:
            continue
        raw = str(raw)
        if not raw.strip():
            continue
        texts.append(_normalise(raw))
    description = (env_params or {}).get("description", "")
    if description is not None:
        description = str(description).strip()
        if description:
            texts.append(_normalise(description))
    return list(dict.fromkeys(texts))


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


def _is_discourse_negation(tokens: list[str]) -> bool:
    """True for "not only"/"not just" focus constructions."""
    focus = {"only", "just", "merely", "simply"}
    return any(
        tokens[i] == "not"
        and i + 1 < len(tokens)
        and tokens[i + 1] in focus
        for i in range(len(tokens) - 1)
    )


def _match_is_voided(
    text: str,
    start: int,
    end: int,
    *,
    include_intent: bool = True,
) -> bool:
    """True when negation/intent markers qualify a match in the same clause."""
    clause_matches_before = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    clause_start = clause_matches_before[-1].end() if clause_matches_before else 0
    before = re.findall(r"[a-z]+", text[clause_start:start])[-8:]

    clause_matches_after = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, end, len(text)))
    clause_end = clause_matches_after[0].start() if clause_matches_after else len(text)
    after = re.findall(r"[a-z]+", text[end:clause_end])[:8]

    # A keyword inside an interrogative clause is a question, not evidence.
    if clause_end < len(text) and text[clause_end] == "?":
        return True

    if after and after[0] in {"and", "or", "then", "also", "plus", "too"}:
        after = []
    before_text = " ".join(before)
    combined = before + after

    if any(
        phrase in before_text
        for phrase in ("working on", "in progress", "to be")
    ):
        return True
    if _is_discourse_negation(combined):
        negation_voided = False
    else:
        negation_voided = bool(set(combined) & _NEGATION_MARKERS)
    # Intent markers only void evidence when they precede the keyword.
    return negation_voided or (include_intent and bool(set(before) & _INTENT_MARKERS))


def _evidence_covered(
    texts: list[str],
    keywords: tuple[str, ...],
) -> bool:
    """True when at least one keyword match survives negation/intent checks."""
    pattern = _keyword_pattern(keywords)
    for text in texts:
        for match in pattern.finditer(text):
            if not _match_is_voided(text, match.start(), match.end()):
                return True
    return False


def _spans_overlap(
    a: tuple[int, int],
    b: tuple[int, int],
) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _count_gap_matches(texts: list[str]) -> int:
    """Count explicit integration-gap phrases plus negated integration actions.

    Explicit phrases ("no API", "does not integrate") and the generic
    negated-action pattern are de-duplicated so the same span never counts
    twice. "No API key required" is excluded as a convenience claim.
    """
    total = 0
    for text in texts:
        explicit_spans: list[tuple[int, int]] = []
        exclusion_spans = [
            (m.start(), m.end())
            for m in _GAP_EXCLUSION_PATTERN.finditer(text)
        ]
        pattern = _keyword_pattern(_INTEGRATION_GAP_KEYWORDS)
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            if any(_spans_overlap(span, e) for e in exclusion_spans):
                continue
            total += 1
            explicit_spans.append(span)
        for match in _NEGATED_INTEGRATION_ACTION_RE.finditer(text):
            span = (match.start(), match.end())
            if any(_spans_overlap(span, s) for s in explicit_spans):
                continue
            if any(_spans_overlap(span, e) for e in exclusion_spans):
                continue
            total += 1
            explicit_spans.append(span)
    return total


class IntegrationFrictionArchitect(BaseArchitect):
    """Models how existing-workflow/toolchain compatibility shapes adoption."""

    @property
    def name(self) -> str:
        return "IntegrationFrictionArchitect"

    @property
    def product_types(self) -> list[str]:
        # Software categories where consumers buy into an existing workflow.
        # Hardware ecosystem fit is already covered by
        # EcosystemCompatibilityArchitect.
        return sorted(_SUPPORTED_PRODUCT_TYPES)

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        traits = {**cluster.base_traits, **agent_profile}
        literacy = _trait(traits, "digital_literacy")
        patience = _trait(traits, "patience_score")
        risk_aversion = _trait(traits, "risk_aversion")

        product_type = str(env_params.get("product_type", "saas"))
        texts = _collect_texts(assumptions, env_params)

        # ── Evidence extraction ──────────────────────────────────────────
        covered_names: list[str] = []
        covered_flags: dict[str, bool] = {}
        for name, keywords in zip(_EVIDENCE_CLASS_NAMES, _EVIDENCE_GROUPS):
            present = _evidence_covered(texts, keywords)
            covered_flags[name] = present
            if present:
                covered_names.append(name)
        evidence_score = float(_EVIDENCE_SCORES.get(len(covered_names), 0.0))

        gap_count = _count_gap_matches(texts)
        gap_score = (
            _clamp(0.12 + 0.18 * min(gap_count, 5), low=0.0, high=1.0)
            if gap_count > 0
            else 0.0
        )
        topic_discussed = len(covered_names) > 0 or gap_count > 0

        # ── Trait- and category-driven necessity ─────────────────────────
        necessity = 0.30
        if product_type in _HIGH_EXPECTATION_TYPES:
            necessity += 0.25
        necessity += 0.20 * (1.0 - literacy)
        necessity += 0.15 * (1.0 - patience)
        necessity += 0.15 * risk_aversion
        necessity = _clamp(necessity, low=0.0, high=0.95)

        # ── Workflow fit and friction ────────────────────────────────────
        if not topic_discussed:
            # The pitch never mentions toolchain compatibility: report
            # healthy neutral values so accountability stays quiet, and
            # keep the funnel unchanged (mirrors the other architects'
            # "not discussed" rule).
            evidence_score = 1.0
            gap_score = 0.0
            workflow_fit = 1.0
            friction = 0.0
        else:
            workflow_fit = _clamp(
                0.35
                + 0.50 * evidence_score
                + 0.10 * literacy
                - 0.30 * gap_score,
                low=0.05,
                high=0.95,
            )
            friction = _clamp(
                necessity * (1.0 - workflow_fit),
                low=0.0,
                high=1.0,
            )

        suppressor = 1.0
        friction_active = topic_discussed and friction >= _ACTIVE_FRICTION_THRESHOLD
        if friction_active:
            suppression = _MAX_SUPPRESSION * min(
                1.0,
                (friction - _ACTIVE_FRICTION_THRESHOLD)
                / (_CRITICAL_FRICTION_THRESHOLD - _ACTIVE_FRICTION_THRESHOLD),
            )
            suppressor = round(
                _clamp(1.0 - suppression, low=_SUPPRESSOR_FLOOR, high=1.0),
                4,
            )

        evidence_strong = (
            topic_discussed and evidence_score >= _STRONG_EVIDENCE_THRESHOLD
        )
        fit_lift = (
            round(_EVIDENCE_LIFT * evidence_score, 4)
            if evidence_strong and not friction_active
            else 0.0
        )

        # ── Flags & severity ─────────────────────────────────────────────
        flags: dict[str, bool] = {
            "integration_topic_discussed": topic_discussed,
            "integration_evidence_strong": evidence_strong,
            "integration_gap_detected": gap_count > 0,
            "integration_friction_active": friction_active,
            "integration_fit_lift_active": fit_lift > 0.0,
            "api_evidence_present": covered_flags["API/SDK"],
            "native_integration_evidence_present": covered_flags["native integrations"],
            "import_export_evidence_present": covered_flags["import/export"],
            "sso_evidence_present": covered_flags["SSO/enterprise auth"],
            "workflow_compat_evidence_present": covered_flags["workflow compatibility"],
        }
        missing_classes = [
            name for name in _EVIDENCE_CLASS_NAMES if not covered_flags[name]
        ]
        severity = (
            "CRITICAL"
            if friction >= _CRITICAL_FRICTION_THRESHOLD
            else "WARNING"
            if friction_active
            else "INFO"
        )

        if not topic_discussed:
            narrative = [
                (
                    "Integration friction neutral: pitch does not discuss "
                    "toolchain compatibility"
                ),
                (
                    f"Integration necessity: {necessity:.2f} | "
                    f"Workflow fit: {workflow_fit:.2f} | Friction: 0.00"
                ),
                "No integration evidence demanded; funnel unchanged",
            ]
        else:
            narrative = [
                (
                    f"Integration evidence classes: {len(covered_names)}/5 "
                    f"| Gap signals: {gap_count} | Workflow fit: {workflow_fit:.2f}"
                ),
                (
                    f"Integration necessity: {necessity:.2f} | "
                    f"Friction: {friction:.2f} | Funnel suppressor: {suppressor:.2f}"
                ),
                (
                    f"Missing evidence: {', '.join(missing_classes) or 'none'}"
                ),
            ]

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "integration_evidence_score": round(evidence_score, 4),
                "integration_gap_score": round(gap_score, 4),
                "integration_necessity": round(necessity, 4),
                "workflow_fit_score": round(workflow_fit, 4),
                "integration_friction": round(friction, 4),
                "integration_funnel_suppressor": suppressor,
            },
            flags=flags,
            narrative_findings=narrative,
            severity=severity,
        )

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        if not output.flags.get("integration_topic_discussed", False):
            return {}
        if output.flags.get("integration_friction_active", False):
            return {
                ("CONSIDER", "DECIDE"): float(
                    output.metrics.get("integration_funnel_suppressor", 1.0)
                ),
            }
        if output.flags.get("integration_fit_lift_active", False):
            evidence = float(output.metrics.get("integration_evidence_score", 0.0))
            return {
                ("CONSIDER", "DECIDE"): round(1.0 + _EVIDENCE_LIFT * evidence, 4),
            }
        return {}

    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        if not outputs:
            return DomainReport(
                architect_name=self.name,
                primary_finding=(
                    "No integration-friction outputs to aggregate"
                ),
                affected_cluster_ids=[],
                population_fraction=0.0,
                conversion_impact=0.0,
                recommended_action=(
                    "Re-run simulation with at least one cluster"
                ),
                severity="INFO",
            )

        from app.simulation.clusters.registry import ClusterRegistry

        registry = ClusterRegistry()
        total_weight = (
            sum(c.population_weight for c in registry.all_clusters()) or 1.0
        )

        affected = [
            o for o in outputs
            if o.flags.get("integration_friction_active", False)
        ]
        critical = [
            o for o in outputs
            if o.severity == "CRITICAL"
        ]

        affected_ids = list(dict.fromkeys(
            o.cluster_id for o in affected if o.cluster_id
        ))
        affected_weight = 0.0
        fallback_weight = 1.0 / max(1, len(registry.all_clusters()))
        for cid in affected_ids:
            try:
                cluster = registry.get_cluster(cid)
            except KeyError:
                cluster = None
            if cluster:
                affected_weight += cluster.population_weight
            else:
                affected_weight += fallback_weight
        population_fraction = round(affected_weight / total_weight, 4)

        # ── Dominant missing evidence class across affected clusters ─────
        class_counts: dict[str, int] = {name: 0 for name in _EVIDENCE_CLASS_NAMES}
        for output in affected:
            for name in _EVIDENCE_CLASS_NAMES:
                if not output.flags.get(
                    {
                        "API/SDK": "api_evidence_present",
                        "native integrations": "native_integration_evidence_present",
                        "import/export": "import_export_evidence_present",
                        "SSO/enterprise auth": "sso_evidence_present",
                        "workflow compatibility": "workflow_compat_evidence_present",
                    }[name],
                    False,
                ):
                    class_counts[name] += 1
        missing_ranked = sorted(
            _EVIDENCE_CLASS_NAMES,
            key=lambda name: (-class_counts[name], _EVIDENCE_CLASS_NAMES.index(name)),
        )
        top_missing = missing_ranked[0] if affected else None

        if affected:
            primary = (
                f"{len(affected)} clusters face integration friction; "
                f"top missing evidence class: {top_missing}"
            )
            recommended_action = {
                "API/SDK": (
                    "Publish API/SDK/webhook evidence: docs, keys, rate "
                    "limits and a developer portal"
                ),
                "native integrations": (
                    "Name the tools you already integrate with (Slack, "
                    "Salesforce, Zapier, QuickBooks, ...) in the pitch"
                ),
                "import/export": (
                    "Add CSV import/export, migration tools and data "
                    "portability proof to the pitch"
                ),
                "SSO/enterprise auth": (
                    "Add SSO (SAML/SCIM/Okta), RBAC and audit-log evidence "
                    "for workplace buyers"
                ),
                "workflow compatibility": (
                    "Show how the product slots into the existing workflow: "
                    "sync, cross-platform, offline, calendar/meeting fit"
                ),
            }[top_missing or "API/SDK"]
        else:
            primary = (
                "No cluster shows active integration friction; "
                "existing-toolchain messaging is adequate"
            )
            recommended_action = (
                "No dominant integration blocker detected; keep current "
                "workflow-compatibility messaging"
            )

        return DomainReport(
            architect_name=self.name,
            primary_finding=primary,
            affected_cluster_ids=affected_ids,
            population_fraction=population_fraction,
            conversion_impact=round(
                len(affected) * 0.04 + len(critical) * 0.02,
                4,
            ),
            recommended_action=recommended_action,
            severity=(
                "CRITICAL"
                if len(critical) >= 3
                else "WARNING"
                if affected
                else "INFO"
            ),
        )


__all__ = ["IntegrationFrictionArchitect"]
