from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ================================================================
# STATE DEFINITIONS
# Ordered intentionally - index position matters for the matrix.
# Terminal states (PURCHASE, ABANDON) have no outgoing transitions
# to non-terminal states except RETURN which re-enters the funnel.
# ================================================================


class State(str, Enum):
    ARRIVE = "ARRIVE"
    BROWSE = "BROWSE"
    CONSIDER = "CONSIDER"
    DECIDE = "DECIDE"
    PURCHASE = "PURCHASE"
    ABANDON = "ABANDON"
    RETURN = "RETURN"


STATES: list[State] = list(State)
STATE_INDEX: dict[State, int] = {s: i for i, s in enumerate(STATES)}

# ================================================================
# BASE TRANSITION MATRIX
# Derived from 2024-2026 SaaS + D2C e-commerce benchmarks.
# Row = from state. Column = to state.
# Rows must sum to 1.0 after normalisation (handled in code).
# Zeros mean the transition is structurally impossible.
# PURCHASE and ABANDON are absorbing states within a single visit -
# only RETURN re-enters the funnel.
# ================================================================

BASE_TRANSITIONS: dict[State, dict[State, float]] = {
    State.ARRIVE: {
        State.BROWSE: 0.87,
        State.ABANDON: 0.13,
    },
    State.BROWSE: {
        State.CONSIDER: 0.62,
        State.ABANDON: 0.38,
    },
    State.CONSIDER: {
        State.DECIDE: 0.46,
        State.BROWSE: 0.16,
        State.ABANDON: 0.38,
    },
    State.DECIDE: {
        State.PURCHASE: 0.31,
        State.CONSIDER: 0.14,
        State.ABANDON: 0.55,
    },
    State.PURCHASE: {
        State.RETURN: 0.28,
        State.ABANDON: 0.72,
    },
    State.ABANDON: {
        State.RETURN: 0.19,
        State.ARRIVE: 0.81,
    },
    State.RETURN: {
        State.BROWSE: 0.58,
        State.CONSIDER: 0.22,
        State.ABANDON: 0.20,
    },
}

# ================================================================
# ASSUMPTION ADJUSTMENT RULES
# Maps assumption text keywords -> which transition pair to adjust.
# Each rule: (from_state, to_state, direction)
# direction: -1 = reduce probability, +1 = increase probability
# Magnitude is scaled by (sensitivity_weight * impact_score).
# ================================================================

SENSITIVITY_WEIGHTS: dict[str, float] = {
    "CRITICAL": 0.38,
    "HIGH": 0.22,
    "MEDIUM": 0.12,
    "LOW": 0.04,
}

KEYWORD_RULES: list[dict[str, Any]] = [
    {
        "keywords": ["pric", "cost", "fee", "₹", "afford", "expensive", "cheap"],
        "transitions": [
            (State.DECIDE, State.PURCHASE, -1),
            (State.CONSIDER, State.DECIDE, -1),
        ],
    },
    {
        "keywords": ["trust", "credib", "review", "testimonial", "brand", "scam"],
        "transitions": [
            (State.BROWSE, State.CONSIDER, -1),
            (State.CONSIDER, State.DECIDE, -1),
        ],
    },
    {
        "keywords": ["retention", "return", "churn", "loyal", "repeat", "habit"],
        "transitions": [
            (State.PURCHASE, State.RETURN, +1),
            (State.ABANDON, State.RETURN, +1),
        ],
    },
    {
        "keywords": ["word", "referral", "viral", "organic", "cac", "acquisition"],
        "transitions": [
            (State.ARRIVE, State.BROWSE, -1),
        ],
    },
    {
        "keywords": ["ux", "ui", "usab", "confus", "complex", "onboard", "friction"],
        "transitions": [
            (State.BROWSE, State.CONSIDER, -1),
            (State.CONSIDER, State.ABANDON, +1),
        ],
    },
    {
        "keywords": ["market", "demand", "need", "problem", "pain", "fit"],
        "transitions": [
            (State.ARRIVE, State.BROWSE, +1),
            (State.CONSIDER, State.DECIDE, +1),
        ],
    },
    {
        "keywords": ["compet", "alternat", "rival", "substitut"],
        "transitions": [
            (State.CONSIDER, State.ABANDON, +1),
            (State.DECIDE, State.ABANDON, +1),
        ],
    },
]


class MarkovBehaviourModel:
    """
    Pure stochastic behavioural engine.
    No database calls. No LLM calls. No side effects.
    Fully reproducible when seeded.

    Usage:
        model = MarkovBehaviourModel()
        matrix = model.build_transition_matrix(env_params, assumptions)
        result = model.run_chain(agent_profile, matrix)
    """

    def build_transition_matrix(
        self,
        env_params: dict[str, Any],
        assumptions: list[dict[str, Any]],
        seed: int | None = None,
    ) -> np.ndarray:
        """
        Constructs a (7 x 7) row-stochastic transition matrix.
        """
        if seed is not None:
            np.random.seed(seed)

        n = len(STATES)
        matrix = np.zeros((n, n), dtype=np.float64)

        for from_state, transitions in BASE_TRANSITIONS.items():
            fi = STATE_INDEX[from_state]
            for to_state, prob in transitions.items():
                ti = STATE_INDEX[to_state]
                matrix[fi, ti] = prob

        for assumption in assumptions:
            text = assumption.get("text", "").lower()
            sensitivity = assumption.get("sensitivity", "MEDIUM")
            impact = float(assumption.get("impact_score", 5.0)) / 10.0
            weight = SENSITIVITY_WEIGHTS.get(sensitivity, 0.12)
            magnitude = weight * impact

            for rule in KEYWORD_RULES:
                if any(kw in text for kw in rule["keywords"]):
                    for from_s, to_s, direction in rule["transitions"]:
                        fi = STATE_INDEX[from_s]
                        ti = STATE_INDEX[to_s]
                        matrix[fi, ti] = np.clip(
                            matrix[fi, ti] + direction * magnitude,
                            0.0,
                            1.0,
                        )
                    break

        price_sensitivity = float(env_params.get("price_sensitivity", 0.5))
        market_maturity = float(env_params.get("market_maturity", 0.3))

        decide_idx = STATE_INDEX[State.DECIDE]
        purchase_idx = STATE_INDEX[State.PURCHASE]
        abandon_idx = STATE_INDEX[State.ABANDON]
        matrix[decide_idx, purchase_idx] = np.clip(
            matrix[decide_idx, purchase_idx] - price_sensitivity * 0.18,
            0.05,
            1.0,
        )

        browse_idx = STATE_INDEX[State.BROWSE]
        consider_idx = STATE_INDEX[State.CONSIDER]
        matrix[browse_idx, consider_idx] = np.clip(
            matrix[browse_idx, consider_idx] - market_maturity * 0.14,
            0.10,
            1.0,
        )

        matrix = np.clip(matrix, 0.0, 1.0)

        row_sums = matrix.sum(axis=1, keepdims=True)
        zero_rows = row_sums.flatten() == 0.0
        for ri in np.where(zero_rows)[0]:
            matrix[ri, abandon_idx] = 1.0
            row_sums[ri, 0] = 1.0
        matrix = matrix / row_sums

        return matrix

    def run_chain(
        self,
        agent_profile: dict[str, Any],
        transition_matrix: np.ndarray,
        max_steps: int = 20,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """
        Simulates one agent traversing the funnel.
        """
        if seed is not None:
            np.random.seed(seed)

        patience = float(agent_profile.get("patience_score", 0.5))
        literacy = float(agent_profile.get("digital_literacy", 0.5))
        agent_price_sens = float(agent_profile.get("price_sensitivity", 0.5))

        effective_max = max(5, int(max_steps * (0.5 + patience)))

        current_idx = STATE_INDEX[State.ARRIVE]
        path: list[str] = [STATES[current_idx].value]
        time_per_state: dict[str, float] = {s.value: 0.0 for s in STATES}
        steps_taken = 0

        base_times: dict[State, tuple[float, float]] = {
            State.ARRIVE: (4.0, 2.0),
            State.BROWSE: (38.0, 14.0),
            State.CONSIDER: (52.0, 18.0),
            State.DECIDE: (24.0, 10.0),
            State.PURCHASE: (35.0, 12.0),
            State.ABANDON: (2.0, 1.0),
            State.RETURN: (18.0, 8.0),
        }

        for _ in range(effective_max):
            state = STATES[current_idx]

            mu, sigma = base_times.get(state, (10.0, 5.0))
            literacy_factor = 0.6 + (1.0 - literacy) * 0.8
            time_s = max(1.0, np.random.normal(mu * literacy_factor, sigma))
            time_per_state[state.value] += round(time_s, 1)

            steps_taken += 1

            if state == State.DECIDE and np.random.random() < agent_price_sens * 0.4:
                current_idx = STATE_INDEX[State.ABANDON]
                path.append(State.ABANDON.value)
                break

            probs = transition_matrix[current_idx]
            prob_sum = probs.sum()
            if prob_sum <= 0.0:
                current_idx = STATE_INDEX[State.ABANDON]
                path.append(State.ABANDON.value)
                break
            probs = probs / prob_sum

            next_idx = int(np.random.choice(len(STATES), p=probs))
            current_idx = next_idx
            path.append(STATES[current_idx].value)

            if STATES[current_idx] in (State.PURCHASE, State.ABANDON):
                break

        final_state = STATES[current_idx]

        return {
            "final_state": final_state.value,
            "converted": final_state == State.PURCHASE,
            "path": path,
            "steps": steps_taken,
            "time_per_state": time_per_state,
            "total_time_seconds": round(sum(time_per_state.values()), 1),
        }

    def run_batch(
        self,
        agents: list[dict[str, Any]],
        transition_matrix: np.ndarray,
        base_seed: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Runs a batch of agents through the chain.
        Each agent gets a unique but deterministic seed derived from base_seed.
        """
        results = []
        for i, agent in enumerate(agents):
            seed = (base_seed + i) if base_seed is not None else None
            results.append(self.run_chain(agent, transition_matrix, seed=seed))
        return results


# ================================================================
# QUICK SANITY CHECK - run directly to verify the model works
# python -m app.simulation.markov
# ================================================================

if __name__ == "__main__":
    import json

    model = MarkovBehaviourModel()

    env = {
        "consumer_volume": 10000,
        "growth_rate_per_month": 8.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.55,
        "market_maturity": 0.3,
    }

    assumptions = [
        {
            "text": "users will pay ₹999 without a trial",
            "sensitivity": "CRITICAL",
            "impact_score": 9.1,
        },
        {
            "text": "word-of-mouth will drive growth",
            "sensitivity": "HIGH",
            "impact_score": 7.5,
        },
        {
            "text": "retention will be strong",
            "sensitivity": "MEDIUM",
            "impact_score": 6.0,
        },
    ]

    matrix = model.build_transition_matrix(env, assumptions, seed=42)

    print("--- Transition Matrix ---")
    print(f"{'':12}", end="")
    for s in STATES:
        print(f"{s.value[:7]:>8}", end="")
    print()
    for i, row in enumerate(matrix):
        print(f"{STATES[i].value:<12}", end="")
        for val in row:
            print(f"{val:>8.3f}", end="")
        print()

    print("\n--- Row sums (must all be 1.0) ---")
    print(matrix.sum(axis=1))

    agent = {
        "patience_score": 0.6,
        "digital_literacy": 0.5,
        "price_sensitivity": 0.55,
    }

    result = model.run_chain(agent, matrix, seed=99)
    print("\n--- Single agent result ---")
    print(json.dumps(result, indent=2))

    agents = [
        {"patience_score": 0.3, "digital_literacy": 0.4, "price_sensitivity": 0.8},
        {"patience_score": 0.7, "digital_literacy": 0.7, "price_sensitivity": 0.2},
        {"patience_score": 0.5, "digital_literacy": 0.5, "price_sensitivity": 0.5},
    ]
    batch = model.run_batch(agents, matrix, base_seed=0)
    conversions = sum(1 for r in batch if r["converted"])
    print(f"\n--- Batch of {len(batch)} agents ---")
    print(f"Conversions: {conversions}/{len(batch)}")
    for r in batch:
        print(f"  {r['final_state']:<10} path={' -> '.join(r['path'])}")
