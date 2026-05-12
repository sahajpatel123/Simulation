from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.models.outcome import Outcome
from app.simulation.markov import BASE_TRANSITIONS, State

logger = logging.getLogger(__name__)

MIN_OUTCOMES_FOR_CALIBRATION: int = 3
RECENT_WINDOW: int = 5
ADJUSTMENT_CAP: float = 0.08

CATEGORY_ACCURACY_WEIGHTS: dict[str, float] = {
    "conversion": 0.40,
    "revenue": 0.25,
    "retention": 0.20,
    "cac": 0.15,
}

CATEGORY_DIFFICULTY: dict[str, float] = {
    "conversion": 1.00,
    "revenue": 0.90,
    "retention": 0.75,
    "cac": 0.82,
}


@dataclass
class CategoryAccuracy:
    category: str
    accuracy_score: float
    sample_count: int
    mean_variance_pct: float
    bias_direction: str
    reliability: str


@dataclass
class MarkovAdjustment:
    from_state: str
    to_state: str
    current_val: float
    suggested_val: float
    delta: float
    rationale: str


@dataclass
class SamplingAdjustment:
    parameter: str
    current_val: float
    suggested_val: float
    delta: float
    rationale: str


@dataclass
class CalibrationMetrics:
    platform_accuracy: float
    total_outcomes: int
    total_projects_with_data: int
    maturity_score: float
    category_accuracy: list[CategoryAccuracy]
    calibration_trend: str
    trend_delta: float
    markov_adjustments: list[MarkovAdjustment]
    sampling_adjustments: list[SamplingAdjustment]
    last_computed_at: str
    data_sufficient: bool


class CalibrationEngine:
    def _outcome_accuracy(self, variance_pct: float | None) -> float | None:
        if variance_pct is None:
            return None
        abs_var = abs(variance_pct)
        return max(0.0, round(100.0 - abs_var * 2.0, 2))

    def _bias_direction(self, variance_values: list[float]) -> str:
        if not variance_values:
            return "NEUTRAL"
        mean_v = float(np.mean(variance_values))
        if mean_v > 5.0:
            return "UNDER_PREDICTED"
        if mean_v < -5.0:
            return "OVER_PREDICTED"
        return "NEUTRAL"

    def _reliability(self, sample_count: int, accuracy: float) -> str:
        if sample_count < MIN_OUTCOMES_FOR_CALIBRATION:
            return "INSUFFICIENT_DATA"
        if accuracy >= 75 and sample_count >= 10:
            return "HIGH"
        if accuracy >= 55 or sample_count >= 5:
            return "MEDIUM"
        return "LOW"

    def _category_accuracy(
        self,
        outcomes: list[Outcome],
        category: str,
        difficulty_key: str | None = None,
    ) -> CategoryAccuracy:
        """Generic accuracy computation for a given metric category."""
        difficulty = CATEGORY_DIFFICULTY.get(difficulty_key or category, 1.0)
        
        # Handle different outcome field structures
        if category == "conversion":
            variances = [
                o.variance_conversion for o in outcomes
                if o.variance_conversion is not None and o.calibration_score is not None
            ]
        elif category == "revenue":
            variances = [o.variance_mrr for o in outcomes if o.variance_mrr is not None]
        else:
            # For retention/cac, we use the calibration_score directly
            variances = [o.calibration_score for o in outcomes if o.calibration_score is not None]

        if not variances:
            return CategoryAccuracy(category, 0.0, 0, 0.0, "NEUTRAL", "INSUFFICIENT_DATA")

        if category in ("conversion", "revenue"):
            accuracies = [self._outcome_accuracy(v) for v in variances if v is not None]
            mean_acc = float(np.mean(accuracies)) if accuracies else 0.0
            mean_var = float(np.mean([abs(v) for v in variances if v is not None]))
            bias = self._bias_direction([v for v in variances if v is not None])
        else:
            mean_acc = float(np.mean(variances))
            mean_var = 0.0
            bias = "NEUTRAL"

        return CategoryAccuracy(
            category=category,
            accuracy_score=round(mean_acc * difficulty, 2),
            sample_count=len(variances),
            mean_variance_pct=round(mean_var, 2),
            bias_direction=bias,
            reliability=self._reliability(len(variances), mean_acc),
        )

    def _trend(self, outcomes: list[Outcome]) -> tuple[str, float]:
        scores = [o.calibration_score for o in outcomes if o.calibration_score is not None]
        if len(scores) < MIN_OUTCOMES_FOR_CALIBRATION:
            return "INSUFFICIENT_DATA", 0.0

        overall_avg = float(np.mean(scores))
        recent = scores[:RECENT_WINDOW]
        recent_avg = float(np.mean(recent))
        delta = round(recent_avg - overall_avg, 2)

        if delta > 4.0:
            return "IMPROVING", delta
        if delta < -4.0:
            return "DEGRADING", delta
        return "STABLE", delta

    def _weighted_platform_accuracy(self, categories: list[CategoryAccuracy]) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        for category in categories:
            if category.reliability == "INSUFFICIENT_DATA":
                continue
            weight = CATEGORY_ACCURACY_WEIGHTS.get(category.category, 0.1)
            weighted_sum += category.accuracy_score * weight
            total_weight += weight

        if total_weight == 0.0:
            return 0.0
        return round(weighted_sum / total_weight, 2)

    def _maturity_score(self, total_outcomes: int) -> float:
        if total_outcomes == 0:
            return 0.0
        return round(min(100.0, 20.0 * np.log1p(total_outcomes / 3.0)), 1)

    def _compute_markov_adjustments(
        self,
        categories: list[CategoryAccuracy],
        outcomes: list[Outcome],
    ) -> list[MarkovAdjustment]:
        _ = outcomes
        adjustments: list[MarkovAdjustment] = []

        conv_cat = next((c for c in categories if c.category == "conversion"), None)
        if conv_cat and conv_cat.reliability != "INSUFFICIENT_DATA":
            current = BASE_TRANSITIONS.get(State.DECIDE, {}).get(State.PURCHASE, 0.31)
            if conv_cat.bias_direction == "OVER_PREDICTED":
                delta = -min(ADJUSTMENT_CAP, conv_cat.mean_variance_pct * 0.001)
            elif conv_cat.bias_direction == "UNDER_PREDICTED":
                delta = min(ADJUSTMENT_CAP, conv_cat.mean_variance_pct * 0.001)
            else:
                delta = 0.0

            if abs(delta) > 0.001:
                adjustments.append(
                    MarkovAdjustment(
                        from_state="DECIDE",
                        to_state="PURCHASE",
                        current_val=round(current, 4),
                        suggested_val=round(float(np.clip(current + delta, 0.05, 0.60)), 4),
                        delta=round(delta, 4),
                        rationale=(
                            f"Conversion {conv_cat.bias_direction.lower().replace('_', ' ')} "
                            f"by mean {conv_cat.mean_variance_pct:.1f}% across "
                            f"{conv_cat.sample_count} outcomes."
                        ),
                    )
                )

        ret_cat = next((c for c in categories if c.category == "retention"), None)
        if ret_cat and ret_cat.accuracy_score < 60:
            current = BASE_TRANSITIONS.get(State.PURCHASE, {}).get(State.RETURN, 0.28)
            delta = 0.02
            adjustments.append(
                MarkovAdjustment(
                    from_state="PURCHASE",
                    to_state="RETURN",
                    current_val=round(current, 4),
                    suggested_val=round(float(np.clip(current + delta, 0.10, 0.60)), 4),
                    delta=round(delta, 4),
                    rationale=(
                        f"Retention accuracy is {ret_cat.accuracy_score:.0f}/100 — "
                        "increasing post-purchase return probability to compensate."
                    ),
                )
            )

        return adjustments

    def _compute_sampling_adjustments(
        self,
        platform_accuracy: float,
        categories: list[CategoryAccuracy],
    ) -> list[SamplingAdjustment]:
        _ = categories
        adjustments: list[SamplingAdjustment] = []

        base_mean_current = 0.035
        accuracy_delta = (platform_accuracy - 75.0) * 0.0008
        suggested_mean = float(np.clip(base_mean_current + accuracy_delta, 0.01, 0.12))
        if abs(suggested_mean - base_mean_current) > 0.001:
            adjustments.append(
                SamplingAdjustment(
                    parameter="base_conversion_mean",
                    current_val=base_mean_current,
                    suggested_val=round(suggested_mean, 4),
                    delta=round(suggested_mean - base_mean_current, 4),
                    rationale=(
                        f"Platform accuracy is {platform_accuracy:.0f}/100. "
                        f"{'Raising' if suggested_mean > base_mean_current else 'Lowering'} "
                        "base conversion mean to reduce systematic bias."
                    ),
                )
            )

        ps_var_current = 0.08
        ps_var_delta = (100.0 - platform_accuracy) * 0.001
        suggested_ps = float(np.clip(ps_var_current + ps_var_delta, 0.04, 0.18))
        if abs(suggested_ps - ps_var_current) > 0.002:
            adjustments.append(
                SamplingAdjustment(
                    parameter="price_sensitivity_variance",
                    current_val=ps_var_current,
                    suggested_val=round(suggested_ps, 4),
                    delta=round(suggested_ps - ps_var_current, 4),
                    rationale=(
                        f"Accuracy gap of {100 - platform_accuracy:.0f}% indicates "
                        "price sensitivity sampling may need wider variance."
                    ),
                )
            )

        return adjustments

    def calculate_platform_accuracy(self, db: Session) -> CalibrationMetrics:
        outcomes = db.query(Outcome).order_by(Outcome.created_at.desc()).all()
        total = len(outcomes)
        total_projects = len(set(o.project_id for o in outcomes))

        if total < MIN_OUTCOMES_FOR_CALIBRATION:
            return CalibrationMetrics(
                platform_accuracy=0.0,
                total_outcomes=total,
                total_projects_with_data=total_projects,
                maturity_score=self._maturity_score(total),
                category_accuracy=[],
                calibration_trend="INSUFFICIENT_DATA",
                trend_delta=0.0,
                markov_adjustments=[],
                sampling_adjustments=[],
                last_computed_at=datetime.now(timezone.utc).isoformat(),
                data_sufficient=False,
            )

        categories = [
            self._category_accuracy(outcomes, "conversion"),
            self._category_accuracy(outcomes, "revenue"),
            self._category_accuracy(outcomes, "retention"),
            self._category_accuracy(outcomes, "cac"),
        ]

        platform_accuracy = self._weighted_platform_accuracy(categories)
        maturity = self._maturity_score(total)
        trend, delta = self._trend(outcomes)
        markov_adj = self._compute_markov_adjustments(categories, outcomes)
        sampling_adj = self._compute_sampling_adjustments(platform_accuracy, categories)

        logger.info(
            "[Calibration] Computed — outcomes=%s accuracy=%.1f maturity=%.1f trend=%s",
            total,
            platform_accuracy,
            maturity,
            trend,
        )

        return CalibrationMetrics(
            platform_accuracy=platform_accuracy,
            total_outcomes=total,
            total_projects_with_data=total_projects,
            maturity_score=maturity,
            category_accuracy=categories,
            calibration_trend=trend,
            trend_delta=delta,
            markov_adjustments=markov_adj,
            sampling_adjustments=sampling_adj,
            last_computed_at=datetime.now(timezone.utc).isoformat(),
            data_sufficient=True,
        )

    def update_markov_priors(self, db: Session) -> CalibrationMetrics:
        metrics = self.calculate_platform_accuracy(db)

        if not metrics.data_sufficient:
            logger.info("[Calibration] Insufficient data — skipping prior update")
            return metrics

        for adjustment in metrics.markov_adjustments:
            try:
                from_state = State(adjustment.from_state)
                to_state = State(adjustment.to_state)
                if from_state in BASE_TRANSITIONS and to_state in BASE_TRANSITIONS[from_state]:
                    old_val = BASE_TRANSITIONS[from_state][to_state]
                    BASE_TRANSITIONS[from_state][to_state] = adjustment.suggested_val
                    logger.info(
                        "[Calibration] Markov updated — %s→%s: %.4f → %.4f (Δ%+.4f)",
                        adjustment.from_state,
                        adjustment.to_state,
                        old_val,
                        adjustment.suggested_val,
                        adjustment.delta,
                    )
            except Exception as exc:
                logger.warning("[Calibration] Could not apply Markov adjustment: %s", exc)

        logger.info(
            "[Calibration] Prior update complete — applied %s Markov adjustments",
            len(metrics.markov_adjustments),
        )
        return metrics
