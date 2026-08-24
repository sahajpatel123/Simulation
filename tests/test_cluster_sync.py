"""Tests for ``ClusterRegistry.sync_to_db`` — the startup cluster sync.

The sync ships every (cluster, trait, base_value) row to PostgreSQL
through one bulk UPDATE ... FROM (VALUES ...) per chunk. These tests pin
the three properties that keep it safe and survivable:

1. Values travel only as named bind parameters — no identifier from the
   registry may appear in the SQL text (injection regression guard).
2. Statements stay under PostgreSQL's per-statement bind-parameter
   ceiling, so registry growth chunks instead of failing at startup.
3. The whole sync commits exactly once, regardless of chunk count.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.simulation.clusters import registry as registry_module
from app.simulation.clusters.registry import ClusterRegistry


class _FakeSession:
    """Capture executed statements/params without touching a database."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.param_sets: list[dict] = []
        self.commits = 0

    def execute(self, statement, params=None):  # noqa: ANN001 - test fake
        self.statements.append(str(statement))
        self.param_sets.append(dict(params or {}))

    def commit(self) -> None:
        self.commits += 1


def _clusters(count: int, traits: int) -> list:
    return [
        SimpleNamespace(
            cluster_id=f"cluster_{i:03d}",
            base_traits={f"trait_{t}": 0.5 for t in range(traits)},
        )
        for i in range(count)
    ]


@pytest.fixture()
def patched_all_clusters(monkeypatch: pytest.MonkeyPatch):
    """Replace all_clusters without disturbing the class-level memo cache."""

    def _install(clusters: list) -> list:
        monkeypatch.setattr(ClusterRegistry, "all_clusters", lambda self: clusters, raising=True)
        return clusters

    return _install


class TestSyncToDb:
    def test_full_registry_uses_single_statement(self, patched_all_clusters):
        # The real 52 × 8 grid must fit one round-trip — chunking exists
        # purely as headroom for growth.
        patched_all_clusters(_clusters(52, traits=8))
        session = _FakeSession()

        ClusterRegistry().sync_to_db(session)

        assert len(session.statements) == 1
        assert len(session.param_sets[0]) == 52 * 8 * 3
        assert session.commits == 1

    def test_values_are_bound_never_inlined(self, patched_all_clusters):
        # Security contract behind today's repo-wide parameterized-SQL
        # audit: cluster/trait identifiers are data, so they may appear in
        # the params dict but never in the statement text itself.
        clusters = _clusters(2, traits=2)
        clusters[0].base_traits["trait_x"] = 0.25
        patched_all_clusters(clusters)
        session = _FakeSession()

        ClusterRegistry().sync_to_db(session)

        sql = "\n".join(session.statements)
        assert ":cid_0" in sql and ":val_0" in sql
        assert "cluster_000" not in sql
        assert "trait_x" not in sql
        assert session.param_sets[0]["cid_0"] == "cluster_000"
        assert session.param_sets[0]["trait_2"] == "trait_x"
        assert session.param_sets[0]["val_2"] == pytest.approx(0.25)

    def test_growth_chunks_instead_of_failing(self, monkeypatch, patched_all_clusters):
        # Simulate a registry far past the ceiling by shrinking the chunk
        # size: statements must split while every row still lands exactly
        # once and the single-commit guarantee holds.
        monkeypatch.setattr(
            ClusterRegistry,
            "_SYNC_MAX_BIND_PARAMS",
            ClusterRegistry._SYNC_PARAMS_PER_ROW * 100,
        )
        rows = patched_all_clusters(_clusters(37, traits=4))
        total_values = sum(len(c.base_traits) for c in rows)
        session = _FakeSession()

        ClusterRegistry().sync_to_db(session)

        expected_chunks = -(-total_values // 100)
        assert len(session.statements) == expected_chunks
        seen: set[tuple[str, str]] = set()
        for params in session.param_sets:
            i = 0
            while f"cid_{i}" in params:
                seen.add((params[f"cid_{i}"], params[f"trait_{i}"]))
                i += 1
        assert len(seen) == total_values == 37 * 4
        assert session.commits == 1

    def test_empty_registry_is_a_noop(self, patched_all_clusters):
        patched_all_clusters([])
        session = _FakeSession()

        ClusterRegistry().sync_to_db(session)

        assert session.statements == []
        assert session.commits == 0

    def test_module_no_longer_imports_sqla_inside_functions(self):
        # Repo rule: imports live at module top. Guard against the
        # function-local `from sqlalchemy import text` creeping back.
        import ast
        import inspect

        source = inspect.getsource(registry_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local_names = {
                    alias.name.split(".")[0]
                    for stmt in ast.walk(node)
                    if isinstance(stmt, ast.Import)
                    for alias in stmt.names
                }
                assert "sqlalchemy" not in local_names, f"{node.name} re-imports sqlalchemy locally"
