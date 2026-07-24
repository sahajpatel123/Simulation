from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

FUNNEL_STAGES = ["ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE"]


@dataclass
class FunnelStage:
    stage: str
    agents_entered: int
    agents_exited: int  # dropped at this stage
    exit_rate: float  # % who dropped here
    cluster_exit_rates: dict[str, float]  # cluster_id → exit rate at this stage


@dataclass
class FunnelAnalyticsResult:
    generated_ui_id: int
    total_agents: int
    overall_conversion: float
    stages: list[FunnelStage]
    cluster_funnels: dict[str, dict]  # cluster_id → per-stage breakdown
    highest_drop_stage: str  # where most agents exit
    best_cluster: str  # cluster with highest conversion
    worst_cluster: str  # cluster with lowest conversion


class FunnelAnalyticsEngine:

    def _infer_stage(self, events: list[dict], converted: bool) -> str:
        """
        Infer the deepest funnel stage an agent reached
        from their click events and conversion outcome.
        """
        if converted:
            return "PURCHASE"

        thecee_ids = [e.get("target", "") for e in events if e.get("action") == "click"]

        if any(x in thecee_ids for x in ["checkout-form", "nav-checkout"]):
            return "DECIDE"
        if any(x in thecee_ids for x in ["add-to-cart", "pricing-section"]):
            return "CONSIDER"
        if any(x in thecee_ids for x in ["cta-primary", "nav-products", "nav-home"]):
            return "BROWSE"
        if any(e.get("action") == "abandon" and e.get("target") == "ARRIVE" for e in events):
            return "ARRIVE"
        return "BROWSE"  # default — reached page but bounced

    def generate(
        self,
        generated_ui_id: int,
        sessions: list[dict[str, Any]],
    ) -> FunnelAnalyticsResult:

        total = len(sessions)
        if total == 0:
            return FunnelAnalyticsResult(
                generated_ui_id=generated_ui_id,
                total_agents=0,
                overall_conversion=0.0,
                stages=[],
                cluster_funnels={},
                highest_drop_stage="ARRIVE",
                best_cluster="none",
                worst_cluster="none",
            )

        # ── Build per-agent stage reached ──
        agent_stages: list[tuple[str, str]] = []  # (cluster_id, stage_reached)

        for s in sessions:
            events = s.get("events_json") or []
            if isinstance(events, str):
                try:
                    events = json.loads(events)
                except Exception:
                    events = []
            converted = bool(s.get("converted", False))
            cluster = s.get("agent_cluster_id") or "unknown"
            stage = self._infer_stage(events, converted)
            agent_stages.append((cluster, stage))

        # ── Overall funnel ──
        stage_index = {s: i for i, s in enumerate(FUNNEL_STAGES)}

        def agents_reaching(stage: str) -> int:
            idx = stage_index[stage]
            return sum(1 for _, st in agent_stages if stage_index.get(st, 0) >= idx)

        stages_out = []
        for i, stage in enumerate(FUNNEL_STAGES):
            entered = agents_reaching(stage)
            if i + 1 < len(FUNNEL_STAGES):
                next_entered = agents_reaching(FUNNEL_STAGES[i + 1])
                exited = entered - next_entered
            else:
                # PURCHASE stage: exited = those who did NOT convert
                exited = entered - sum(1 for _, st in agent_stages if st == "PURCHASE")
            exit_rate = round(exited / max(entered, 1), 4)

            # Per-cluster exit rates at this stage
            cluster_exit_rates: dict[str, float] = {}
            by_cluster = defaultdict(list)
            for cid, st in agent_stages:
                by_cluster[cid].append(st)
            for cid, cluster_agent_stages in by_cluster.items():
                c_entered = sum(1 for st in cluster_agent_stages if stage_index.get(st, 0) >= i)
                if i + 1 < len(FUNNEL_STAGES):
                    c_next = sum(1 for st in cluster_agent_stages if stage_index.get(st, 0) >= i + 1)
                    c_exit = c_entered - c_next
                else:
                    c_exit = c_entered - sum(1 for st in cluster_agent_stages if st == "PURCHASE")
                cluster_exit_rates[cid] = round(c_exit / max(c_entered, 1), 4)

            stages_out.append(
                FunnelStage(
                    stage=stage,
                    agents_entered=entered,
                    agents_exited=exited,
                    exit_rate=exit_rate,
                    cluster_exit_rates=cluster_exit_rates,
                )
            )

        # ── Per-cluster funnel summary ──
        cluster_funnels: dict[str, dict] = {}
        by_cluster = defaultdict(list)
        for cid, st in agent_stages:
            by_cluster[cid].append(st)

        for cid, cstages in by_cluster.items():
            n = len(cstages)
            converted_count = sum(1 for st in cstages if st == "PURCHASE")
            per_stage = {}
            for stname in FUNNEL_STAGES:
                idx = stage_index[stname]
                reached = sum(1 for st in cstages if stage_index.get(st, 0) >= idx)
                per_stage[stname] = {
                    "agents_reached": reached,
                    "reach_rate": round(reached / max(n, 1), 4),
                }
            cluster_funnels[cid] = {
                "total_agents": n,
                "converted": converted_count,
                "conversion_rate": round(converted_count / max(n, 1), 4),
                "stages": per_stage,
            }

        # ── Summary metrics ──
        overall_conv = round(sum(1 for _, st in agent_stages if st == "PURCHASE") / max(total, 1), 4)
        highest_drop = max(stages_out, key=lambda s: s.agents_exited).stage
        best_cluster = (
            max(cluster_funnels, key=lambda c: cluster_funnels[c]["conversion_rate"])
            if cluster_funnels
            else "none"
        )
        worst_cluster = (
            min(cluster_funnels, key=lambda c: cluster_funnels[c]["conversion_rate"])
            if cluster_funnels
            else "none"
        )

        return FunnelAnalyticsResult(
            generated_ui_id=generated_ui_id,
            total_agents=total,
            overall_conversion=overall_conv,
            stages=stages_out,
            cluster_funnels=cluster_funnels,
            highest_drop_stage=highest_drop,
            best_cluster=best_cluster,
            worst_cluster=worst_cluster,
        )

    def to_dict(self, result: FunnelAnalyticsResult) -> dict:
        return {
            "generated_ui_id": result.generated_ui_id,
            "total_agents": result.total_agents,
            "overall_conversion": result.overall_conversion,
            "highest_drop_stage": result.highest_drop_stage,
            "best_cluster": result.best_cluster,
            "worst_cluster": result.worst_cluster,
            "stages": [
                {
                    "stage": s.stage,
                    "agents_entered": s.agents_entered,
                    "agents_exited": s.agents_exited,
                    "exit_rate": s.exit_rate,
                    "cluster_exit_rates": s.cluster_exit_rates,
                }
                for s in result.stages
            ],
            "cluster_funnels": result.cluster_funnels,
        }
