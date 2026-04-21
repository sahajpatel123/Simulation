from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.database import SessionLocal
from app.hardware.physics_engine import PhysicsSimulationEngine
from app.hardware.test_configs import TestConfigBuilder
from app.worker import celery_app

engine = PhysicsSimulationEngine()
builder = TestConfigBuilder()


@celery_app.task(
    name="hardware.run_tests",
    bind=True,
    max_retries=2,
    soft_time_limit=120,
    time_limit=150,
)
def run_hardware_tests(self, hardware_product_id: int, project_id: int):
    db = SessionLocal()
    try:
        hw = db.execute(
            text("""
            SELECT hp.id, hp.name, hp.category, hp.product_type,
                   hp.target_price_inr, hp.weight_grams,
                   hm.model_data_json
            FROM hardware_products hp
            LEFT JOIN hardware_3d_models hm
              ON hm.hardware_product_id = hp.id
            WHERE hp.id = :hw_id AND hp.project_id = :pid
            ORDER BY hm.created_at DESC
            LIMIT 1
        """),
            {"hw_id": hardware_product_id, "pid": project_id},
        ).fetchone()

        if not hw:
            raise ValueError(f"Hardware product {hardware_product_id} not found")

        model_data = hw.model_data_json
        if isinstance(model_data, str):
            model_data = json.loads(model_data or "{}")
        if not model_data:
            raise ValueError("No 3D model spec found — generate spec first")

        if "dimensions" not in model_data:
            model_data["dimensions"] = {}
        if hw.weight_grams:
            model_data["dimensions"]["weight_grams"] = hw.weight_grams

        config_rows = db.execute(
            text("""
            SELECT id, test_type, parameters_json, environment_conditions_json
            FROM hardware_test_configs
            WHERE hardware_product_id = :hw_id
            ORDER BY created_at ASC
        """),
            {"hw_id": hardware_product_id},
        ).fetchall()

        config_id_by_type: dict[str, int] = {}
        if not config_rows:
            cat = (hw.category or "").strip().lower() or "consumer_hardware"
            configs = builder.defaults_for_category(cat)
        else:
            configs = []
            for row in config_rows:
                config_id_by_type[str(row.test_type)] = int(row.id)
                params = (
                    row.parameters_json
                    if isinstance(row.parameters_json, dict)
                    else json.loads(row.parameters_json or "{}")
                )
                params = dict(params)
                severity_weight = float(params.pop("severity_weight", 0.5))
                try:
                    cfg = builder.custom_config(
                        test_type=row.test_type,
                        params=params,
                        severity_weight=severity_weight,
                    )
                    configs.append(cfg)
                except ValueError:
                    continue

        if not configs:
            cat = (hw.category or "").strip().lower() or "consumer_hardware"
            configs = builder.defaults_for_category(cat)

        results = engine.run_full_suite(model_data, configs)

        all_failure_points: list[dict] = []
        for result in results:
            for fp in result.failure_points:
                all_failure_points.append(
                    {
                        **fp,
                        "test_type": result.test_type,
                        "recommended_fix": (
                            result.recommendations[0]
                            if result.recommendations
                            else "Review component specification"
                        ),
                    }
                )
        SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        all_failure_points.sort(
            key=lambda x: SEVERITY_ORDER.get(x.get("severity", "INFO"), 2)
        )
        seen_components: set[str] = set()
        top_failures: list[dict] = []
        for fp in all_failure_points:
            cid = str(fp.get("component_id", ""))
            if cid not in seen_components:
                seen_components.add(cid)
                top_failures.append(fp)
            if len(top_failures) >= 3:
                break

        result_ids: list[int] = []
        for result in results:
            tid = config_id_by_type.get(result.test_type)
            row = db.execute(
                text("""
                INSERT INTO hardware_test_results
                (hardware_product_id, test_config_id, test_type, status,
                 results_json, failure_points_json, pass_rate, created_at)
                VALUES (:hw_id, :test_config_id, :test_type, :status,
                        CAST(:results AS jsonb), CAST(:fp AS jsonb), :pass_rate, NOW())
                RETURNING id
            """),
                {
                    "hw_id": hardware_product_id,
                    "test_config_id": tid,
                    "test_type": result.test_type,
                    "status": result.status,
                    "results": json.dumps(result.metrics),
                    "fp": json.dumps(result.failure_points),
                    "pass_rate": result.pass_rate,
                },
            ).fetchone()
            if row is not None:
                result_ids.append(int(row.id))

        overall_pass_rate = sum(r.pass_rate for r in results) / max(len(results), 1)
        critical_count = sum(1 for r in results if r.severity == "CRITICAL")
        summary = {
            "total_tests": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status == "FAIL"),
            "partial": sum(1 for r in results if r.status == "PARTIAL"),
            "overall_pass_rate": round(overall_pass_rate, 4),
            "critical_count": critical_count,
            "top_failure_points": top_failures,
            "test_result_ids": result_ids,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        db.execute(
            text("""
            UPDATE hardware_products
            SET last_test_summary_json = CAST(:summary AS jsonb)
            WHERE id = :hw_id AND project_id = :pid
        """),
            {
                "summary": json.dumps(summary),
                "hw_id": hardware_product_id,
                "pid": project_id,
            },
        )

        db.commit()
        return {
            "status": "completed",
            "hardware_product_id": hardware_product_id,
            "tests_run": len(results),
            "overall_pass_rate": round(overall_pass_rate, 4),
            "critical_failures": critical_count,
            "top_failure_points": top_failures,
        }

    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=15)
    finally:
        db.close()
