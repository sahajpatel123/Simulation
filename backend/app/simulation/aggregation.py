from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats

from app.simulation.funnel import FunnelResult
from app.simulation.markov import STATES, State

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfidenceInterval:
    low: float
    high: float
    level: float


@dataclass(frozen=True)
class StageAggregation:
    state: str
    mean_entry_rate: float
    mean_drop_off_rate: float
    mean_time_seconds: float
    std_entry_rate: float


@dataclass(frozen=True)
class PriceCurvePoint:
    price: float
    conversion_rate: float
    revenue_per_1000_visitors: float
    is_optimal: bool


@dataclass(frozen=True)
class DemographicSegment:
    name: str
    conversion_rate: float
    count_fraction: float
    revenue_index: float


@dataclass(frozen=True)
class Insight:
    severity: str
    category: str
    text: str


@dataclass
class AggregatedResult:
    mean_conversion_rate: float
    std_dev: float
    ci_90: ConfidenceInterval
    ci_95: ConfidenceInterval
    total_agents: int
    total_runs: int
    mean_revenue: float
    revenue_ci_90: ConfidenceInterval
    stage_aggregations: list[StageAggregation]
    worst_drop_off_stage: str
    price_curve: list[PriceCurvePoint]
    optimal_price: float
    optimal_conversion: float
    demographic_segments: list[DemographicSegment]
    insights: list[Insight]
    confidence_score: int
    all_conversion_rates: list[float] = field(default_factory=list)


class ResultsAggregator:
    def _ci(
        self,
        values: list[float],
        level: float,
    ) -> ConfidenceInterval:
        n = len(values)
        if n < 2:
            v = float(values[0]) if values else 0.0
            return ConfidenceInterval(low=round(v, 4), high=round(v, 4), level=level)

        arr = np.array(values, dtype=np.float64)
        mean = arr.mean()
        sem = stats.sem(arr)
        lo, hi = stats.t.interval(level, df=n - 1, loc=mean, scale=sem)

        return ConfidenceInterval(
            low=round(float(np.clip(lo, 0.0, 1.0)), 4),
            high=round(float(np.clip(hi, 0.0, 1.0)), 4),
            level=level,
        )

    def _revenue_ci(
        self,
        values: list[float],
        level: float,
    ) -> ConfidenceInterval:
        n = len(values)
        if n < 2:
            v = float(values[0]) if values else 0.0
            return ConfidenceInterval(low=round(v, 2), high=round(v, 2), level=level)

        arr = np.array(values, dtype=np.float64)
        mean = arr.mean()
        sem = stats.sem(arr)
        lo, hi = stats.t.interval(level, df=n - 1, loc=mean, scale=sem)

        return ConfidenceInterval(
            low=round(float(max(0.0, lo)), 2),
            high=round(float(hi), 2),
            level=level,
        )

    def _aggregate_stages(
        self,
        results: list[FunnelResult],
    ) -> tuple[list[StageAggregation], str]:
        aggregations: list[StageAggregation] = []
        worst_stage = "DECIDE"
        worst_dropoff = 0.0

        for state in STATES:
            stage = state.value
            if stage in (State.PURCHASE.value, State.RETURN.value):
                continue

            entry_rates = [
                next((sm.entry_rate for sm in r.stage_metrics if sm.state == stage), 0.0)
                for r in results
            ]
            dropoff_rates = [
                next((sm.drop_off_rate for sm in r.stage_metrics if sm.state == stage), 0.0)
                for r in results
            ]
            times = [
                next((sm.avg_time_seconds for sm in r.stage_metrics if sm.state == stage), 0.0)
                for r in results
            ]

            mean_entry = float(np.mean(entry_rates))
            mean_dropoff = float(np.mean(dropoff_rates))
            mean_time = float(np.mean(times))
            std_entry = float(np.std(entry_rates)) if len(entry_rates) > 1 else 0.0

            aggregations.append(
                StageAggregation(
                    state=stage,
                    mean_entry_rate=round(mean_entry, 4),
                    mean_drop_off_rate=round(mean_dropoff, 4),
                    mean_time_seconds=round(mean_time, 2),
                    std_entry_rate=round(std_entry, 4),
                )
            )

            if mean_dropoff > worst_dropoff:
                worst_dropoff = mean_dropoff
                worst_stage = stage

        return aggregations, worst_stage

    def _price_curve(
        self,
        base_price: float,
        base_conversion: float,
        price_sensitivity: float,
    ) -> list[PriceCurvePoint]:
        multipliers = [0.4, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 1.8, 2.2]
        points: list[tuple[float, float]] = []

        for m in multipliers:
            price = base_price * m
            decay = 1.0 / (1.0 + price_sensitivity * 3.5 * (m - 0.6))
            conv = float(np.clip(base_conversion * decay, 0.001, 0.99))
            points.append((price, conv))

        revenues = [p * c for p, c in points]
        opt_idx = int(np.argmax(revenues))

        curve: list[PriceCurvePoint] = []
        for i, (price, conv) in enumerate(points):
            curve.append(
                PriceCurvePoint(
                    price=round(price, 0),
                    conversion_rate=round(conv, 4),
                    revenue_per_1000_visitors=round(conv * price * 1000, 0),
                    is_optimal=(i == opt_idx),
                )
            )

        return curve

    def _demographic_segments(
        self,
        results: list[FunnelResult],
        mean_conversion: float,
    ) -> list[DemographicSegment]:
        income_data: dict[str, list[float]] = {}
        region_data: dict[str, list[float]] = {}
        device_data: dict[str, list[float]] = {}

        for r in results:
            for bracket, v in r.demographics.by_income_bracket.items():
                income_data.setdefault(bracket, []).append(v["conversion_rate"])
            for region, v in r.demographics.by_region.items():
                region_data.setdefault(region, []).append(v["conversion_rate"])
            for device, v in r.demographics.by_device.items():
                device_data.setdefault(device, []).append(v["conversion_rate"])

        segments: list[DemographicSegment] = []

        def _add(name: str, data: dict[str, list[float]], count_frac: float) -> None:
            for key, vals in data.items():
                mean_cr = float(np.mean(vals))
                revenue_idx = (mean_cr / mean_conversion) if mean_conversion > 0 else 1.0
                segments.append(
                    DemographicSegment(
                        name=f"{name}:{key}",
                        conversion_rate=round(mean_cr, 4),
                        count_fraction=round(count_frac, 3),
                        revenue_index=round(revenue_idx, 3),
                    )
                )

        n_income = len(income_data)
        n_region = len(region_data)
        n_device = len(device_data)

        _add("income", income_data, 1.0 / max(n_income, 1))
        _add("region", region_data, 1.0 / max(n_region, 1))
        _add("device", device_data, 1.0 / max(n_device, 1))

        segments.sort(key=lambda s: s.revenue_index, reverse=True)
        return segments

    def _generate_insights(
        self,
        mean_conversion: float,
        stage_aggs: list[StageAggregation],
        worst_stage: str,
        price_curve: list[PriceCurvePoint],
        std_dev: float,
        demographics: list[DemographicSegment],
    ) -> list[Insight]:
        _ = worst_stage
        insights: list[Insight] = []

        if mean_conversion < 0.01:
            insights.append(
                Insight(
                    "CRITICAL",
                    "PRICING",
                    f"Conversion rate of {mean_conversion:.1%} is critically low. "
                    "Fewer than 1 in 100 simulated users converted. "
                    "Pricing or trust assumptions likely need rethinking before launch.",
                )
            )
        elif mean_conversion < 0.03:
            insights.append(
                Insight(
                    "WARNING",
                    "PRICING",
                    f"Conversion rate of {mean_conversion:.1%} is below the "
                    "Indian SaaS/D2C benchmark of 3-5%. Consider A/B testing pricing.",
                )
            )
        elif mean_conversion > 0.10:
            insights.append(
                Insight(
                    "INFO",
                    "MARKET",
                    f"Conversion rate of {mean_conversion:.1%} exceeds benchmarks. "
                    "Focus on scaling acquisition - the funnel is healthy.",
                )
            )

        for sa in stage_aggs:
            if sa.state == "DECIDE" and sa.mean_drop_off_rate > 0.60:
                insights.append(
                    Insight(
                        "CRITICAL",
                        "PRICING",
                        f"{sa.mean_drop_off_rate:.0%} of users who reached checkout "
                        "abandoned. Strong signal of price resistance or trust gap at "
                        "the final step.",
                    )
                )
            if sa.state == "CONSIDER" and sa.mean_drop_off_rate > 0.55:
                insights.append(
                    Insight(
                        "WARNING",
                        "UX",
                        f"{sa.mean_drop_off_rate:.0%} drop-off at the consideration "
                        "stage. Users are browsing but not convincing themselves. "
                        "Add social proof, case studies, or comparison tables.",
                    )
                )
            if sa.state == "BROWSE" and sa.mean_drop_off_rate > 0.45:
                insights.append(
                    Insight(
                        "WARNING",
                        "ACQUISITION",
                        f"{sa.mean_drop_off_rate:.0%} of arriving users leave at browse. "
                        "The landing page is not communicating value quickly enough.",
                    )
                )

        optimal = next((p for p in price_curve if p.is_optimal), None)
        if optimal:
            best_rev = optimal.revenue_per_1000_visitors
            current = next((p for p in price_curve if abs(p.price - price_curve[5].price) < 1), None)
            if current and best_rev > current.revenue_per_1000_visitors * 1.15:
                uplift = ((best_rev / current.revenue_per_1000_visitors) - 1) if current.revenue_per_1000_visitors > 0 else 0.0
                insights.append(
                    Insight(
                        "INFO",
                        "PRICING",
                        f"Optimal price point is INR {optimal.price:,.0f} - this generates "
                        f"INR {best_rev:,.0f} revenue per 1,000 visitors, "
                        f"{uplift:.0%} above current pricing.",
                    )
                )

        if std_dev > 0.04:
            insights.append(
                Insight(
                    "WARNING",
                    "MARKET",
                    "High variance across simulation runs indicates unstable conversion "
                    "behaviour. Results depend heavily on which customer segment you "
                    "reach first. Validate with a small-scale real launch before scaling.",
                )
            )

        top_segment = demographics[0] if demographics else None
        if top_segment and top_segment.revenue_index > 1.4:
            insights.append(
                Insight(
                    "INFO",
                    "MARKET",
                    f"Segment '{top_segment.name}' converts at "
                    f"{top_segment.conversion_rate:.1%} - "
                    f"{top_segment.revenue_index:.1f}x the overall average. "
                    "Consider targeting this segment in early marketing.",
                )
            )

        order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        insights.sort(key=lambda i: order.get(i.severity, 3))
        return insights

    def _confidence_score(
        self,
        std_dev: float,
        n_runs: int,
        n_agents: int,
    ) -> int:
        run_bonus = min(20, n_runs * 8)
        agent_bonus = min(30, int(n_agents / 500))
        std_penalty = min(40, int(std_dev * 600))

        score = 50 + run_bonus + agent_bonus - std_penalty
        return int(np.clip(score, 10, 99))

    def aggregate(
        self,
        results: list[FunnelResult],
        base_price: float = 999.0,
        price_sensitivity: float = 0.55,
    ) -> AggregatedResult:
        if not results:
            raise ValueError("results list is empty - nothing to aggregate")

        n = len(results)

        conv_rates = [r.conversion_rate for r in results]
        revenues = [r.revenue_projection for r in results]
        total_agents = results[0].total_agents

        mean_conv = float(np.mean(conv_rates))
        std_dev = float(np.std(conv_rates, ddof=1)) if n > 1 else 0.0
        mean_rev = float(np.mean(revenues))

        ci_90 = self._ci(conv_rates, 0.90)
        ci_95 = self._ci(conv_rates, 0.95)
        rev_ci = self._revenue_ci(revenues, 0.90)

        stage_aggs, worst_stage = self._aggregate_stages(results)
        price_curve = self._price_curve(base_price, mean_conv, price_sensitivity)
        optimal = next((p for p in price_curve if p.is_optimal), price_curve[0])
        demo_segments = self._demographic_segments(results, mean_conv)

        insights = self._generate_insights(
            mean_conversion=mean_conv,
            stage_aggs=stage_aggs,
            worst_stage=worst_stage,
            price_curve=price_curve,
            std_dev=std_dev,
            demographics=demo_segments,
        )

        conf_score = self._confidence_score(std_dev, n, total_agents)

        logger.info(
            f"[Aggregation] Complete - runs={n} mean_conv={mean_conv:.3f} "
            f"std={std_dev:.4f} confidence={conf_score}"
        )

        return AggregatedResult(
            mean_conversion_rate=round(mean_conv, 4),
            std_dev=round(std_dev, 4),
            ci_90=ci_90,
            ci_95=ci_95,
            total_agents=total_agents,
            total_runs=n,
            mean_revenue=round(mean_rev, 2),
            revenue_ci_90=rev_ci,
            stage_aggregations=stage_aggs,
            worst_drop_off_stage=worst_stage,
            price_curve=price_curve,
            optimal_price=optimal.price,
            optimal_conversion=optimal.conversion_rate,
            demographic_segments=demo_segments,
            insights=insights,
            confidence_score=conf_score,
            all_conversion_rates=[round(c, 4) for c in conv_rates],
        )

    def to_dict(self, result: AggregatedResult) -> dict[str, Any]:
        return {
            "mean_conversion_rate": result.mean_conversion_rate,
            "std_dev": result.std_dev,
            "ci_90": {"low": result.ci_90.low, "high": result.ci_90.high},
            "ci_95": {"low": result.ci_95.low, "high": result.ci_95.high},
            "total_agents": result.total_agents,
            "total_runs": result.total_runs,
            "mean_revenue": result.mean_revenue,
            "revenue_ci_90": {"low": result.revenue_ci_90.low, "high": result.revenue_ci_90.high},
            "confidence_score": result.confidence_score,
            "worst_drop_off_stage": result.worst_drop_off_stage,
            "optimal_price": result.optimal_price,
            "optimal_conversion": result.optimal_conversion,
            "stage_aggregations": [
                {
                    "state": s.state,
                    "mean_entry_rate": s.mean_entry_rate,
                    "mean_drop_off_rate": s.mean_drop_off_rate,
                    "mean_time_seconds": s.mean_time_seconds,
                    "std_entry_rate": s.std_entry_rate,
                }
                for s in result.stage_aggregations
            ],
            "price_curve": [
                {
                    "price": p.price,
                    "conversion_rate": p.conversion_rate,
                    "revenue_per_1000_visitors": p.revenue_per_1000_visitors,
                    "is_optimal": p.is_optimal,
                }
                for p in result.price_curve
            ],
            "demographic_segments": [
                {
                    "name": d.name,
                    "conversion_rate": d.conversion_rate,
                    "count_fraction": d.count_fraction,
                    "revenue_index": d.revenue_index,
                }
                for d in result.demographic_segments
            ],
            "insights": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "text": i.text,
                }
                for i in result.insights
            ],
            "all_conversion_rates": result.all_conversion_rates,
        }


if __name__ == "__main__":
    import json

    from app.simulation.funnel import FunnelExecutionEngine
    from app.simulation.profiles import AgentProfileGenerator

    env_params = {
        "consumer_volume": 500,
        "growth_rate_per_month": 8.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.55,
        "market_maturity": 0.3,
    }
    assumptions = [
        {"id": 1, "text": "pricing assumption", "sensitivity": "CRITICAL", "impact_score": 9.0},
        {"id": 2, "text": "word of mouth growth", "sensitivity": "HIGH", "impact_score": 7.0},
    ]

    gen = AgentProfileGenerator()
    exec_engine = FunnelExecutionEngine(num_workers=1, store_paths=False)

    raw: list[FunnelResult] = []
    for seed in [42, 123, 999]:
        agents = gen.generate_population(500, env_params, seed=seed)
        result = exec_engine.run_batch(agents, env_params, assumptions, seed=seed)
        raw.append(result)
        print(f"Run seed={seed}: conversion={result.conversion_rate:.3f} revenue=INR {result.revenue_projection:,.0f}")

    aggregator = ResultsAggregator()
    agg = aggregator.aggregate(raw, base_price=999.0, price_sensitivity=0.55)

    print("\n--- Aggregated Result ---")
    print(f"  mean_conversion:  {agg.mean_conversion_rate:.3f}")
    print(f"  std_dev:          {agg.std_dev:.4f}")
    print(f"  CI 90%:           [{agg.ci_90.low}, {agg.ci_90.high}]")
    print(f"  CI 95%:           [{agg.ci_95.low}, {agg.ci_95.high}]")
    print(f"  mean_revenue:     INR {agg.mean_revenue:,.0f}")
    print(f"  confidence_score: {agg.confidence_score}/100")
    print(f"  worst_stage:      {agg.worst_drop_off_stage}")
    print(f"  optimal_price:    INR {agg.optimal_price:,.0f}")

    print("\n--- Stage Analysis ---")
    for s in agg.stage_aggregations:
        print(f"  {s.state:<10} entry={s.mean_entry_rate:.2%} dropoff={s.mean_drop_off_rate:.2%}")

    print("\n--- Price Curve ---")
    for p in agg.price_curve:
        marker = " <- OPTIMAL" if p.is_optimal else ""
        print(f"  INR {p.price:>6.0f}  conv={p.conversion_rate:.3f}  rev/1k=INR {p.revenue_per_1000_visitors:>7,.0f}{marker}")

    print("\n--- Insights ---")
    for ins in agg.insights:
        print(f"  [{ins.severity}] {ins.category}: {ins.text[:80]}...")

    print("\n--- Serialisation check ---")
    data = aggregator.to_dict(agg)
    json_str = json.dumps(data)
    print(f"  JSON length: {len(json_str)} chars")
    assert "mean_conversion_rate" in data
    assert "price_curve" in data
    assert "insights" in data
    print("\nAll aggregation checks passed")
