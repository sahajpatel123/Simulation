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

from datetime import UTC, datetime

from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType
from app.tasks import simulation_tasks as tasks_mod

_ENV = {
    "average_order_value": 999.0,
    "price_sensitivity": 0.5,
    "market_maturity": 0.3,
}


class _FakeSimulation:
    def __init__(
        self,
        *,
        status: str = "RUNNING",
        task_id: str | None = "task-abc",
    ) -> None:
        self.id = 1
        self.project_id = 10
        self.status = status
        self.task_id = task_id
        self.error_message: str | None = None
        self.results_json: dict | None = None
        self.consumer_volume = 10_000
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.updated_at = datetime(2026, 1, 1, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, sims: list[_FakeSimulation]) -> None:
        self.sims = sims

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self) -> _FakeSimulation | None:
        return self.sims[0] if self.sims else None


class _FakeSession:
    def __init__(self, sims: list[_FakeSimulation]) -> None:
        self.sims = sims

    def query(self, *args, **kwargs) -> _FakeQuery:
        return _FakeQuery(self.sims)


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


def test_progress_endpoint_surfaces_cluster_metadata(monkeypatch) -> None:
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation(status="RUNNING", task_id="task-abc")
    meta = {
        "stage": "Simulating cluster metro_power_professional (1/52)",
        "pct": 26,
        "cluster_id": "metro_power_professional",
        "clusters_completed": 1,
        "clusters_total": 52,
    }

    class _TaskResult:
        state = "PROGRESS"
        info = meta

    monkeypatch.setattr(
        sim_mod.celery_app,
        "AsyncResult",
        lambda task_id: _TaskResult(),
    )

    out = sim_mod.get_simulation_progress(
        simulation_id=1,
        db=_FakeSession([sim]),
        current_user=type("U", (), {"id": 42})(),
    )

    assert out["pct"] == 26
    assert out["stage"] == "Simulating cluster metro_power_professional (1/52)"
    assert out["cluster_id"] == "metro_power_professional"
    assert out["clusters_completed"] == 1
    assert out["clusters_total"] == 52


def test_progress_endpoint_tolerates_non_dict_celery_meta(monkeypatch) -> None:
    """A string ``info`` (possible with some Celery result backends) must not
    hide the per-cluster progress or crash the polling fallback path."""
    from app.api.v1 import simulations as sim_mod

    sim = _FakeSimulation(status="RUNNING", task_id="task-abc")

    class _TaskResult:
        state = "PROGRESS"
        info = "PROGRESS"

    monkeypatch.setattr(
        sim_mod.celery_app,
        "AsyncResult",
        lambda task_id: _TaskResult(),
    )

    out = sim_mod.get_simulation_progress(
        simulation_id=1,
        db=_FakeSession([sim]),
        current_user=type("U", (), {"id": 42})(),
    )

    assert out["pct"] == 50
    assert out["stage"] is None
    assert out["cluster_id"] is None
    assert out["clusters_completed"] is None
    assert out["clusters_total"] is None
