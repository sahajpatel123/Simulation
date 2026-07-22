from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class HeatmapPoint:
    thecee_id: str  # data-thecee-id value
    click_count: int
    cluster_breakdown: dict[str, int]  # cluster_id → click count
    conversion_rate: float  # % of clicks that led to conversion
    abandon_rate: float  # % of clicks followed by abandon


@dataclass
class UIHeatmapResult:
    generated_ui_id: int
    total_clicks: int
    unique_elements: int
    heatmap_points: list[HeatmapPoint]
    cluster_heatmaps: dict[str, list[HeatmapPoint]]  # per-cluster view
    top_conversion_element: str
    top_abandon_element: str


class HeatmapEngine:

    def generate(
        self,
        generated_ui_id: int,
        sessions: list[dict[str, Any]],
    ) -> UIHeatmapResult:
        """
        sessions: list of dicts from ui_simulation_sessions rows
        Each session has: events_json, converted, agent_cluster_id
        """
        # element → {total, converted, abandoned, by_cluster}
        element_stats: dict[str, dict] = defaultdict(
            lambda: {
                "total": 0,
                "converted": 0,
                "abandoned": 0,
                "by_cluster": defaultdict(int),
            }
        )

        for session in sessions:
            events = session.get("events_json") or []
            if isinstance(events, str):
                try:
                    events = json.loads(events)
                except Exception:
                    events = []
            cluster = session.get("agent_cluster_id") or "unknown"
            converted = bool(session.get("converted", False))

            for event in events:
                if event.get("action") != "click":
                    continue
                thecee_id = event.get("target", "unknown")
                element_stats[thecee_id]["total"] += 1
                element_stats[thecee_id]["by_cluster"][cluster] += 1
                if converted:
                    element_stats[thecee_id]["converted"] += 1
                else:
                    element_stats[thecee_id]["abandoned"] += 1

        # Build HeatmapPoints
        points = []
        for thecee_id, stats in element_stats.items():
            total = stats["total"] or 1
            points.append(
                HeatmapPoint(
                    thecee_id=thecee_id,
                    click_count=stats["total"],
                    cluster_breakdown=dict(stats["by_cluster"]),
                    conversion_rate=round(stats["converted"] / total, 4),
                    abandon_rate=round(stats["abandoned"] / total, 4),
                )
            )
        points.sort(key=lambda p: -p.click_count)

        # Per-cluster heatmaps
        cluster_heatmaps: dict[str, list[HeatmapPoint]] = defaultdict(list)
        for session in sessions:
            cluster = session.get("agent_cluster_id") or "unknown"
            events = session.get("events_json") or []
            if isinstance(events, str):
                try:
                    events = json.loads(events)
                except Exception:
                    events = []
            converted = bool(session.get("converted", False))
            cluster_clicks: dict[str, dict] = defaultdict(
                lambda: {"total": 0, "converted": 0, "abandoned": 0}
            )
            for event in events:
                if event.get("action") != "click":
                    continue
                tid = event.get("target", "unknown")
                cluster_clicks[tid]["total"] += 1
                if converted:
                    cluster_clicks[tid]["converted"] += 1
                else:
                    cluster_clicks[tid]["abandoned"] += 1
            for tid, s in cluster_clicks.items():
                t = s["total"] or 1
                cluster_heatmaps[cluster].append(
                    HeatmapPoint(
                        thecee_id=tid,
                        click_count=s["total"],
                        cluster_breakdown={cluster: s["total"]},
                        conversion_rate=round(s["converted"] / t, 4),
                        abandon_rate=round(s["abandoned"] / t, 4),
                    )
                )

        if points:
            top_conv = max(points, key=lambda p: p.conversion_rate).thecee_id
            top_aband = max(points, key=lambda p: p.abandon_rate).thecee_id
        else:
            top_conv = "none"
            top_aband = "none"

        return UIHeatmapResult(
            generated_ui_id=generated_ui_id,
            total_clicks=sum(p.click_count for p in points),
            unique_elements=len(points),
            heatmap_points=points,
            cluster_heatmaps=dict(cluster_heatmaps),
            top_conversion_element=top_conv,
            top_abandon_element=top_aband,
        )

    def to_dict(self, result: UIHeatmapResult) -> dict:
        return {
            "generated_ui_id": result.generated_ui_id,
            "total_clicks": result.total_clicks,
            "unique_elements": result.unique_elements,
            "top_conversion_element": result.top_conversion_element,
            "top_abandon_element": result.top_abandon_element,
            "heatmap_points": [
                {
                    "thecee_id": p.thecee_id,
                    "click_count": p.click_count,
                    "cluster_breakdown": p.cluster_breakdown,
                    "conversion_rate": p.conversion_rate,
                    "abandon_rate": p.abandon_rate,
                }
                for p in result.heatmap_points
            ],
            "cluster_heatmaps": {
                cluster: [
                    {
                        "thecee_id": p.thecee_id,
                        "click_count": p.click_count,
                        "conversion_rate": p.conversion_rate,
                        "abandon_rate": p.abandon_rate,
                    }
                    for p in sorted(pts, key=lambda x: -x.click_count)
                ]
                for cluster, pts in result.cluster_heatmaps.items()
            },
        }
