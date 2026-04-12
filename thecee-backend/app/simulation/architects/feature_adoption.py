"""
FeatureAdoptionArchitect — evaluates how deeply a cluster explores product features.

feature_depth_score is the primary output consumed downstream by RetentionArchitect.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


def complexity_from(assumptions: list[dict]) -> float:
    """Infer product complexity from assumption text. Returns 0.0–1.0."""
    for a in assumptions:
        text = str(a.get("text", a.get("assumption", ""))).lower()
        if any(w in text for w in ["complex", "advanced", "many features", "multi-step"]):
            return 0.8
        if any(w in text for w in ["simple", "easy", "minimal", "one feature"]):
            return 0.2
    return 0.5


class FeatureAdoptionArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "FeatureAdoptionArchitect"

    @property
    def product_types(self) -> list[str]:
        return ["saas", "developer_tool", "enterprise_software", "mobile_app"]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t = cluster.base_traits
        literacy   = t["digital_literacy"]
        motivation = t["motivation"]
        patience   = t["patience_score"]
        trust      = t["trust"]

        # ── Derived cluster-level scores ─────────────────────────────────
        curiosity      = literacy * 0.5 + motivation * 0.5
        technical_lit  = literacy * 0.7 + (0.3 if "developer" in cluster.product_affinities else 0.0)
        builder_orient = 0.8 if "developer_tool" in cluster.product_affinities else 0.3
        professional   = (
            1.0 if any(x in cluster.cluster_id for x in
                       ["professional", "founder", "enterprise", "smb"])
            else 0.4
        )
        team_orient    = (
            1.0 if any(x in cluster.cluster_id for x in
                       ["enterprise", "smb", "b2b"])
            else 0.3
        )

        complexity = complexity_from(assumptions)

        # ── Core metrics ─────────────────────────────────────────────────
        core_dau        = min(0.95, motivation * 0.6 + literacy * 0.25 + patience * 0.15)
        power_discovery = min(0.90, curiosity * 0.5 * (1.4 if literacy > 0.6 else 0.5))
        feature_depth   = min(0.95, (
            patience      * 0.35
            + motivation  * 0.30
            + literacy    * 0.25
            + power_discovery * 0.10
        ))
        collab_rate     = min(0.80, team_orient * 0.5 * trust)
        integration     = min(0.70, (
            literacy * 0.4
            + builder_orient * 0.3
            * (0.3 if "tier3" in cluster.cluster_id else 1.0)
        ))
        adv_settings    = min(0.70, literacy * 0.35 * (1.5 if curiosity > 0.6 else 0.5))
        api_rate        = min(0.80, (
            technical_lit * 0.5 * builder_orient
            * (0.0 if literacy < 0.4 else 1.8)
        ))
        abandonment     = max(0.05, (
            (1 - patience) * 0.3
            * (1.5 if complexity > 0.6 else 1.0)
        ))
        export_usage    = min(0.60, professional * 0.4)
        dashboard_cust  = min(0.60, literacy * 0.3 + (0.2 if patience > 0.6 else 0.0))

        severity = (
            "CRITICAL" if feature_depth < 0.20 else
            "WARNING"  if feature_depth < 0.40 else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "core_feature_dau_rate":         round(core_dau, 4),
                "power_feature_discovery_rate":  round(power_discovery, 4),
                "feature_depth_score":           round(feature_depth, 4),
                "collaboration_adoption_rate":   round(collab_rate, 4),
                "integration_adoption_rate":     round(integration, 4),
                "advanced_settings_exploration": round(adv_settings, 4),
                "api_adoption_rate":             round(api_rate, 4),
                "feature_abandonment_rate":      round(abandonment, 4),
                "export_reporting_usage":        round(export_usage, 4),
                "dashboard_customisation_rate":  round(dashboard_cust, 4),
            },
            flags={
                "shallow_adoption_risk":  feature_depth < 0.25,
                "no_api_interest":        api_rate < 0.05,
                "collaboration_blocked":  collab_rate < 0.10,
            },
            narrative_findings=[
                f"Feature depth score: {feature_depth:.2f}",
                f"Power feature discovery: {power_discovery * 100:.1f}% without prompting",
            ],
            severity=severity,
        )

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        shallow = [o for o in outputs if o.flags.get("shallow_adoption_risk")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(shallow)} clusters show shallow feature adoption",
            affected_cluster_ids=[o.cluster_id for o in shallow],
            population_fraction=round(len(shallow) * 0.05, 3),
            conversion_impact=round(len(shallow) * 0.02, 3),
            recommended_action="Add progressive feature discovery, guided tours",
            severity="WARNING" if shallow else "INFO",
        )
