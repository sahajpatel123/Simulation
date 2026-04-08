from __future__ import annotations

import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from typing import Any

import numpy as np

from app.simulation.markov import MarkovBehaviourModel, STATES
from app.simulation.profiles import AgentProfile
from app.simulation.sampling import BetaSamplingEngine, MultiRunResult

logger = logging.getLogger(__name__)

# ================================================================
# DESIGN CONTRACT
#
# Orchestration layer tying together:
# - MarkovBehaviourModel (Step 21a)
# - AgentProfile (Step 21b)
# - BetaSamplingEngine (Step 21c)
# ================================================================


@dataclass
class StageMetrics:
    state: str
    agent_count: int
    entry_rate: float
    drop_off_rate: float
    avg_time_seconds: float


@dataclass
class DemographicBreakdown:
    by_income_bracket: dict[str, dict[str, float]]
    by_region: dict[str, dict[str, float]]
    by_device: dict[str, dict[str, float]]
    by_age_bracket: dict[str, dict[str, float]]


@dataclass
class FunnelResult:
    total_agents: int
    converted: int
    conversion_rate: float
    avg_time_seconds: float
    revenue_projection: float
    ci_low: float
    ci_high: float
    stage_metrics: list[StageMetrics]
    stage_counts: dict[str, int]
    demographics: DemographicBreakdown
    wall_time_seconds: float
    agents_per_second: float
    seed_used: int
    sample_paths: list[list[str]] = field(default_factory=list)


def _run_single_agent(args: tuple) -> dict[str, Any]:
    (
        agent_dict,
        transition_matrix,
        assumption_impact,
        price_point,
        aov_baseline,
        product_strength,
        seed,
    ) = args

    markov = MarkovBehaviourModel()
    sampling = BetaSamplingEngine(seed=seed)

    chain_result = markov.run_chain(
        agent_profile=agent_dict,
        transition_matrix=transition_matrix,
        seed=seed,
    )

    decision = sampling.full_conversion_decision(
        agent_profile=agent_dict,
        assumption_impact=assumption_impact,
        price_point=price_point,
        aov_baseline=aov_baseline,
        product_strength=product_strength,
    )

    markov_converted = bool(chain_result["converted"])
    final_converted = markov_converted and decision.converted
    final_state = chain_result["final_state"]
    path = list(chain_result["path"])

    if markov_converted and not final_converted:
        final_state = "ABANDON"
        if path and path[-1] == "PURCHASE":
            path[-1] = "ABANDON"

    return {
        "final_state": "PURCHASE" if final_converted else final_state,
        "converted": final_converted,
        "path": path,
        "time_seconds": chain_result["total_time_seconds"],
        "retention_days": decision.retention_days,
        "price_accepted": decision.price_accepted,
        "markov_converted": markov_converted,
        "income_bracket": agent_dict.get("income_bracket", "UNKNOWN"),
        "region": agent_dict.get("region", "UNKNOWN"),
        "device_type": agent_dict.get("device_type", "UNKNOWN"),
        "age": agent_dict.get("age", 30),
    }


class FunnelExecutionEngine:
    def __init__(
        self,
        num_workers: int | None = None,
        store_paths: bool = False,
        max_stored_paths: int = 100,
    ) -> None:
        self.num_workers = num_workers or max(1, cpu_count() - 1)
        self.store_paths = store_paths
        self.max_stored_paths = max_stored_paths
        self._markov = MarkovBehaviourModel()

    def _derive_assumption_impact(
        self,
        assumptions: list[dict[str, Any]],
    ) -> dict[str, float]:
        weights = {"CRITICAL": -0.10, "HIGH": -0.06, "MEDIUM": -0.03, "LOW": -0.01}
        impact: dict[str, float] = {}
        for a in assumptions:
            key = a.get("sensitivity", "MEDIUM")
            score = float(a.get("impact_score", 5.0)) / 10.0
            impact[f"{key}_{a.get('id', id(a))}"] = weights.get(key, -0.03) * score
        return impact

    def _derive_product_strength(
        self,
        assumptions: list[dict[str, Any]],
    ) -> float:
        if not assumptions:
            return 0.65

        critical = sum(1 for a in assumptions if a.get("sensitivity") == "CRITICAL")
        high = sum(1 for a in assumptions if a.get("sensitivity") == "HIGH")

        strength = 0.85 - (critical * 0.08) - (high * 0.04)
        return float(np.clip(strength, 0.15, 0.90))

    def _build_stage_metrics(
        self,
        stage_counts: dict[str, int],
        stage_times: dict[str, list[float]],
        total_agents: int,
    ) -> list[StageMetrics]:
        ordered_stages = [s.value for s in STATES]
        metrics: list[StageMetrics] = []
        prev_count = total_agents

        for stage in ordered_stages:
            count = stage_counts.get(stage, 0)
            times = stage_times.get(stage, [0.0])
            entry_r = count / total_agents if total_agents > 0 else 0.0
            raw_dropoff = 1.0 - (count / prev_count) if prev_count > 0 else 0.0
            dropoff_r = float(np.clip(raw_dropoff, 0.0, 1.0))
            avg_time = float(np.mean(times)) if times else 0.0

            metrics.append(
                StageMetrics(
                    state=stage,
                    agent_count=count,
                    entry_rate=round(entry_r, 4),
                    drop_off_rate=round(dropoff_r, 4),
                    avg_time_seconds=round(avg_time, 2),
                )
            )
            prev_count = max(1, count)

        return metrics

    def _build_demographic_breakdown(
        self,
        raw_results: list[dict[str, Any]],
    ) -> DemographicBreakdown:
        def group(key: str) -> dict[str, dict[str, float]]:
            buckets: dict[str, list[bool]] = {}
            for r in raw_results:
                k = str(r.get(key, "UNKNOWN"))
                buckets.setdefault(k, []).append(bool(r["converted"]))
            return {
                k: {
                    "conversion_rate": round(sum(v) / len(v), 4) if v else 0.0,
                    "count": len(v),
                }
                for k, v in buckets.items()
            }

        age_buckets: dict[str, list[bool]] = {}
        for r in raw_results:
            age = int(r.get("age", 30))
            bracket = f"{(age // 10) * 10}s"
            age_buckets.setdefault(bracket, []).append(bool(r["converted"]))
        by_age = {
            k: {"conversion_rate": round(sum(v) / len(v), 4), "count": len(v)}
            for k, v in age_buckets.items()
        }

        return DemographicBreakdown(
            by_income_bracket=group("income_bracket"),
            by_region=group("region"),
            by_device=group("device_type"),
            by_age_bracket=by_age,
        )

    def run_batch(
        self,
        agents: list[AgentProfile],
        env_params: dict[str, Any],
        assumptions: list[dict[str, Any]],
        seed: int = 42,
    ) -> FunnelResult:
        if not agents:
            raise ValueError("agents list is empty - cannot run simulation")

        t_start = time.perf_counter()
        n = len(agents)

        transition_matrix = self._markov.build_transition_matrix(
            env_params=env_params,
            assumptions=assumptions,
            seed=seed,
        )

        assumption_impact = self._derive_assumption_impact(assumptions)
        product_strength = self._derive_product_strength(assumptions)
        price_point = float(env_params.get("average_order_value", 999.0))
        aov_baseline = price_point

        agent_args = [
            (
                agents[i].to_dict(),
                transition_matrix,
                assumption_impact,
                price_point,
                aov_baseline,
                product_strength,
                seed + i,
            )
            for i in range(n)
        ]

        logger.info(f"[Funnel] Starting batch: n={n} workers={self.num_workers} seed={seed}")

        raw_results: list[dict[str, Any]] = []

        if self.num_workers == 1:
            raw_results = [_run_single_agent(a) for a in agent_args]
        else:
            with ProcessPoolExecutor(max_workers=self.num_workers) as executor:
                futures = {executor.submit(_run_single_agent, a): i for i, a in enumerate(agent_args)}
                for future in as_completed(futures):
                    try:
                        raw_results.append(future.result())
                    except Exception as exc:
                        logger.warning(f"[Funnel] Agent {futures[future]} failed: {exc}")
                        raw_results.append(
                            {
                                "final_state": "ABANDON",
                                "converted": False,
                                "path": ["ARRIVE", "ABANDON"],
                                "time_seconds": 5.0,
                                "retention_days": 0,
                                "price_accepted": False,
                                "income_bracket": "UNKNOWN",
                                "region": "UNKNOWN",
                                "device_type": "UNKNOWN",
                                "age": 30,
                            }
                        )

        stage_counts: dict[str, int] = {s.value: 0 for s in STATES}
        stage_times: dict[str, list[float]] = {s.value: [] for s in STATES}
        converted = 0
        total_time = 0.0
        markov_converted_total = 0
        markov_price_accepted = 0
        sample_paths: list[list[str]] = []

        for result in raw_results:
            path = result.get("path", [])
            reached = set(path)
            for stage in reached:
                if stage in stage_counts:
                    stage_counts[stage] = stage_counts.get(stage, 0) + 1

            path_len = max(len(path), 1)
            per_stage_time = float(result.get("time_seconds", 0.0)) / path_len
            for stage in path:
                if stage in stage_counts:
                    stage_times.setdefault(stage, []).append(per_stage_time)

            if result["converted"]:
                converted += 1

            if result.get("markov_converted"):
                markov_converted_total += 1
                if result.get("price_accepted"):
                    markov_price_accepted += 1

            total_time += float(result.get("time_seconds", 0.0))

            if self.store_paths and len(sample_paths) < self.max_stored_paths:
                sample_paths.append(path)

        conversion_rate = converted / n if n > 0 else 0.0
        avg_time = total_time / n if n > 0 else 0.0
        revenue = converted * aov_baseline

        sampler = BetaSamplingEngine(seed=seed)
        avg_profile = {
            "motivation": float(np.mean([a.motivation for a in agents])),
            "price_sensitivity": float(np.mean([a.price_sensitivity for a in agents])),
            "digital_literacy": float(np.mean([a.digital_literacy for a in agents])),
            "trust_baseline": float(np.mean([a.trust_baseline for a in agents])),
            "patience_score": float(np.mean([a.patience_score for a in agents])),
            "monthly_income": float(np.mean([a.monthly_income for a in agents])),
        }
        multi: MultiRunResult = sampler.run_multiple(
            n_runs=3,
            agent_profile=avg_profile,
            assumption_impact=assumption_impact,
        )
        markov_rate = markov_converted_total / n if n > 0 else 0.0
        price_accept_given_markov = (
            markov_price_accepted / markov_converted_total
            if markov_converted_total > 0
            else 0.0
        )
        stochastic_width = max(0.005, multi.std * 2.0)
        ci_center = conversion_rate
        ci_low = max(0.0, ci_center - stochastic_width)
        ci_high = min(1.0, ci_center + stochastic_width)
        if markov_rate > 0 and price_accept_given_markov > 0:
            scale = markov_rate * price_accept_given_markov
            ci_low = max(0.0, min(ci_low, multi.ci_low * scale))
            ci_high = min(1.0, max(ci_high, multi.ci_high * scale))

        wall_time = time.perf_counter() - t_start
        logger.info(
            f"[Funnel] Complete: n={n} converted={converted} "
            f"rate={conversion_rate:.3f} wall={wall_time:.2f}s "
            f"aps={n / wall_time:.0f}"
        )

        return FunnelResult(
            total_agents=n,
            converted=converted,
            conversion_rate=round(conversion_rate, 4),
            avg_time_seconds=round(avg_time, 2),
            revenue_projection=round(revenue, 2),
            ci_low=round(ci_low, 4),
            ci_high=round(ci_high, 4),
            stage_metrics=self._build_stage_metrics(stage_counts, stage_times, n),
            stage_counts=stage_counts,
            demographics=self._build_demographic_breakdown(raw_results),
            wall_time_seconds=round(wall_time, 3),
            agents_per_second=round(n / wall_time, 1),
            seed_used=seed,
            sample_paths=sample_paths,
        )


if __name__ == "__main__":
    from app.simulation.profiles import AgentProfileGenerator

    env_params = {
        "consumer_volume": 1000,
        "growth_rate_per_month": 8.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.55,
        "market_maturity": 0.3,
    }

    assumptions = [
        {
            "id": 1,
            "text": "users will pay 999 without trial",
            "sensitivity": "CRITICAL",
            "impact_score": 9.1,
        },
        {
            "id": 2,
            "text": "word-of-mouth will drive growth",
            "sensitivity": "HIGH",
            "impact_score": 7.5,
        },
        {
            "id": 3,
            "text": "retention will be moderate",
            "sensitivity": "MEDIUM",
            "impact_score": 5.0,
        },
    ]

    generator = AgentProfileGenerator()
    agents = generator.generate_population(
        volume=1000,
        env_params=env_params,
        scenario_type=None,
        seed=42,
    )

    engine = FunnelExecutionEngine(num_workers=1, store_paths=True)
    result = engine.run_batch(agents, env_params, assumptions, seed=42)

    print("--- FunnelResult ---")
    print(f"  Total agents:    {result.total_agents}")
    print(f"  Converted:       {result.converted}")
    print(f"  Conversion rate: {result.conversion_rate:.2%}")
    print(f"  CI:              [{result.ci_low:.4f}, {result.ci_high:.4f}]")
    print(f"  Revenue:         {result.revenue_projection:,.0f}")
    print(f"  Wall time:       {result.wall_time_seconds:.2f}s")
    print(f"  Agents/sec:      {result.agents_per_second:.0f}")

    print("\n--- Stage Metrics ---")
    for sm in result.stage_metrics:
        print(
            f"  {sm.state:<10} count={sm.agent_count:<6} "
            f"entry={sm.entry_rate:.2%} dropoff={sm.drop_off_rate:.2%}"
        )

    print("\n--- Demographics (income) ---")
    for k, v in sorted(result.demographics.by_income_bracket.items()):
        print(f"  {k:<20} conv={v['conversion_rate']:.2%}  n={v['count']}")

    print("\n--- Sample path (first agent) ---")
    if result.sample_paths:
        print("  " + " -> ".join(result.sample_paths[0]))

    assert 0.0 <= result.conversion_rate <= 1.0
    assert result.ci_low <= result.conversion_rate <= result.ci_high + 0.05
    assert result.total_agents == 1000
    assert result.converted <= result.total_agents
    assert result.wall_time_seconds > 0
    print("\nAll funnel engine checks passed")
