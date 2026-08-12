from __future__ import annotations

import json
import math
from collections import defaultdict
from statistics import mean

from sqlalchemy import text

from app.simulation.correction_application import (
    MAX_CORRECTION_SCALAR,
    MIN_CORRECTION_SCALAR,
)
from app.simulation.funnel_stage_calibration import (
    CLUSTER_ALL,
    MAX_OUTCOMES,
    SCOPE_GLOBAL,
    compute_stage_corrections,
    predicted_drop_rates_from_results,
)

ALL_ARCHITECT_NAMES = [
    "AccessibilityInclusionArchitect",
    "MarketTimingArchitect",
    "CompetitiveDynamicsArchitect",
    "TrustArchitect",
    "PricingArchitect",
    "PaymentFrictionArchitect",
    "OnboardingArchitect",
    "FeatureAdoptionArchitect",
    "RetentionArchitect",
    "SupportFrictionArchitect",
    "ViralityArchitect",
    "MacroeconomicArchitect",
    "DemographicInteractionArchitect",
    "MarketplaceLiquidityArchitect",
    "AssumptionCascadeArchitect",
    "PurchaseDecisionArchitect",
    "PhysicalSensoryArchitect",
    "PerformanceThresholdArchitect",
    "SetupFirstUseArchitect",
    "EcosystemCompatibilityArchitect",
    "DistributionChannelArchitect",
    "AftersalesLifecycleArchitect",
    "HealthSafetyHardwareArchitect",
    "SustainabilityArchitect",
    "RegulatoryComplianceArchitect",
    "EnterpriseProcurementArchitect",
    "PlatformDependencyArchitect",
    "SupplyChainArchitect",
    "RunwayArchitect",
    "MessagingClarityArchitect",
    "FounderExecutionArchitect",
    "AISkepticismArchitect",
    "BehavioralEconomicsArchitect",
    "IntegrationFrictionArchitect",
]

# Layer 5 gate: a cluster must accumulate at least this many validated,
# learning-weighted outcomes before the Bayesian trait update may move its
# ``cluster_parameters.calibrated_value``. Kept as a module constant so the
# API trigger and the engine itself share one threshold.
CLUSTER_TRAIT_CALIBRATION_MIN_EFF_COUNT: float = 5.0

# Postgres advisory-lock key used to serialize Layer 5 runs. The weekly
# beat and the outcome-feedback trigger can overlap in the Celery pool;
# the lock makes the watermark read + trait writes one atomic window so
# two workers can never consume the same outcome evidence twice.
CLUSTER_TRAIT_CALIBRATION_LOCK_KEY: int = 735001


def _predicted_conversion(results: dict) -> float:
    return float(
        results.get("mean_conversion_rate")
        or results.get("conversion_rate")
        or results.get("population_weighted_conversion")
        or 0
    )


def _calibration_scalar(wmean: float) -> float:
    """Turn a signed mean error into a multiplicative correction scalar.

    ``wmean`` is ``actual - predicted``: a positive error means founders
    beat the model, so future probabilities must be raised (scalar > 1.0);
    a negative error means the model over-predicted, so future
    probabilities must be lowered (scalar < 1.0). The scalar is the
    reciprocal of ``1 - wmean`` and is clamped to the same safe bounds the
    Conductor enforces when it reads correction rows, so an extreme or
    malformed bias can never distort the funnel.
    """
    if not math.isfinite(wmean):
        return 1.0
    denominator = 1.0 - wmean
    if denominator <= 0.0:
        return MAX_CORRECTION_SCALAR
    return max(
        MIN_CORRECTION_SCALAR,
        min(MAX_CORRECTION_SCALAR, 1.0 / denominator),
    )


def _is_finite_number(value: object) -> bool:
    """Return True when ``value`` casts to a finite float.

    Guards Layer 5 against a single malformed cluster summary (NULL or
    non-numeric ``conversion_rate``) aborting the whole calibration batch.
    """
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class CalibrationEngine:
    # ── LAYER 1: PLAUSIBILITY VALIDATION ──

    def validate_outcome(self, outcome, simulation, db) -> bool:
        results = simulation.results_json or {}
        if isinstance(results, str):
            results = json.loads(results)
        predicted = _predicted_conversion(results)
        actual = outcome.actual_conversion_rate

        if outcome.product_changed_since_sim:
            db.execute(
                text("UPDATE founder_outcomes SET learning_weight=0.0 WHERE id=:id"),
                {"id": outcome.id},
            )
            db.commit()
            return False

        if predicted > 0.10 and actual > predicted * 3.0:
            db.execute(
                text("UPDATE founder_outcomes SET validated=false WHERE id=:id"),
                {"id": outcome.id},
            )
            db.commit()
            return False
        if predicted > 0.10 and actual <= predicted * 0.10:
            db.execute(
                text("UPDATE founder_outcomes SET validated=false WHERE id=:id"),
                {"id": outcome.id},
            )
            db.commit()
            return False

        conf_weights = {"EXACT": 1.0, "ESTIMATED": 0.6, "ROUGH": 0.3}
        sig_q = float(simulation.signal_quality or 0.0)
        conf_w = conf_weights.get(outcome.data_confidence, 0.3)

        if sig_q >= 0.50:
            lw = sig_q * conf_w
        elif sig_q >= 0.25:
            lw = sig_q * 0.5 * conf_w
        else:
            lw = 0.0

        db.execute(
            text(
                "UPDATE founder_outcomes SET validated=true, learning_weight=:lw WHERE id=:id"
            ),
            {"lw": lw, "id": outcome.id},
        )
        db.commit()
        return lw > 0.0

    # ── LAYER 2: SYSTEMATIC BIAS (weekly, eff_count >= 10) ──

    def update_systematic_bias(self, product_type: str, db) -> None:
        rows = db.execute(
            text("""
            SELECT fo.actual_conversion_rate, fo.learning_weight,
                   s.results_json
            FROM founder_outcomes fo
            JOIN simulations s ON s.id = fo.simulation_id
            WHERE fo.validated = true
              AND fo.learning_weight > 0
              AND s.results_json->>'product_type_detected' = :pt
        """),
            {"pt": product_type},
        ).fetchall()

        if not rows:
            return
        eff_count = sum(float(r.learning_weight) for r in rows)
        if eff_count < 10:
            return

        errors = []
        weights = []
        for r in rows:
            res = r.results_json if isinstance(r.results_json, dict) else json.loads(
                r.results_json or "{}"
            )
            predicted = _predicted_conversion(res)
            if predicted == 0:
                continue
            errors.append(float(r.actual_conversion_rate) - predicted)
            weights.append(float(r.learning_weight))

        if not errors:
            return
        w_sum = sum(weights) or 1.0
        wmean = sum(e * w for e, w in zip(errors, weights)) / w_sum

        if abs(wmean) > 0.03:
            scalar = _calibration_scalar(wmean)
            conf = min(1.0, eff_count / (eff_count + 30))
            for arch_name in ALL_ARCHITECT_NAMES:
                self._upsert_correction(
                    db, arch_name, product_type, "ALL", "ALL",
                    scalar, conf, eff_count, "CATEGORY_GLOBAL",
                )

    # ── LAYER 3: STRUCTURAL PATTERNS (monthly, eff_count >= 30) ──

    def update_structural_patterns(self, db) -> None:
        rows = db.execute(
            text("""
            SELECT crs.cluster_id, crs.primary_drop_trigger,
                   crs.conversion_rate, crs.signal_quality, crs.product_type,
                   fo.actual_conversion_rate, fo.learning_weight
            FROM cluster_run_summaries crs
            JOIN founder_outcomes fo ON fo.simulation_id = crs.simulation_id
            WHERE fo.validated = true AND fo.learning_weight > 0
        """)
        ).fetchall()

        groups: dict[tuple[str, str, str], list] = defaultdict(list)
        for r in rows:
            key = (r.primary_drop_trigger or "unknown", r.product_type or "saas", r.cluster_id)
            groups[key].append(r)

        for (arch_name, product_type, cluster_id), group in groups.items():
            eff_count = sum(float(r.learning_weight) for r in group)
            if eff_count < 30:
                continue
            w_sum = sum(float(r.learning_weight) for r in group) or 1.0
            errors = [
                (float(r.actual_conversion_rate) - float(r.conversion_rate))
                * float(r.learning_weight)
                for r in group
            ]
            wmean = sum(errors) / w_sum
            if abs(wmean) < 0.05:
                continue
            scalar = _calibration_scalar(wmean)
            conf_w = eff_count / (eff_count + 30)
            self._upsert_correction(
                db,
                arch_name,
                product_type,
                "detected",
                cluster_id,
                scalar,
                conf_w,
                eff_count,
                "CATEGORY_GLOBAL",
            )

    # ── LAYER 4: USER CLAIM ACCURACY (per-user, sample >= 3) ──

    def update_user_accuracy_profile(self, user_id: int, outcome, simulation, db) -> None:
        if not outcome.validated or outcome.learning_weight == 0.0:
            return

        results = simulation.results_json or {}
        if isinstance(results, str):
            results = json.loads(results)
        predicted_overall = _predicted_conversion(results)
        actual_overall = float(outcome.actual_conversion_rate)

        summaries = db.execute(
            text(
                "SELECT primary_drop_trigger, conversion_rate FROM cluster_run_summaries "
                "WHERE simulation_id=:sid"
            ),
            {"sid": simulation.id},
        ).fetchall()

        ALPHA = 0.35
        for s in summaries:
            trigger = s.primary_drop_trigger
            if not trigger:
                continue
            gap = float(s.conversion_rate) - actual_overall

            existing = db.execute(
                text(
                    "SELECT id, ema_delta, sample_count FROM user_claim_accuracy_profiles "
                    "WHERE user_id=:uid AND architect_name=:an"
                ),
                {"uid": user_id, "an": trigger},
            ).fetchone()

            if existing:
                new_ema = ALPHA * gap + (1 - ALPHA) * float(existing.ema_delta)
                new_count = int(existing.sample_count) + 1
                history = db.execute(
                    text("""
                    SELECT ema_delta FROM user_claim_accuracy_profiles
                    WHERE user_id=:uid AND architect_name=:an
                """),
                    {"uid": user_id, "an": trigger},
                ).fetchall()
                consistent = sum(1 for h in history if h.ema_delta > 0) / max(len(history), 1)
                reliability = abs(consistent - 0.5) * 2.0
                db.execute(
                    text("""
                    UPDATE user_claim_accuracy_profiles
                    SET ema_delta=:ema, sample_count=:sc, reliability_score=:rel, last_updated=NOW()
                    WHERE id=:id
                """),
                    {"ema": new_ema, "sc": new_count, "rel": reliability, "id": existing.id},
                )
            else:
                db.execute(
                    text("""
                    INSERT INTO user_claim_accuracy_profiles
                    (user_id, architect_name, ema_delta, reliability_score, sample_count, last_updated)
                    VALUES (:uid, :an, :ema, 0.0, 1, NOW())
                """),
                    {"uid": user_id, "an": trigger, "ema": ALPHA * gap},
                )

        gap = abs(predicted_overall - actual_overall)
        trend = self._compute_trend(user_id, db)
        db.execute(
            text("""
            INSERT INTO user_simulation_accuracy_history
            (user_id, simulation_id, predicted_conversion, actual_conversion,
             absolute_gap, signal_quality_at_run, accuracy_trend, created_at)
            VALUES (:uid,:sid,:pred,:act,:gap,:sq,:trend,NOW())
        """),
            {
                "uid": user_id,
                "sid": simulation.id,
                "pred": predicted_overall,
                "act": actual_overall,
                "gap": gap,
                "sq": float(simulation.signal_quality or 0),
                "trend": trend,
            },
        )
        db.commit()

    def _compute_trend(self, user_id: int, db) -> str:
        rows = db.execute(
            text("""
            SELECT absolute_gap, signal_quality_at_run
            FROM user_simulation_accuracy_history
            WHERE user_id=:uid ORDER BY created_at ASC
        """),
            {"uid": user_id},
        ).fetchall()
        if len(rows) < 4:
            return "INSUFFICIENT_DATA"
        valid = [r for r in rows if float(r.signal_quality_at_run) >= 0.50]
        if len(valid) < 3:
            return "INSUFFICIENT_QUALITY_DATA"
        mid = len(valid) // 2
        early = mean(float(r.absolute_gap) for r in valid[:mid])
        late = mean(float(r.absolute_gap) for r in valid[mid:])
        imp = (early - late) / (early + 0.001)
        if imp > 0.20:
            return "IMPROVING"
        if imp < -0.10:
            return "DEGRADING"
        return "STABLE"

    # ── LAYER 5: CLUSTER TRAIT CALIBRATION (Bayesian, eff_count >= 5) ──

    def clusters_ready_for_trait_calibration(self, db) -> bool:
        """Return True when at least one cluster crossed the Layer 5 gate.

        Mirrors the exact join / grouping used by
        :meth:`update_cluster_trait_calibration` so the API only enqueues
        the Celery task once there is enough validated, learning-weighted
        ground truth to learn from. Outcomes already consumed by a previous
        run (recorded in ``cluster_trait_calibration_state``) are excluded,
        so the gate does not stay hot forever after one successful run.
        """
        row = db.execute(
            text("""
                SELECT COUNT(*)::int AS ready
                FROM (
                    SELECT crs.cluster_id
                    FROM cluster_run_summaries crs
                    JOIN founder_outcomes fo ON fo.simulation_id = crs.simulation_id
                    LEFT JOIN cluster_trait_calibration_state st
                           ON st.cluster_id = crs.cluster_id
                    WHERE fo.validated = true
                      AND fo.learning_weight > 0
                      AND fo.id > COALESCE(st.last_processed_outcome_id, 0)
                    GROUP BY crs.cluster_id
                    HAVING SUM(fo.learning_weight) >= :min_eff
                ) ready_clusters
            """),
            {"min_eff": CLUSTER_TRAIT_CALIBRATION_MIN_EFF_COUNT},
        ).fetchone()
        return bool(row and int(row.ready or 0) > 0)

    def update_cluster_trait_calibration(self, db) -> None:
        # Serialize concurrent weekly-beat / outcome-triggered runs. The
        # advisory lock is transaction-scoped and released on commit/close.
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": CLUSTER_TRAIT_CALIBRATION_LOCK_KEY},
        )

        rows = db.execute(
            text("""
            SELECT crs.cluster_id, crs.conversion_rate,
                   fo.actual_conversion_rate, fo.learning_weight, fo.id AS outcome_id
            FROM cluster_run_summaries crs
            JOIN founder_outcomes fo ON fo.simulation_id = crs.simulation_id
            LEFT JOIN cluster_trait_calibration_state st
                   ON st.cluster_id = crs.cluster_id
            WHERE fo.validated = true
              AND fo.learning_weight > 0
              AND fo.id > COALESCE(st.last_processed_outcome_id, 0)
        """)
        ).fetchall()

        if not rows:
            # Nothing new to learn; leave the watermark and calibration
            # counters untouched so re-runs stay true no-ops.
            return

        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(r.cluster_id, []).append(r)

        for cluster_id, group in groups.items():
            eff_count = sum(float(r.learning_weight) for r in group)
            if eff_count < CLUSTER_TRAIT_CALIBRATION_MIN_EFF_COUNT:
                # Keep this cluster's watermark where it is so older
                # sub-threshold outcomes accumulate toward the gate.
                continue

            # Drop malformed rows (NULL / non-numeric conversion rates) so
            # one bad summary cannot abort the batch. When every row in the
            # group is malformed we still advance the watermark so poisoned
            # evidence cannot wedge the pipeline forever.
            max_outcome_id = max(int(r.outcome_id) for r in group)
            valid = [
                r
                for r in group
                if _is_finite_number(r.conversion_rate)
                and _is_finite_number(r.actual_conversion_rate)
            ]
            if not valid:
                db.execute(
                    text("""
                        INSERT INTO cluster_trait_calibration_state
                            (cluster_id, last_processed_outcome_id, updated_at)
                        VALUES (:cid, :max_id, NOW())
                        ON CONFLICT (cluster_id) DO UPDATE SET
                            last_processed_outcome_id = EXCLUDED.last_processed_outcome_id,
                            updated_at = NOW()
                    """),
                    {"cid": cluster_id, "max_id": max_outcome_id},
                )
                continue

            errors = [
                float(r.actual_conversion_rate) - float(r.conversion_rate)
                for r in valid
            ]
            w_sum = sum(float(r.learning_weight) for r in valid) or 1.0
            wmean_error = sum(
                e * float(r.learning_weight) for e, r in zip(errors, valid)
            ) / w_sum

            direction = "price_sensitivity" if wmean_error < -0.02 else "digital_literacy"

            param = db.execute(
                text("""
                    SELECT cp.id, cp.base_value, cp.calibrated_value, cp.calibration_count
                    FROM cluster_parameters cp
                    WHERE cp.cluster_id = :cid AND cp.trait_name = :trait
                """),
                {"cid": cluster_id, "trait": direction},
            ).fetchone()
            if not param:
                continue

            count = int(param.calibration_count or 0)
            prior = float(param.calibrated_value)

            alpha = 1.0 / (count + 2.0)
            signal = prior + abs(wmean_error) * 0.3 if wmean_error < 0 else prior - abs(wmean_error) * 0.3
            clamped_signal = max(0.0, min(1.0, signal))
            new_val = prior * (1.0 - alpha) + clamped_signal * alpha
            new_val = round(max(0.01, min(0.99, new_val)), 4)

            db.execute(
                text("""
                    UPDATE cluster_parameters
                    SET calibrated_value = :val,
                        calibration_count = :cnt,
                        last_updated = NOW()
                    WHERE id = :pid
                """),
                {"val": new_val, "cnt": count + 1, "pid": int(param.id)},
            )

            db.execute(
                text("""
                    INSERT INTO cluster_trait_calibration_state
                        (cluster_id, last_processed_outcome_id, updated_at)
                    VALUES (:cid, :max_id, NOW())
                    ON CONFLICT (cluster_id) DO UPDATE SET
                        last_processed_outcome_id = EXCLUDED.last_processed_outcome_id,
                        updated_at = NOW()
                """),
                {"cid": cluster_id, "max_id": max_outcome_id},
            )
        db.commit()

    # ── LAYER 6: FUNNEL STAGE CALIBRATION (per-stage drop-off feedback) ──

    def funnel_stage_calibration_ready(self, db) -> bool:
        """Return True when any validated outcome carries per-stage drops."""
        row = db.execute(
            text("""
                SELECT COUNT(*)::int AS ready
                FROM founder_outcomes fo
                JOIN simulations s ON s.id = fo.simulation_id
                WHERE fo.validated = true
                  AND fo.learning_weight > 0
                  AND (fo.actual_drop_at_browse_pct IS NOT NULL
                       OR fo.actual_drop_at_consider_pct IS NOT NULL
                       OR fo.actual_drop_at_decide_pct IS NOT NULL)
            """)
        ).fetchone()
        return bool(row and int(row.ready or 0) > 0)

    def update_funnel_stage_calibration(self, db) -> None:
        """Learn per-stage pass-through corrections from founder outcomes.

        Layer 6 pairs the drop-off each validated outcome *reported* with
        the drop-off the outcome's simulation *predicted*, then upserts a
        learning-weighted pass-through scalar per (product type, stage) into
        ``funnel_stage_corrections``. The Conductor multiplies those scalars
        into the forward Markov transitions of future runs, so a stage the
        simulation consistently mis-predicts gets corrected instead of only
        being diagnosed.

        The update is idempotent (upsert) and deliberately bounded to the
        most recent :data:`MAX_OUTCOMES` rows so stale evidence cannot
        accumulate forever. A single commit at the end keeps the write batch
        atomic.
        """
        rows = db.execute(
            text("""
                SELECT fo.id AS outcome_id,
                       fo.actual_drop_at_browse_pct,
                       fo.actual_drop_at_consider_pct,
                       fo.actual_drop_at_decide_pct,
                       fo.learning_weight,
                       s.results_json
                FROM founder_outcomes fo
                JOIN simulations s ON s.id = fo.simulation_id
                WHERE fo.validated = true
                  AND fo.learning_weight > 0
                  AND (fo.actual_drop_at_browse_pct IS NOT NULL
                       OR fo.actual_drop_at_consider_pct IS NOT NULL
                       OR fo.actual_drop_at_decide_pct IS NOT NULL)
                ORDER BY fo.id DESC
                LIMIT :limit
            """),
            {"limit": MAX_OUTCOMES},
        ).mappings().all()

        if not rows:
            return

        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            raw_results = row.get("results_json")
            if isinstance(raw_results, str):
                try:
                    raw_results = json.loads(raw_results or "{}")
                except (ValueError, TypeError):
                    raw_results = None
            if not isinstance(raw_results, dict):
                continue
            product_type = str(raw_results.get("product_type_detected") or "saas")
            groups[product_type].append(
                {
                    "predicted_drop_rates": predicted_drop_rates_from_results(
                        raw_results
                    ),
                    "actual_drops": {
                        "BROWSE": row.get("actual_drop_at_browse_pct"),
                        "CONSIDER": row.get("actual_drop_at_consider_pct"),
                        "DECIDE": row.get("actual_drop_at_decide_pct"),
                    },
                    "learning_weight": row.get("learning_weight"),
                }
            )

        wrote_any = False
        for product_type, pairs in groups.items():
            for correction in compute_stage_corrections(
                pairs,
                product_type=product_type,
            ):
                self._upsert_funnel_stage_correction(db, correction)
                wrote_any = True

        if wrote_any:
            db.commit()

    def _upsert_funnel_stage_correction(
        self,
        db,
        correction: dict,
    ) -> None:
        """Upsert one learned stage correction (no commit — caller batches)."""
        db.execute(
            text("""
                INSERT INTO funnel_stage_corrections
                    (product_type, stage, cluster_id, from_state, to_state,
                     correction_scalar, confidence_weight,
                     effective_sample_count, sample_count, mean_bias,
                     scope, last_updated)
                VALUES
                    (:pt, :stage, :cluster_id, :from_state, :to_state,
                     :scalar, :confidence, :eff_count, :sample_count,
                     :mean_bias, :scope, NOW())
                ON CONFLICT (product_type, stage, cluster_id) DO UPDATE SET
                    from_state = EXCLUDED.from_state,
                    to_state = EXCLUDED.to_state,
                    correction_scalar = EXCLUDED.correction_scalar,
                    confidence_weight = EXCLUDED.confidence_weight,
                    effective_sample_count = EXCLUDED.effective_sample_count,
                    sample_count = EXCLUDED.sample_count,
                    mean_bias = EXCLUDED.mean_bias,
                    scope = EXCLUDED.scope,
                    last_updated = NOW()
            """),
            {
                "pt": correction["product_type"],
                "stage": correction["stage"],
                "cluster_id": CLUSTER_ALL,
                "from_state": correction["from_state"],
                "to_state": correction["to_state"],
                "scalar": correction["correction_scalar"],
                "confidence": correction["confidence_weight"],
                "eff_count": correction["effective_sample_count"],
                "sample_count": correction["sample_count"],
                "mean_bias": correction["mean_bias"],
                "scope": SCOPE_GLOBAL,
            },
        )

    def _upsert_correction(
        self,
        db,
        arch_name,
        product_type,
        product_attr,
        cluster_id,
        scalar,
        conf_weight,
        eff_count,
        scope,
    ) -> None:
        db.execute(
            text("""
            INSERT INTO architect_corrections
            (architect_name, product_type, product_attribute, cluster_id,
             correction_scalar, confidence_weight, effective_sample_count, scope, last_updated)
            VALUES (:an,:pt,:pa,:cid,:cs,:cw,:ec,:sc,NOW())
            ON CONFLICT (architect_name, product_type, product_attribute, cluster_id)
            DO UPDATE SET
              correction_scalar     = EXCLUDED.correction_scalar,
              confidence_weight     = EXCLUDED.confidence_weight,
              effective_sample_count= EXCLUDED.effective_sample_count,
              last_updated          = NOW()
        """),
            {
                "an": arch_name,
                "pt": product_type,
                "pa": product_attr,
                "cid": cluster_id,
                "cs": scalar,
                "cw": conf_weight,
                "ec": eff_count,
                "sc": scope,
            },
        )
        db.commit()
