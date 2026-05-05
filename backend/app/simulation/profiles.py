from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from scipy.stats import beta as beta_dist

logger = logging.getLogger(__name__)

# ================================================================
# ENUMS
# ================================================================


class DeviceType(str, Enum):
    MOBILE = "MOBILE"
    DESKTOP = "DESKTOP"
    TABLET = "TABLET"


class Region(str, Enum):
    METRO = "METRO"
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"
    CENTRAL = "CENTRAL"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class IncomeBracket(str, Enum):
    LOW_INCOME = "LOW_INCOME"
    LOWER_MIDDLE = "LOWER_MIDDLE"
    MIDDLE = "MIDDLE"
    UPPER_MIDDLE = "UPPER_MIDDLE"
    HIGH_INCOME = "HIGH_INCOME"


# ================================================================
# AGENT PROFILE DATACLASS
# Lightweight by design: no ORM, no DB calls.
# All floats are in [0.0, 1.0] unless documented otherwise.
# ================================================================


@dataclass
class AgentProfile:
    # Demographic
    age: int
    income_bracket: IncomeBracket
    monthly_income: int
    region: Region
    device_type: DeviceType

    # Behavioural traits
    digital_literacy: float
    price_sensitivity: float
    patience_score: float
    motivation: float
    trust_baseline: float

    # Derived tier
    tier: str = field(init=False)

    def __post_init__(self) -> None:
        if self.region in (Region.METRO,):
            self.tier = "METRO"
        elif self.region in (Region.NORTH, Region.SOUTH, Region.EAST, Region.WEST):
            self.tier = "TIER1"
        elif self.region == Region.TIER2:
            self.tier = "TIER2"
        else:
            self.tier = "TIER3"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["income_bracket"] = self.income_bracket.value
        data["region"] = self.region.value
        data["device_type"] = self.device_type.value
        return data


# ================================================================
# DEMOGRAPHIC DISTRIBUTIONS
# ================================================================

AGE_BRACKETS: list[tuple[int, int]] = [
    (18, 24),
    (25, 34),
    (35, 44),
    (45, 54),
    (55, 65),
]
AGE_WEIGHTS: list[float] = [0.27, 0.41, 0.18, 0.10, 0.04]

INCOME_BRACKETS: list[tuple[IncomeBracket, int, int]] = [
    (IncomeBracket.LOW_INCOME, 10_000, 20_000),
    (IncomeBracket.LOWER_MIDDLE, 20_000, 40_000),
    (IncomeBracket.MIDDLE, 40_000, 80_000),
    (IncomeBracket.UPPER_MIDDLE, 80_000, 150_000),
    (IncomeBracket.HIGH_INCOME, 150_000, 400_000),
]
INCOME_WEIGHTS: list[float] = [0.22, 0.35, 0.26, 0.12, 0.05]

REGION_VALUES: list[Region] = list(Region)
REGION_WEIGHTS: list[float] = [0.12, 0.18, 0.20, 0.14, 0.16, 0.10, 0.06, 0.04]

DEVICE_VALUES: list[DeviceType] = [DeviceType.MOBILE, DeviceType.DESKTOP, DeviceType.TABLET]
DEVICE_WEIGHTS: list[float] = [0.79, 0.17, 0.04]

# ================================================================
# BETA DISTRIBUTION PARAMETERS
# ================================================================

TRAIT_PARAMS: dict[str, tuple[float, float]] = {
    "digital_literacy": (3.2, 1.6),
    "price_sensitivity": (2.8, 1.9),
    "patience_score": (1.8, 2.4),
    "motivation": (2.2, 2.8),
    "trust_baseline": (2.5, 2.5),
}

INCOME_TRAIT_ADJUSTMENTS: dict[IncomeBracket, dict[str, tuple[float, float]]] = {
    IncomeBracket.LOW_INCOME: {
        "price_sensitivity": (+1.2, 0.0),
        "digital_literacy": (-0.8, +0.5),
        "motivation": (-0.3, 0.0),
    },
    IncomeBracket.LOWER_MIDDLE: {
        "price_sensitivity": (+0.5, 0.0),
        "digital_literacy": (-0.2, 0.0),
    },
    IncomeBracket.MIDDLE: {},
    IncomeBracket.UPPER_MIDDLE: {
        "price_sensitivity": (0.0, +0.8),
        "digital_literacy": (+0.6, 0.0),
        "trust_baseline": (+0.4, 0.0),
    },
    IncomeBracket.HIGH_INCOME: {
        "price_sensitivity": (0.0, +1.5),
        "digital_literacy": (+1.0, 0.0),
        "trust_baseline": (+0.6, 0.0),
        "patience_score": (+0.4, 0.0),
    },
}

REGION_TRAIT_ADJUSTMENTS: dict[Region, dict[str, tuple[float, float]]] = {
    Region.METRO: {
        "digital_literacy": (+0.8, 0.0),
        "price_sensitivity": (0.0, +0.4),
        "patience_score": (-0.3, 0.0),
    },
    Region.TIER2: {
        "price_sensitivity": (+0.4, 0.0),
        "digital_literacy": (-0.4, +0.2),
    },
    Region.TIER3: {
        "price_sensitivity": (+0.8, 0.0),
        "digital_literacy": (-0.8, +0.4),
        "trust_baseline": (-0.4, +0.2),
    },
    Region.NORTH: {},
    Region.SOUTH: {"digital_literacy": (+0.3, 0.0)},
    Region.EAST: {},
    Region.WEST: {"trust_baseline": (+0.2, 0.0)},
    Region.CENTRAL: {"price_sensitivity": (+0.3, 0.0)},
}

SCENARIO_TRAIT_ADJUSTMENTS: dict[str, dict[str, tuple[float, float]]] = {
    "RECESSION": {
        "price_sensitivity": (+1.5, 0.0),
        "motivation": (-0.8, +0.4),
        "trust_baseline": (-0.5, +0.3),
    },
    "SATURATED": {
        "price_sensitivity": (+0.8, 0.0),
        "trust_baseline": (-0.3, +0.2),
    },
    "EARLY_ADOPTER": {
        "motivation": (+1.2, 0.0),
        "trust_baseline": (+0.8, 0.0),
        "price_sensitivity": (0.0, +0.6),
    },
    "HIGH_GROWTH": {
        "motivation": (+0.8, 0.0),
        "digital_literacy": (+0.4, 0.0),
    },
    "VIRAL_LAUNCH": {
        "motivation": (+1.5, 0.0),
        "trust_baseline": (+0.5, 0.0),
    },
}


class AgentProfileGenerator:
    """
    Generates synthetic consumer profiles representing Indian internet users.
    Pure: no database calls, no side effects.
    """

    def _sample_beta(
        self,
        alpha: float,
        beta: float,
        low: float = 0.03,
        high: float = 0.97,
    ) -> float:
        alpha = max(0.1, alpha)
        beta = max(0.1, beta)
        return float(np.clip(beta_dist.rvs(alpha, beta), low, high))

    def _build_trait_params(
        self,
        income_bracket: IncomeBracket,
        region: Region,
        scenario_type: str | None,
    ) -> dict[str, tuple[float, float]]:
        params = {k: list(v) for k, v in TRAIT_PARAMS.items()}

        for source in [
            INCOME_TRAIT_ADJUSTMENTS.get(income_bracket, {}),
            REGION_TRAIT_ADJUSTMENTS.get(region, {}),
            SCENARIO_TRAIT_ADJUSTMENTS.get(scenario_type or "", {}),
        ]:
            for trait, (da, db) in source.items():
                if trait in params:
                    params[trait][0] = max(0.1, params[trait][0] + da)
                    params[trait][1] = max(0.1, params[trait][1] + db)

        return {k: (v[0], v[1]) for k, v in params.items()}

    def generate_one(
        self,
        env_params: dict[str, Any],
        scenario_type: str | None = None,
    ) -> AgentProfile:
        _ = env_params

        age_bracket_idx = np.random.choice(len(AGE_BRACKETS), p=AGE_WEIGHTS)
        age_lo, age_hi = AGE_BRACKETS[age_bracket_idx]
        age = int(np.random.randint(age_lo, age_hi + 1))

        income_idx = np.random.choice(len(INCOME_BRACKETS), p=INCOME_WEIGHTS)
        income_enum, income_lo, income_hi = INCOME_BRACKETS[income_idx]
        monthly_income = int(np.random.randint(income_lo, income_hi + 1))

        region = REGION_VALUES[np.random.choice(len(REGION_VALUES), p=REGION_WEIGHTS)]
        device_type = DEVICE_VALUES[np.random.choice(len(DEVICE_VALUES), p=DEVICE_WEIGHTS)]

        trait_params = self._build_trait_params(income_enum, region, scenario_type)

        return AgentProfile(
            age=age,
            income_bracket=income_enum,
            monthly_income=monthly_income,
            region=region,
            device_type=device_type,
            digital_literacy=self._sample_beta(*trait_params["digital_literacy"]),
            price_sensitivity=self._sample_beta(*trait_params["price_sensitivity"]),
            patience_score=self._sample_beta(*trait_params["patience_score"]),
            motivation=self._sample_beta(*trait_params["motivation"]),
            trust_baseline=self._sample_beta(*trait_params["trust_baseline"]),
        )

    def generate_population(
        self,
        volume: int,
        env_params: dict[str, Any],
        scenario_type: str | None = None,
        seed: int | None = None,
    ) -> list[AgentProfile]:
        if seed is not None:
            np.random.seed(seed)

        profiles = [self.generate_one(env_params, scenario_type) for _ in range(volume)]

        logger.info(
            f"Generated population of {volume} agents "
            f"(scenario={scenario_type}, seed={seed})"
        )
        return profiles

    def population_summary(self, profiles: list[AgentProfile]) -> dict[str, Any]:
        n = len(profiles)
        if n == 0:
            return {}

        traits = [
            "digital_literacy",
            "price_sensitivity",
            "patience_score",
            "motivation",
            "trust_baseline",
        ]

        summary: dict[str, Any] = {"total": n}

        for t in traits:
            vals = [getattr(p, t) for p in profiles]
            summary[t] = {
                "mean": round(float(np.mean(vals)), 3),
                "median": round(float(np.median(vals)), 3),
                "std": round(float(np.std(vals)), 3),
                "p25": round(float(np.percentile(vals, 25)), 3),
                "p75": round(float(np.percentile(vals, 75)), 3),
            }

        summary["devices"] = {
            d.value: sum(1 for p in profiles if p.device_type == d) for d in DeviceType
        }
        summary["regions"] = {
            r.value: sum(1 for p in profiles if p.region == r) for r in Region
        }
        summary["income_brackets"] = {
            i.value: sum(1 for p in profiles if p.income_bracket == i)
            for i in IncomeBracket
        }

        converted_fraction = sum(
            1
            for p in profiles
            if p.income_bracket in (IncomeBracket.UPPER_MIDDLE, IncomeBracket.HIGH_INCOME)
        ) / n
        summary["estimated_high_income_fraction"] = round(converted_fraction, 3)

        return summary


# ================================================================
# QUICK SANITY CHECK
# python -m app.simulation.profiles
# ================================================================

if __name__ == "__main__":
    import json

    gen = AgentProfileGenerator()

    env = {
        "consumer_volume": 10000,
        "growth_rate_per_month": 8.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.55,
        "market_maturity": 0.3,
    }

    profile = gen.generate_one(env, scenario_type="EARLY_ADOPTER")
    print("--- Single agent profile ---")
    print(json.dumps(profile.to_dict(), indent=2))

    pop = gen.generate_population(1000, env, scenario_type=None, seed=42)
    summary = gen.population_summary(pop)
    print("\n--- Population summary (n=1000) ---")
    print(json.dumps(summary, indent=2))

    ps_mean = summary["price_sensitivity"]["mean"]
    dl_mean = summary["digital_literacy"]["mean"]
    print("\n--- Sanity checks ---")
    print(f"price_sensitivity mean: {ps_mean} (expected ~0.55-0.65)")
    print(f"digital_literacy  mean: {dl_mean} (expected ~0.60-0.72)")
    print(f"mobile device share: {summary['devices']['MOBILE']/1000:.1%} (expected ~75-82%)")
