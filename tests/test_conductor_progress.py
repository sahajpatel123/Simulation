"""Tests for per-cluster simulation progress reporting.

The conductor's long "Running cluster simulation" phase previously emitted
no intermediate progress: a 10 000-agent run sat at 25% for the entire
cluster × architect sweep. This feature adds an advisory
``progress_callback`` to ``Conductor.run()`` (called once per completed
cluster) and task-side helpers that map cluster counts into the 25–89%
band of the run, so both WebSocket listeners and the polling progress
endpoint see live per-cluster movement.
"""

from __future__ import annotations

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType
from app.tasks import simulation_tasks as tasks_mod

_ENV = {
    "average_order_value": 999.0,
    "price_sensitivity": 0.5,
    "market_maturity": 0.3,
}


def test_conductor_progress_callback_reports_every_cluster() -> None:
    calls: list[tuple[str, int, int]] = []

    Conductor().run(
        agents=[],
        env_params=_ENV,
        assumptions=[],
        product_type=ProductType.SAAS,
        progress_callback=lambda cluster_id, completed, total: calls.append(
            (cluster_id, completed, total)
        ),
    )

    expected = [c.cluster_id for c in ClusterRegistry().all_clusters()]
    assert [c[0] for c in calls] == expected
    assert [c[1] for c in calls] == list(range(1, len(expected) + 1))
    assert all(c[2] == len(expected) for c in calls)


def test_conductor_progress_callback_failure_does_not_abort_run() -> None:
    def boom(cluster_id: str, completed: int, total: int) -> None:
        raise RuntimeError("progress observer down")

    result = Conductor().run(
        agents=[],
        env_params=_ENV,
        assumptions=[],
        product_type=ProductType.SAAS,
        progress_callback=boom,
    )

    assert len(result.cluster_results) == len(ClusterRegistry().all_clusters())


def test_cluster_progress_pct_stays_in_conductor_band() -> None:
    assert tasks_mod._cluster_progress_pct(0, 52) == 25
    assert tasks_mod._cluster_progress_pct(1, 52) == 26
    assert tasks_mod._cluster_progress_pct(26, 52) == 57
    assert tasks_mod._cluster_progress_pct(52, 52) == 89
    assert tasks_mod._cluster_progress_pct(0, 0) == 25
    assert tasks_mod._cluster_progress_pct(5, 0) == 25


def test_cluster_progress_stage_includes_position() -> None:
    assert (
        tasks_mod._cluster_progress_stage("cluster_a", 3, 52)
        == "Simulating cluster cluster_a (3/52)"
    )
