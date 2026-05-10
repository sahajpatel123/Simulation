from __future__ import annotations

import asyncio
import logging
import json
import os
import random
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from sqlalchemy import text

from app.browser.utils import cluster_to_agent_profile
from app.core.database import SessionLocal
from app.core.tier_enforcement import enforce_hardware_access
from app.models.project import Project
from app.models.user import User
from app.simulation.accountability import AccountabilityEngine
from app.simulation.agent_hierarchy import AgentHierarchyRouter, AgentTier
from app.simulation.architects.base import ArchitectOutput
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.cognitive_state import CognitiveStateMutator
from app.simulation.conductor import Conductor, ConductorResult
from app.simulation.product_type import ProductType
from app.worker import celery_app

_conductor = Conductor()
_mutator = CognitiveStateMutator()
_accountability = AccountabilityEngine()
_registry = ClusterRegistry()
_router = AgentHierarchyRouter()

CATEGORY_TO_PRODUCT_TYPE: dict[str, ProductType] = {
    "consumer_hardware": ProductType.CONSUMER_HARDWARE,
    "health_hardware": ProductType.HEALTH_HARDWARE,
    "iot_hardware": ProductType.IOT_HARDWARE,
    "wearable": ProductType.WEARABLE,
    "b2b_hardware": ProductType.B2B_HARDWARE,
}


def _norm_category_key(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _resolve_product_type(category: str | None, product_type_col: str | None) -> ProductType:
    for key in (_norm_category_key(category), _norm_category_key(product_type_col)):
        if key and key in CATEGORY_TO_PRODUCT_TYPE:
            return CATEGORY_TO_PRODUCT_TYPE[key]
    return ProductType.CONSUMER_HARDWARE


def _build_env_params(
    spec: dict,
    test_results: list[dict],
    target_price: float,
    category: str,
    product_type_col: str | None = None,
) -> dict:
    pt = _resolve_product_type(category, product_type_col)
    env: dict = {
        "average_order_value": target_price,
        "product_type": pt.value,
        "market_maturity": 0.5,
        "geography": "ALL_INDIA",
    }

    failed_tests = [r for r in test_results if r.get("status") == "FAIL"]
    for ft in failed_tests:
        if ft.get("test_type") == "BATTERY_DRAIN":
            env["battery_claim_validated"] = False
        if ft.get("test_type") == "WATER_INGRESS":
            env["ip_rating_validated"] = False
        if ft.get("test_type") == "DROP_TEST":
            env["build_quality_validated"] = False

    return env


def _spec_to_assumptions(spec: dict, test_results: list[dict]) -> list[dict]:
    assumptions: list[dict] = []
    dims = spec.get("dimensions") or {}

    if dims.get("weight_grams"):
        assumptions.append(
            {
                "assumption": f"Product weighs {dims['weight_grams']}g",
                "sensitivity": "MEDIUM",
                "claim_confidence": "VALIDATED_INTERNAL",
            }
        )

    battery_passed = any(
        r.get("test_type") == "BATTERY_DRAIN" and r.get("status") == "PASS"
        for r in test_results
    )
    battery_hours: float | None = None
    for r in test_results:
        if r.get("test_type") == "BATTERY_DRAIN":
            raw = (r.get("metrics") or {}).get("runtime_hours")
            if raw is not None:
                battery_hours = float(raw)
            break
    if battery_hours is not None:
        assumptions.append(
            {
                "assumption": f"Battery lasts {battery_hours:.0f} hours",
                "sensitivity": "CRITICAL",
                "claim_confidence": (
                    "VALIDATED_INTERNAL" if battery_passed else "ASPIRATIONAL"
                ),
            }
        )

    water_passed = any(
        r.get("test_type") == "WATER_INGRESS" and r.get("status") == "PASS"
        for r in test_results
    )
    if any(r.get("test_type") == "WATER_INGRESS" for r in test_results):
        ip_target = "IP54"
        for r in test_results:
            if r.get("test_type") == "WATER_INGRESS":
                ip_target = str((r.get("metrics") or {}).get("target_ip", "IP54"))
                break
        assumptions.append(
            {
                "assumption": f"Water resistance rated {ip_target}",
                "sensitivity": "HIGH",
                "claim_confidence": (
                    "VALIDATED_INTERNAL" if water_passed else "ASPIRATIONAL"
                ),
            }
        )

    for comp in (spec.get("components") or [])[:3]:
        assumptions.append(
            {
                "assumption": f"{comp.get('name', '')} made from {comp.get('material', '')}",
                "sensitivity": "LOW",
                "claim_confidence": "VALIDATED_INTERNAL",
            }
        )

    return assumptions


def _architect_outputs_to_dicts(
    arch_out_raw: dict[str, ArchitectOutput],
) -> dict[str, dict]:
    return {
        name: {"metrics": dict(out.metrics), "flags": dict(out.flags)}
        for name, out in arch_out_raw.items()
    }


def _latest_test_results(rows: list) -> list[dict]:
    """Keep newest row per test_type (query is ORDER BY created_at DESC)."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        tt = str(r.test_type)
        if tt in seen:
            continue
        seen.add(tt)
        metrics = r.results_json
        if isinstance(metrics, str):
            metrics = json.loads(metrics or "{}")
        elif metrics is None:
            metrics = {}
        fp = r.failure_points_json
        if isinstance(fp, list):
            pass
        elif isinstance(fp, str):
            fp = json.loads(fp or "[]")
        else:
            fp = []
        out.append(
            {
                "test_type": tt,
                "status": str(r.status),
                "pass_rate": float(r.pass_rate or 0),
                "metrics": metrics,
                "failure_points": fp,
            }
        )
    return out


def _conductor_result_jsonable(result: ConductorResult) -> dict:
    return {
        "product_type": result.product_type.value,
        "population_weighted_conversion": result.population_weighted_conversion,
        "cluster_breakdown": result.cluster_breakdown,
        "architect_accountability": result.architect_accountability,
    }


def _public_api_base() -> str:
    return os.environ.get("PUBLIC_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _fallback_sessions(
    cid: str,
    n_agents: int,
    eff_will_pay: float,
) -> list[dict]:
    sessions: list[dict] = []
    for _ in range(n_agents):
        converted = random.random() < eff_will_pay * 0.7
        sessions.append(
            {
                "converted": converted,
                "outcome": "converted" if converted else "abandoned",
                "pages_visited": 2 if random.random() < eff_will_pay else 1,
                "duration_seconds": random.randint(10, 60),
                "events": [{"action": "micro_eval", "cluster": cid}],
                "agent_cluster_id": cid,
            }
        )
    return sessions


async def _run_browser_batch(
    pool,
    cluster_id: str,
    agent_profile: dict,
    architect_outputs: dict,
    n_agents: int,
    serve_url: str,
) -> list:
    return await pool.run_cluster_batch(
        cluster_id=cluster_id,
        agent_profiles=[agent_profile] * n_agents,
        architect_outputs=architect_outputs,
        url=serve_url,
    )


@celery_app.task(
    name="hardware.consumer_simulation",
    bind=True,
    max_retries=2,
    soft_time_limit=600,
    time_limit=720,
)
def run_hardware_consumer_simulation(
    self,
    hardware_product_id: int,
    project_id: int,
    generated_ui_id: int | None = None,
):
    db = SessionLocal()
    try:
        hw = db.execute(
            text("""
            SELECT hp.id, hp.name, hp.category, hp.product_type,
                   hp.target_price_inr,
                   hm.model_data_json
            FROM hardware_products hp
            LEFT JOIN hardware_3d_models hm
              ON hm.hardware_product_id = hp.id
            WHERE hp.id = :hw_id AND hp.project_id = :pid
            ORDER BY hm.created_at DESC LIMIT 1
        """),
            {"hw_id": hardware_product_id, "pid": project_id},
        ).fetchone()

        if not hw:
            raise ValueError(f"Hardware product {hardware_product_id} not found")

        user = (
            db.query(User)
            .join(Project, Project.user_id == User.id)
            .filter(Project.id == project_id)
            .first()
        )
        if not user:
            raise ValueError("Project owner not found for hardware consumer simulation")
        enforce_hardware_access(user, db)

        spec = hw.model_data_json
        if isinstance(spec, str):
            spec = json.loads(spec or "{}")
        spec = dict(spec)
        spec["category"] = hw.category or "consumer_hardware"

        test_result_rows = (
            db.execute(
                text("""
            SELECT test_type, status, results_json, failure_points_json, pass_rate
            FROM hardware_test_results
            WHERE hardware_product_id = :hw_id
            ORDER BY created_at DESC
        """),
                {"hw_id": hardware_product_id},
            )
            .fetchall()
            or []
        )

        test_results = _latest_test_results(list(test_result_rows))

        target_price = float(hw.target_price_inr or 1999)
        cat = str(hw.category or "")
        ptype_col = str(hw.product_type or "")
        env_params = _build_env_params(spec, test_results, target_price, cat, ptype_col)
        assumptions = _spec_to_assumptions(spec, test_results)

        product_type = _resolve_product_type(cat, ptype_col)

        conductor_result = _conductor.run(
            agents=[],
            env_params=env_params,
            assumptions=assumptions,
            product_type=product_type,
            simulation_id=None,
            signal_quality=0.6,
            db=None,
        )

        all_clusters = _registry.all_clusters()
        cluster_results: dict[str, dict] = {}
        session_rows: list[dict] = []
        total_agents = 0
        total_converted = 0

        serve_url: str | None = None
        if generated_ui_id:
            token_row = db.execute(
                text("SELECT preview_token FROM generated_uis WHERE id = :ui_id"),
                {"ui_id": generated_ui_id},
            ).fetchone()
            if token_row and token_row.preview_token:
                serve_url = (
                    f"{_public_api_base()}/api/v1/generated-uis/{generated_ui_id}/serve"
                    f"?preview_token={token_row.preview_token}"
                )

        findings_all: list = []
        try:
            findings_all = _accountability.generate_domain_findings(conductor_result)
        except Exception:
            findings_all = []
        findings_by_cluster: dict[str, list] = {}
        for f in findings_all:
            findings_by_cluster.setdefault(f.cluster_id, []).append(f)

        skip_browser = os.environ.get("THECEE_SKIP_HARDWARE_BROWSER", "").lower() in (
            "1",
            "true",
            "yes",
        )

        from app.browser.pool import BrowserPool

        browser_pool = BrowserPool(max_sessions=4) if serve_url and not skip_browser else None

        db.execute(
            text("""
                UPDATE hardware_consumer_simulation_runs
                SET status = 'RUNNING'
                WHERE id = (
                    SELECT id FROM hardware_consumer_simulation_runs
                    WHERE hardware_product_id = :hw_id AND project_id = :pid
                      AND status = 'QUEUED'
                    ORDER BY created_at DESC
                    LIMIT 1
                )
            """),
            {"hw_id": hardware_product_id, "pid": project_id},
        )
        db.commit()

        for cluster in all_clusters:
            cid = cluster.cluster_id
            agent_profile = cluster_to_agent_profile(cid)
            arch_out_raw = conductor_result.cluster_results.get(cid, {})
            arch_dicts = _architect_outputs_to_dicts(arch_out_raw)

            mutation_result = _mutator.apply(
                cluster_id=cid,
                agent_profile=agent_profile,
                architect_outputs=arch_dicts,
                assumptions=assumptions,
            )
            mutated_profile = (
                mutation_result.mutated_profile
                if mutation_result.any_mutation_fired
                else agent_profile
            )

            decision = _router.route(cid, mutated_profile, arch_dicts)
            n_agents = max(1, int(20 * float(cluster.population_weight) * 10))

            if (
                serve_url
                and browser_pool is not None
                and decision.tier in (AgentTier.WORKER, AgentTier.SUPERVISOR)
            ):
                sessions = asyncio.run(
                    _run_browser_batch(browser_pool, cid, mutated_profile, arch_dicts, n_agents, serve_url)
                )
            else:
                pricing_m = arch_dicts.get("PricingArchitect", {}).get("metrics", {})
                will_pay = float(pricing_m.get("will_pay_probability", 0.05))
                trust_pen = abs(float(mutation_result.total_trust_delta))
                eff_will_pay = max(0.0, will_pay - trust_pen * 0.5)
                sessions = _fallback_sessions(cid, n_agents, eff_will_pay)

            converted = sum(1 for s in sessions if s.get("converted"))
            cr = converted / max(len(sessions), 1)

            cfs = findings_by_cluster.get(cid, [])
            top_finding = cfs[0].finding if cfs else "No critical findings"

            cluster_results[cid] = {
                "cluster_name": cluster.name,
                "tier": decision.tier.value,
                "agents_run": len(sessions),
                "converted": converted,
                "conversion_rate": round(cr, 4),
                "population_fraction": round(float(cluster.population_weight), 4),
                "top_finding": top_finding,
                "mutations_fired": [m.trigger_name for m in mutation_result.mutations_applied],
            }
            total_agents += len(sessions)
            total_converted += converted

            if serve_url and generated_ui_id:
                for s in sessions:
                    session_rows.append(
                        {
                            "generated_ui_id": generated_ui_id,
                            "agent_cluster_id": cid,
                            "agent_profile_json": json.dumps(mutated_profile),
                            "events_json": json.dumps(s.get("events", [])),
                            "outcome": s.get("outcome", "abandoned"),
                            "duration_seconds": int(s.get("duration_seconds", 0)),
                            "pages_visited": int(s.get("pages_visited", 1)),
                            "converted": bool(s.get("converted", False)),
                        }
                    )

        for row in session_rows:
            db.execute(
                text("""
                INSERT INTO ui_simulation_sessions
                (generated_ui_id, agent_cluster_id, agent_profile_json,
                 events_json, outcome, duration_seconds, pages_visited,
                 converted, created_at)
                VALUES (:generated_ui_id, :agent_cluster_id,
                        CAST(:agent_profile_json AS jsonb), CAST(:events_json AS jsonb),
                        :outcome, :duration_seconds, :pages_visited,
                        :converted, NOW())
            """),
                row,
            )

        sorted_by_conv = sorted(
            cluster_results.items(),
            key=lambda x: x[1]["conversion_rate"],
            reverse=True,
        )
        champions = [cid for cid, _ in sorted_by_conv[:3]]
        blockers = [
            cid
            for cid, data in sorted(
                cluster_results.items(),
                key=lambda x: x[1]["conversion_rate"],
            )
            if data["population_fraction"] > 0.01
        ][:3]

        overall_cr = round(total_converted / max(total_agents, 1), 4)

        findings_top = [f.to_dict() for f in findings_all[:10]]
        primary_domain = (
            _accountability.primary_failure_domain(findings_all)
            if findings_top
            else "unknown"
        )

        results_json = {
            "total_agents": total_agents,
            "total_converted": total_converted,
            "overall_conversion_rate": overall_cr,
            "product_type": product_type.value,
            "prototype_wired": generated_ui_id is not None,
            "generated_ui_id": generated_ui_id,
            "cluster_results": cluster_results,
            "champion_clusters": champions,
            "blocker_clusters": blockers,
            "domain_findings": findings_top,
            "primary_failure_domain": primary_domain,
            "architect_accountability": conductor_result.architect_accountability,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        conductor_blob = _conductor_result_jsonable(conductor_result)

        db.execute(
            text("""
            UPDATE hardware_consumer_simulation_runs
            SET status = 'COMPLETED', agent_count = :agents, product_type = :pt,
                results_json = CAST(:results AS jsonb),
                conductor_result_json = CAST(:conductor AS jsonb),
                completed_at = NOW()
            WHERE id = (
                SELECT id FROM hardware_consumer_simulation_runs
                WHERE hardware_product_id = :hw_id AND project_id = :pid
                  AND status IN ('QUEUED', 'RUNNING')
                ORDER BY created_at DESC
                LIMIT 1
            )
        """),
            {
                "hw_id": hardware_product_id,
                "pid": project_id,
                "agents": total_agents,
                "pt": product_type.value,
                "results": json.dumps(results_json),
                "conductor": json.dumps(conductor_blob),
            },
        )
        db.commit()

        return {
            "status": "completed",
            "overall_conversion_rate": overall_cr,
            "champion_clusters": champions,
            "blocker_clusters": blockers,
            "prototype_wired": generated_ui_id is not None,
            "total_agents": total_agents,
        }

    except Exception as e:
        try:
            db.rollback()
        except Exception as _exc:
            logger.debug(
                "%s suppressed: %s",
                __name__,
                _exc,
            )
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if retries >= max_retries:
            try:
                err_msg = str(e)[:500]
                db.execute(
                    text("""
                        UPDATE hardware_consumer_simulation_runs
                        SET status = 'FAILED', agent_count = 0, product_type = 'unknown',
                            results_json = CAST(:results AS jsonb), completed_at = NOW()
                        WHERE id = (
                            SELECT id FROM hardware_consumer_simulation_runs
                            WHERE hardware_product_id = :hw_id AND project_id = :pid
                              AND status IN ('QUEUED', 'RUNNING')
                            ORDER BY created_at DESC
                            LIMIT 1
                        )
                    """),
                    {
                        "hw_id": hardware_product_id,
                        "pid": project_id,
                        "results": json.dumps(
                            {"error_message": err_msg, "status": "FAILED"}
                        ),
                    },
                )
                db.commit()
            except Exception:
                db.rollback()
        raise self.retry(exc=e, countdown=30)
    finally:
        db.close()
