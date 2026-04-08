from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import beta as scipy_beta
from scipy.stats import norm

logger = logging.getLogger(__name__)

# ================================================================
# DESIGN CONTRACT
#
# This module is the single source of truth for all stochastic
# decisions in TheCee's simulation engine.
# ================================================================


@dataclass(frozen=True)
class SampleResult:
    value: float
    ci_low: float
    ci_high: float
    mean: float
    std: float
    alpha: float
    beta_param: float


@dataclass(frozen=True)
class MultiRunResult:
    mean: float
    ci_low: float
    ci_high: float
    std: float
    n_runs: int
    samples: tuple[float, ...]


@dataclass(frozen=True)
class ConversionDecision:
    converted: bool
    probability_used: float
    price_accepted: bool
    retention_days: int


def mean_variance_to_alpha_beta(
    mean: float,
    variance: float,
) -> tuple[float, float]:
    mean = float(np.clip(mean, 0.01, 0.99))

    max_variance = mean * (1.0 - mean)
    variance = float(np.clip(variance, 1e-6, max_variance * 0.99))

    common = (mean * (1.0 - mean) / variance) - 1.0
    alpha = max(0.1, mean * common)
    beta_p = max(0.1, (1.0 - mean) * common)

    return alpha, beta_p


def alpha_beta_to_mean_std(alpha: float, beta_p: float) -> tuple[float, float]:
    mean = alpha / (alpha + beta_p)
    var = (alpha * beta_p) / ((alpha + beta_p) ** 2 * (alpha + beta_p + 1))
    return mean, float(np.sqrt(var))


class BetaSamplingEngine:
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = np.random.default_rng(seed)

    def _draw(self, alpha: float, beta_p: float, size: int = 1) -> np.ndarray:
        return np.clip(
            self._rng.beta(alpha, beta_p, size=size),
            0.001,
            0.999,
        )

    def sample(
        self,
        mean: float,
        variance: float = 0.06,
        size: int = 1,
    ) -> SampleResult:
        alpha, beta_p = mean_variance_to_alpha_beta(mean, variance)
        samples = self._draw(alpha, beta_p, size=max(size, 1))
        th_mean, th_std = alpha_beta_to_mean_std(alpha, beta_p)

        ci_lo = float(scipy_beta.ppf(0.025, alpha, beta_p))
        ci_hi = float(scipy_beta.ppf(0.975, alpha, beta_p))

        return SampleResult(
            value=float(samples.mean()),
            ci_low=ci_lo,
            ci_high=ci_hi,
            mean=th_mean,
            std=th_std,
            alpha=alpha,
            beta_param=beta_p,
        )

    def sample_conversion_probability(
        self,
        agent_profile: dict[str, Any],
        assumption_impact: dict[str, float],
    ) -> SampleResult:
        base_mean = 0.035

        motivation = float(agent_profile.get("motivation", 0.5))
        price_sensitivity = float(agent_profile.get("price_sensitivity", 0.55))
        digital_literacy = float(agent_profile.get("digital_literacy", 0.62))
        trust_baseline = float(agent_profile.get("trust_baseline", 0.5))
        patience_score = float(agent_profile.get("patience_score", 0.43))

        delta = motivation * 0.22
        delta -= price_sensitivity * 0.18
        delta += digital_literacy * 0.08
        delta += trust_baseline * 0.06
        delta += patience_score * 0.04

        assumption_delta = sum(assumption_impact.values())
        delta += float(np.clip(assumption_delta, -0.20, 0.10))

        adjusted_mean = float(np.clip(base_mean + delta, 0.005, 0.40))
        variance = 0.012 + (0.25 - abs(adjusted_mean - 0.25)) * 0.015

        return self.sample(mean=adjusted_mean, variance=variance, size=500)

    def sample_price_acceptance(
        self,
        agent_profile: dict[str, Any],
        price_point: float,
        aov_baseline: float = 999.0,
    ) -> bool:
        price_sensitivity = float(agent_profile.get("price_sensitivity", 0.55))
        monthly_income = float(agent_profile.get("monthly_income", 35_000))

        price_ratio = float(np.clip(price_point / max(aov_baseline, 1.0), 0.1, 5.0))
        income_factor = float(np.clip(1.0 - (monthly_income / 400_000), 0.1, 0.9))

        accept_prob = 1.0 - (price_sensitivity * 0.7 * price_ratio * income_factor)
        accept_prob = float(np.clip(accept_prob, 0.05, 0.97))

        return bool(self._rng.random() < accept_prob)

    def sample_retention_days(
        self,
        agent_profile: dict[str, Any],
        product_strength: float = 0.65,
    ) -> int:
        patience = float(agent_profile.get("patience_score", 0.43))
        motivation = float(agent_profile.get("motivation", 0.44))

        mean_fraction = float(
            np.clip(
                0.15 + (patience * 0.25) + (motivation * 0.20) + (product_strength * 0.25),
                0.05,
                0.85,
            )
        )

        result = self.sample(mean=mean_fraction, variance=0.025)
        days = int(result.value * 90)
        return max(1, days)

    def sample_time_on_page(
        self,
        agent_profile: dict[str, Any],
        page_type: str = "landing",
    ) -> float:
        page_base_times: dict[str, tuple[float, float]] = {
            "landing": (38.0, 22.0),
            "pricing": (54.0, 28.0),
            "product": (72.0, 35.0),
            "checkout": (45.0, 20.0),
            "about": (28.0, 18.0),
        }
        mu, sigma = page_base_times.get(page_type, (30.0, 15.0))

        literacy_factor = 0.55 + (1.0 - float(agent_profile.get("digital_literacy", 0.62))) * 0.9
        patience_factor = 0.60 + float(agent_profile.get("patience_score", 0.43)) * 0.80

        adjusted_mu = mu * literacy_factor * patience_factor
        seconds = float(np.clip(self._rng.normal(adjusted_mu, sigma), 2.0, 600.0))
        return round(seconds, 1)

    def run_multiple(
        self,
        n_runs: int,
        agent_profile: dict[str, Any],
        assumption_impact: dict[str, float],
    ) -> MultiRunResult:
        samples: list[float] = []
        for i in range(n_runs):
            sub = BetaSamplingEngine(seed=self.seed + i * 1000)
            result = sub.sample_conversion_probability(agent_profile, assumption_impact)
            samples.append(result.value)

        arr = np.array(samples, dtype=np.float64)

        return MultiRunResult(
            mean=round(float(arr.mean()), 4),
            ci_low=round(float(np.percentile(arr, 2.5)), 4),
            ci_high=round(float(np.percentile(arr, 97.5)), 4),
            std=round(float(arr.std()), 4),
            n_runs=n_runs,
            samples=tuple(round(float(s), 4) for s in arr),
        )

    def full_conversion_decision(
        self,
        agent_profile: dict[str, Any],
        assumption_impact: dict[str, float],
        price_point: float = 999.0,
        aov_baseline: float = 999.0,
        product_strength: float = 0.65,
    ) -> ConversionDecision:
        conv_result = self.sample_conversion_probability(agent_profile, assumption_impact)
        price_accepted = self.sample_price_acceptance(agent_profile, price_point, aov_baseline)
        retention = self.sample_retention_days(agent_profile, product_strength)

        converted = (self._rng.random() < conv_result.value) and price_accepted

        return ConversionDecision(
            converted=converted,
            probability_used=round(conv_result.value, 4),
            price_accepted=price_accepted,
            retention_days=retention,
        )


if __name__ == "__main__":
    import json

    engine = BetaSamplingEngine(seed=42)

    core = engine.sample(mean=0.19, variance=0.015)
    print("--- Core sample (mean=0.19) ---")
    print(f"  value={core.value:.4f}  ci=[{core.ci_low:.4f}, {core.ci_high:.4f}]  std={core.std:.4f}")
    assert 0.0 < core.value < 1.0, "value out of range"
    assert core.ci_low < core.value < core.ci_high or abs(core.value - core.ci_low) < 0.01

    agent = {
        "motivation": 0.7,
        "price_sensitivity": 0.55,
        "digital_literacy": 0.68,
        "trust_baseline": 0.55,
        "patience_score": 0.45,
        "monthly_income": 60_000,
    }
    assumption_impact = {"CRITICAL": -0.08, "HIGH": -0.04}
    cp = engine.sample_conversion_probability(agent, assumption_impact)
    print("\n--- Conversion probability ---")
    print(f"  value={cp.value:.4f}  ci=[{cp.ci_low:.4f}, {cp.ci_high:.4f}]")
    assert 0.001 < cp.value < 0.40, f"unrealistic conversion probability: {cp.value}"

    accept_high = engine.sample_price_acceptance(agent, price_point=499.0)
    accept_low = engine.sample_price_acceptance(agent, price_point=4999.0)
    print("\n--- Price acceptance ---")
    print(f"  499 accepted={accept_high}  4999 accepted={accept_low}")

    days = engine.sample_retention_days(agent, product_strength=0.7)
    print("\n--- Retention days ---")
    print(f"  days={days}")
    assert 1 <= days <= 90

    mr = engine.run_multiple(20, agent, assumption_impact)
    print("\n--- Multi-run (n=20) ---")
    print(f"  mean={mr.mean}  ci=[{mr.ci_low}, {mr.ci_high}]  std={mr.std}")

    decision = engine.full_conversion_decision(
        agent,
        assumption_impact,
        price_point=999.0,
        aov_baseline=999.0,
        product_strength=0.65,
    )
    print("\n--- Full conversion decision ---")
    print(
        f"  converted={decision.converted}  "
        f"price_accepted={decision.price_accepted}  retention={decision.retention_days}d"
    )

    e1 = BetaSamplingEngine(seed=99)
    e2 = BetaSamplingEngine(seed=99)
    v1 = e1.sample(mean=0.25, variance=0.02).value
    v2 = e2.sample(mean=0.25, variance=0.02).value
    assert v1 == v2, f"Reproducibility broken: {v1} != {v2}"
    print("\n--- Reproducibility check ---")
    print(f"  seed=99 produces same value twice: {v1:.6f} OK")

    _ = norm
    _ = json
    print("\nAll sampling engine checks passed")
