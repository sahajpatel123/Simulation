"""
PerformanceThresholdArchitect — speed, battery, accuracy, and latency hard limits.

Includes CONSIDER→DECIDE transition override.
No LLM, no DB, no randomness.
"""
from __future__ import annotations

import re

from app.simulation.architects.base import ArchitectOutput, BaseArchitect, DomainReport
from app.simulation.clusters.definitions import ClusterDefinition


class PerformanceThresholdArchitect(BaseArchitect):

    @property
    def name(self) -> str:
        return "PerformanceThresholdArchitect"

    @property
    def product_types(self) -> list[str]:
        return [
            "consumer_hardware", "health_hardware",
            "iot_hardware", "wearable", "b2b_hardware",
        ]

    def compute(
        self,
        cluster: ClusterDefinition,
        agent_profile: dict,
        assumptions: list[dict],
        env_params: dict,
    ) -> ArchitectOutput:
        t            = cluster.base_traits
        literacy     = t["digital_literacy"]
        patience     = t["patience_score"]
        income       = t["income_level"]
        risk_av      = t["risk_aversion"]
        product_type = str(env_params.get("product_type", "consumer_hardware"))
        AOV          = float(env_params.get("average_order_value", 3000))

        # ── Use-case criticality ──────────────────────────────────────────
        criticality = (
            0.95 if product_type == "health_hardware" else
            0.85 if product_type == "b2b_hardware" else
            0.70 if product_type == "wearable" else
            0.50
        )

        # ── Extract specs from assumptions ────────────────────────────────
        stated_battery_h  = 0
        stated_uptime_pct = 99.0
        for a in assumptions:
            text = str(a.get("text", a.get("assumption", ""))).lower()
            battery_match = re.search(r"(\d+)\s*(?:hour|day)", text)
            if battery_match:
                raw = int(battery_match.group(1))
                # convert days → hours if "day" was the unit
                if "day" in text[battery_match.start():battery_match.end() + 3]:
                    stated_battery_h = raw * 24
                else:
                    stated_battery_h = raw
            uptime_match = re.search(r"(\d+\.?\d*)\s*%\s*uptime", text)
            if uptime_match:
                stated_uptime_pct = float(uptime_match.group(1))

        # ── Minimum speed threshold ───────────────────────────────────────
        speed_thresh = max(0.10, criticality * (1.5 - literacy * 0.5))

        # ── Battery collapse hours ────────────────────────────────────────
        battery_collapse_h = (
            18 if product_type == "wearable" else
            8  if product_type in ["b2b_hardware", "health_hardware"] else
            4
        )
        battery_ok = (stated_battery_h >= battery_collapse_h) if stated_battery_h > 0 else None

        # ── Connectivity dropout tolerance ────────────────────────────────
        conn_tolerance = max(0.01, (1 - criticality) * 0.10 * (patience * 1.2))

        # ── Accuracy tolerance ────────────────────────────────────────────
        accuracy_tolerance = (
            0.02 if product_type == "health_hardware"
                 and any(x in cluster.cluster_id for x in ["chronic", "health_skeptic"]) else
            0.05 if product_type == "health_hardware" else
            0.15 if product_type == "wearable" else
            0.25
        )

        # ── Other performance metrics ─────────────────────────────────────
        sophistication  = literacy * 0.6 + (1 - risk_av) * 0.4
        processing_pref = min(0.90, income * 0.6 + sophistication * 0.4)

        storage_min_gb = (
            128 if "media" in str(env_params) else
            64  if product_type in ["wearable", "b2b_hardware"] else
            32
        )

        benchmark_reading = min(0.95,
            literacy * 0.5 * (2.5 if "enthusiast" in cluster.cluster_id else 0.6)
        )

        latency = (
            "real_time" if criticality > 0.8 else
            "moderate"  if criticality > 0.5 else
            "relaxed"
        )

        heat_noise_tol = (
            0.7 if product_type == "iot_hardware" else
            0.3 if product_type == "wearable" else
            0.5
        )

        degrad_tolerance = min(0.80,
            patience * 0.4 * (
                0.6 if AOV > 8000 else
                1.3 if income < 0.3 else
                1.0
            )
        )

        battery_kill = battery_ok is False

        severity = (
            "CRITICAL" if battery_kill else
            "WARNING"  if accuracy_tolerance < 0.03 and product_type != "health_hardware" else
            "INFO"
        )

        return ArchitectOutput(
            architect_name=self.name,
            cluster_id=cluster.cluster_id,
            metrics={
                "minimum_speed_threshold":           round(speed_thresh, 4),
                "battery_collapse_hours":            float(battery_collapse_h),
                "battery_stated_hours":              float(stated_battery_h),
                "connectivity_tolerance":            round(conn_tolerance, 4),
                "accuracy_error_tolerance":          round(accuracy_tolerance, 4),
                "processing_vs_cost_preference":     round(processing_pref, 4),
                "storage_minimum_gb":                float(storage_min_gb),
                "benchmark_reading_behaviour":       round(benchmark_reading, 4),
                "latency_score":                     1.0 if latency == "real_time" else 0.5 if latency == "moderate" else 0.1,
                "heat_noise_tolerance":              round(heat_noise_tol, 4),
                "performance_degradation_tolerance": round(degrad_tolerance, 4),
            },
            flags={
                "battery_kill_shot":  battery_kill,
                "accuracy_critical":  accuracy_tolerance < 0.03,
                "benchmark_reader":   benchmark_reading > 0.50,
                "real_time_required": latency == "real_time",
            },
            narrative_findings=[
                f"Battery: need {battery_collapse_h}h, stated {stated_battery_h}h",
                f"Accuracy tolerance: ±{accuracy_tolerance * 100:.1f}% | Latency: {latency}",
            ],
            severity=severity,
        )

    def transition_overrides(self, output: ArchitectOutput) -> dict[tuple[str, str], float]:
        battery_kill   = output.flags.get("battery_kill_shot", False)
        benchmark_read = output.metrics.get("benchmark_reading_behaviour", 0.3)
        spec_gap       = 0.4 if battery_kill else 0.0
        consider_decide = max(0.05, min(0.95, 1.0 - spec_gap - benchmark_read * spec_gap))
        return {
            ("CONSIDER", "DECIDE"): consider_decide,
        }

    def generate_report(self, outputs: list[ArchitectOutput]) -> DomainReport:
        battery_kills = [o for o in outputs if o.flags.get("battery_kill_shot")]
        return DomainReport(
            architect_name=self.name,
            primary_finding=f"{len(battery_kills)} clusters have battery life as kill shot",
            affected_cluster_ids=[o.cluster_id for o in battery_kills],
            population_fraction=round(len(battery_kills) * 0.05, 3),
            conversion_impact=round(len(battery_kills) * 0.06, 3),
            recommended_action="Increase battery life or clarify use case battery requirements",
            severity="CRITICAL" if battery_kills else "INFO",
        )
