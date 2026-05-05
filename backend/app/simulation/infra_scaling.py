from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GROWTH_STAGES = {
    "launch": {"users": 100, "label": "Launch (Day 1)"},
    "early": {"users": 1000, "label": "Early Traction (Month 1)"},
    "growth": {"users": 10000, "label": "Growth (Month 3)"},
    "scale": {"users": 100000, "label": "Scale (Month 12)"},
    "hyper": {"users": 1000000, "label": "Hyper-scale (Year 3)"},
}

SESSION_API_CALL_MAP = {
    "deep_work": 45,
    "quick_check": 8,
}

DB_LOAD_MAP = {
    "saas": {"reads": 120, "writes": 30},
    "marketplace": {"reads": 200, "writes": 50},
    "mobile_app": {"reads": 80, "writes": 20},
    "consumer_hardware": {"reads": 40, "writes": 10},
    "health_hardware": {"reads": 60, "writes": 25},
    "developer_tool": {"reads": 300, "writes": 80},
    "enterprise_software": {"reads": 150, "writes": 40},
    "iot_hardware": {"reads": 500, "writes": 100},
    "wearable": {"reads": 200, "writes": 60},
    "b2b_hardware": {"reads": 80, "writes": 20},
}


@dataclass
class StageProjection:
    stage: str
    label: str
    total_users: int
    active_users: int
    concurrent_peak: int
    api_calls_per_day: int
    db_reads_per_day: int
    db_writes_per_day: int
    storage_gb: float
    estimated_cost_usd: float
    recommended_tier: str
    bottleneck: str


@dataclass
class InfraScalingResult:
    generated_ui_id: int
    product_type: str
    dau_rate: float
    avg_session_depth: str
    avg_api_calls: int
    db_profile: dict
    stages: list[StageProjection]
    critical_stage: str
    scaling_warnings: list[str]


class InfraScalingEngine:

    def _dau_rate(self, cluster_profiles: list[dict]) -> float:
        if not cluster_profiles:
            return 0.25
        weighted = sum(
            p.get("population_weight", 0.02)
            * (0.55 if p.get("session_pattern") == "deep_work" else 0.18)
            for p in cluster_profiles
        )
        return round(min(0.70, max(0.05, weighted)), 4)

    def _dominant_session(self, cluster_profiles: list[dict]) -> str:
        deep = sum(
            p.get("population_weight", 0) for p in cluster_profiles if p.get("session_pattern") == "deep_work"
        )
        quick = sum(
            p.get("population_weight", 0) for p in cluster_profiles if p.get("session_pattern") == "quick_check"
        )
        return "deep_work" if deep >= quick else "quick_check"

    def _monthly_cost(
        self,
        active_users: int,
        concurrent: int,
        api_calls: int,
        db_reads: int,
        db_writes: int,
    ) -> float:
        compute_cost = max(10, concurrent / 100 * 15)
        db_cost = max(10, (db_reads + db_writes * 3) / 100000 * 8)
        storage_cost = active_users * 0.0002
        cdn_cost = api_calls / 1000000 * 0.08
        return round(compute_cost + db_cost + storage_cost + cdn_cost, 2)

    def _tier(self, cost: float) -> str:
        if cost < 50:
            return "starter"
        if cost < 500:
            return "growth"
        if cost < 5000:
            return "business"
        return "enterprise"

    def _bottleneck(self, concurrent: int, db_writes: int, api_calls: int) -> str:
        if db_writes > 1_000_000:
            return "database_write_throughput"
        if concurrent > 10_000:
            return "compute_horizontal_scaling"
        if api_calls > 50_000_000:
            return "api_gateway_rate_limits"
        if concurrent > 1_000:
            return "connection_pool_saturation"
        return "none"

    def generate(
        self,
        generated_ui_id: int,
        product_type: str,
        cluster_profiles: list[dict],
        overall_conversion: float = 0.05,
    ) -> InfraScalingResult:
        _ = overall_conversion  # reserved for future capacity tied to conversion
        db_profile = DB_LOAD_MAP.get(product_type, DB_LOAD_MAP["saas"])
        dau_rate = self._dau_rate(cluster_profiles)
        dom_session = self._dominant_session(cluster_profiles)
        avg_api = SESSION_API_CALL_MAP[dom_session]

        stages_out: list[StageProjection] = []
        warnings: list[str] = []
        critical = "hyper"

        for stage_key, stage_info in GROWTH_STAGES.items():
            total = stage_info["users"]
            active = max(1, int(total * dau_rate))
            concurrent = max(1, int(active * 0.08))

            api_day = active * avg_api
            db_reads = active * db_profile["reads"]
            db_writes = active * db_profile["writes"]
            storage = round(total * 0.005, 2)

            cost = self._monthly_cost(active, concurrent, api_day, db_reads, db_writes)
            tier = self._tier(cost)
            bottle = self._bottleneck(concurrent, db_writes, api_day)

            if bottle != "none" and critical == "hyper":
                critical = stage_key
                warnings.append(f"{stage_info['label']}: {bottle.replace('_', ' ')} becomes bottleneck")

            if concurrent > 1000 and not any("pgBouncer" in w for w in warnings):
                warnings.append(f"{stage_info['label']}: Configure pgBouncer — {concurrent} concurrent sessions")
            if db_writes > 500_000:
                warnings.append(f"{stage_info['label']}: Consider read replicas — {db_writes:,} writes/day")
            if cost > 1000 and tier == "business":
                warnings.append(f"{stage_info['label']}: Evaluate CDN caching to reduce API cost")

            stages_out.append(
                StageProjection(
                    stage=stage_key,
                    label=stage_info["label"],
                    total_users=total,
                    active_users=active,
                    concurrent_peak=concurrent,
                    api_calls_per_day=api_day,
                    db_reads_per_day=db_reads,
                    db_writes_per_day=db_writes,
                    storage_gb=storage,
                    estimated_cost_usd=cost,
                    recommended_tier=tier,
                    bottleneck=bottle,
                )
            )

        return InfraScalingResult(
            generated_ui_id=generated_ui_id,
            product_type=product_type,
            dau_rate=dau_rate,
            avg_session_depth=dom_session,
            avg_api_calls=avg_api,
            db_profile=db_profile,
            stages=stages_out,
            critical_stage=critical,
            scaling_warnings=list(dict.fromkeys(warnings)),
        )

    def to_dict(self, result: InfraScalingResult) -> dict:
        return {
            "generated_ui_id": result.generated_ui_id,
            "product_type": result.product_type,
            "dau_rate": result.dau_rate,
            "avg_session_depth": result.avg_session_depth,
            "avg_api_calls_per_dau": result.avg_api_calls,
            "db_profile": result.db_profile,
            "critical_stage": result.critical_stage,
            "scaling_warnings": result.scaling_warnings,
            "stages": [
                {
                    "stage": s.stage,
                    "label": s.label,
                    "total_users": s.total_users,
                    "active_users": s.active_users,
                    "concurrent_peak": s.concurrent_peak,
                    "api_calls_per_day": s.api_calls_per_day,
                    "db_reads_per_day": s.db_reads_per_day,
                    "db_writes_per_day": s.db_writes_per_day,
                    "storage_gb": s.storage_gb,
                    "estimated_cost_usd": s.estimated_cost_usd,
                    "recommended_tier": s.recommended_tier,
                    "bottleneck": s.bottleneck,
                }
                for s in result.stages
            ],
        }
