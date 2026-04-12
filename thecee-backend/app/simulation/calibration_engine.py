from __future__ import annotations

import json
from collections import defaultdict
from statistics import mean

from sqlalchemy import text


ALL_ARCHITECT_NAMES = [
    "MarketTimingArchitect",
    "CompetitiveDynamicsArchitect",
    "TrustArchitect",
    "PricingArchitect",
    "OnboardingArchitect",
    "FeatureAdoptionArchitect",
    "RetentionArchitect",
    "SupportFrictionArchitect",
    "ViralityArchitect",
    "MacroeconomicArchitect",
    "DemographicInteractionArchitect",
    "AssumptionCascadeArchitect",
    "PurchaseDecisionArchitect",
    "PhysicalSensoryArchitect",
    "PerformanceThresholdArchitect",
    "SetupFirstUseArchitect",
    "EcosystemCompatibilityArchitect",
    "DistributionChannelArchitect",
    "AftersalesLifecycleArchitect",
    "HealthSafetyHardwareArchitect",
]


def _predicted_conversion(results: dict) -> float:
    return float(
        results.get("mean_conversion_rate")
        or results.get("conversion_rate")
        or results.get("population_weighted_conversion")
        or 0
    )


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
        if predicted > 0.10 and actual < predicted * 0.10:
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
            scalar = 1.0 / (1.0 + wmean)
            self._upsert_correction(
                db,
                "GLOBAL_BIAS",
                product_type,
                "ALL",
                "ALL",
                scalar,
                min(1.0, eff_count / (eff_count + 30)),
                eff_count,
                "CATEGORY_GLOBAL",
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
            scalar = 1.0 / (1.0 + wmean)
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
