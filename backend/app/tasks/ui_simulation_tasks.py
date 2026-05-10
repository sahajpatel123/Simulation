from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from sqlalchemy import text

from app.browser.pool import BrowserPool
from app.browser.utils import cluster_to_agent_profile
from app.core.database import SessionLocal
from app.models.ui_simulation_session import UISimulationSession
from app.models.ui_simulation_run import UISimulationRun
from app.simulation.agent_hierarchy import AgentHierarchyRouter, AgentTier
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType
from app.worker import celery_app

_registry = ClusterRegistry()
_router = AgentHierarchyRouter()
_conductor = Conductor()


# ── MICRO evaluator (no browser, pure stochastic) ──
def _micro_evaluate(
    cluster_id: str,
    agent_profile: dict,
    architect_outputs: dict,
    n_agents: int,
) -> list[dict]:
    """
    Fast stochastic simulation for low-literacy/quick-bounce clusters.
    More accurate than full browser for these users.
    """
    from app.browser.agent_behaviour import AgentBehaviour

    results = []
    for _i in range(n_agents):
        behaviour = AgentBehaviour(cluster_id, agent_profile, architect_outputs)
        # Trust gate first
        if not behaviour.trust_gate():
            results.append(
                {
                    "converted": False,
                    "outcome": "abandoned",
                    "pages_visited": 1,
                    "duration_seconds": 2,
                    "events": [{"action": "abandon", "reason": "trust_gate"}],
                }
            )
            continue
        # Stochastic conversion
        pricing_m = architect_outputs.get("PricingArchitect", {}).get("metrics", {})
        will_pay = float(pricing_m.get("will_pay_probability", 0.05))
        converted = random.random() < will_pay * 0.6  # micro users convert less
        results.append(
            {
                "converted": converted,
                "outcome": "converted" if converted else "abandoned",
                "pages_visited": 1 if not converted else 2,
                "duration_seconds": random.randint(5, 25),
                "events": [{"action": "micro_eval", "cluster": cluster_id}],
            }
        )
    return results


def _session_outcome(s: dict) -> str:
    if s.get("outcome"):
        return str(s["outcome"])
    if s.get("converted"):
        return "converted"
    return "abandoned"


async def _run_browser_batch(
    pool: BrowserPool,
    cluster_id: str,
    agent_profile: dict,
    architect_outputs: dict,
    n_agents: int,
    serve_url: str,
) -> list[dict]:
    return await pool.run_cluster_batch(
        cluster_id=cluster_id,
        agent_profiles=[agent_profile] * n_agents,
        architect_outputs=architect_outputs,
        url=serve_url,
    )


# ── Main Celery task ──
@celery_app.task(
    name="ui_simulation.run",
    bind=True,
    max_retries=2,
    soft_time_limit=600,
    time_limit=720,
)
def run_ui_simulation(
    self,
    ui_simulation_run_id: int,
    generated_ui_id: int,
    project_id: int,
    product_type: str = "saas",
    agents_per_cluster: int = 20,
    serve_url: str | None = None,
):
    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE ui_simulation_runs SET status='RUNNING' WHERE id=:id"),
            {"id": ui_simulation_run_id},
        )
        db.commit()

        pt = (
            ProductType(product_type)
            if product_type in [p.value for p in ProductType]
            else ProductType.SAAS
        )

        # Run Conductor for architect outputs (no DB write, no agents)
        conductor_result = _conductor.run(
            agents=[],
            env_params={
                "average_order_value": 999,
                "market_maturity": 0.5,
                "product_type": pt.value,
            },
            assumptions=[],
            product_type=pt,
        )

        all_clusters = _registry.all_clusters()
        cluster_results: dict = {}
        session_maps: list[dict] = []
        total_agents = 0
        total_converted = 0

        browser_batches: list[tuple[str, object, dict, dict, int]] = []

        for cluster in all_clusters:
            cid = cluster.cluster_id
            agent_profile = cluster_to_agent_profile(cid)
            arch_out = conductor_result.cluster_results.get(cid, {})

            # Convert ArchitectOutput objects to plain dicts
            arch_dicts = {
                name: {
                    "metrics": out.metrics,
                    "flags": out.flags,
                }
                for name, out in arch_out.items()
            }

            decision = _router.route(cid, agent_profile, arch_dicts)
            n = max(1, int(agents_per_cluster * cluster.population_weight * 10))

            if decision.tier == AgentTier.MICRO or serve_url is None:
                session_data = _micro_evaluate(cid, agent_profile, arch_dicts, n)
            else:
                browser_batches.append((cid, cluster, agent_profile, arch_dicts, n))
                continue

            converted = sum(1 for s in session_data if s.get("converted"))
            cr = converted / max(len(session_data), 1)

            cluster_results[cid] = {
                "cluster_name": cluster.name,
                "tier": decision.tier.value,
                "agents_run": len(session_data),
                "converted": converted,
                "conversion_rate": round(cr, 4),
                "population_fraction": round(cluster.population_weight, 4),
                "top_finding": _top_finding(conductor_result, cid),
            }
            total_agents += len(session_data)
            total_converted += converted

            # Collect session rows for DB
            for s in session_data:
                conv = bool(s.get("converted", False))
                session_maps.append(
                    {
                        "generated_ui_id": generated_ui_id,
                        "agent_cluster_id": cid,
                        "agent_profile_json": agent_profile,
                        "events_json": s.get("events", []),
                        "outcome": _session_outcome(s),
                        "duration_seconds": int(s.get("duration_seconds", 0)),
                        "pages_visited": int(s.get("pages_visited", 1)),
                        "converted": conv,
                    }
                )

        if browser_batches:
            browser_pool = BrowserPool(max_sessions=4)

            async def _run_browser_batches() -> list[tuple[str, object, dict, list[dict]]]:
                results: list[tuple[str, object, dict, list[dict]]] = []
                for cid, cluster, agent_profile, arch_dicts, n in browser_batches:
                    sessions = await _run_browser_batch(
                        browser_pool, cid, agent_profile, arch_dicts, n, serve_url
                    )
                    results.append((cid, cluster, agent_profile, sessions))
                return results

            for cid, cluster, agent_profile, session_data in asyncio.run(_run_browser_batches()):
                converted = sum(1 for s in session_data if s.get("converted"))
                cr = converted / max(len(session_data), 1)
                cluster_results[cid] = {
                    "cluster_name": cluster.name,
                    "tier": AgentTier.WORKER.value,
                    "agents_run": len(session_data),
                    "converted": converted,
                    "conversion_rate": round(cr, 4),
                    "population_fraction": round(cluster.population_weight, 4),
                    "top_finding": _top_finding(conductor_result, cid),
                }
                total_agents += len(session_data)
                total_converted += converted
                for s in session_data:
                    conv = bool(s.get("converted", False))
                    session_maps.append(
                        {
                            "generated_ui_id": generated_ui_id,
                            "agent_cluster_id": cid,
                            "agent_profile_json": agent_profile,
                            "events_json": s.get("events", []),
                            "outcome": _session_outcome(s),
                            "duration_seconds": int(s.get("duration_seconds", 0)),
                            "pages_visited": int(s.get("pages_visited", 1)),
                            "converted": conv,
                        }
                    )

        if session_maps:
            db.bulk_insert_mappings(UISimulationSession, session_maps)

        overall_cr = round(total_converted / max(total_agents, 1), 4)
        results = {
            "total_agents": total_agents,
            "total_converted": total_converted,
            "overall_conversion_rate": overall_cr,
            "cluster_results": cluster_results,
            "product_type": product_type,
        }

        run_row = db.get(UISimulationRun, ui_simulation_run_id)
        if run_row:
            run_row.status = "COMPLETED"
            run_row.results_json = results
            run_row.conductor_result_json = {
                "cluster_breakdown": conductor_result.cluster_breakdown,
            }
            run_row.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "completed", "overall_conversion_rate": overall_cr}

    except Exception as e:
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_retries = int(getattr(self, "max_retries", 0) or 0)
        if retries >= max_retries:
            try:
                db.execute(
                    text("UPDATE ui_simulation_runs SET status='FAILED' WHERE id=:id"),
                    {"id": ui_simulation_run_id},
                )
                db.commit()
            except Exception:
                db.rollback()
        raise self.retry(exc=e, countdown=30) from e
    finally:
        db.close()


def _top_finding(conductor_result, cluster_id: str) -> str:
    from app.simulation.accountability import AccountabilityEngine

    try:
        eng = AccountabilityEngine()
        findings = eng.generate_domain_findings(conductor_result)
        cluster_findings = [f for f in findings if f.cluster_id == cluster_id]
        return cluster_findings[0].finding if cluster_findings else "No critical findings"
    except Exception:
        return "Analysis unavailable"
