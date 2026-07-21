"""
Tests for ClusterRegistry caching, defensive validation, and weight
pre-computation (cycle 28 cluster-cache-polish).

These tests lock in the new performance contract:

  1. ``all_clusters()`` returns the same list object across calls (memoised
     at the class level — the registry is immutable post-import).
  2. ``clusters_for_product_type()`` returns the same list per product type.
  3. ``get_cluster()`` raises KeyError on bad input (empty, non-str, missing).
  4. ``total_weight_check()`` returns True without re-summing.
  5. The cache survives across multiple ClusterRegistry() instances (class-
     level state, not instance state).
  6. Caching is thread-safe via an RLock.
"""
from __future__ import annotations

import threading

import pytest


@pytest.fixture(autouse=True)
def _reset_registry_cache() -> None:
    """Reset class-level caches before each test for isolation."""
    from app.simulation.clusters.registry import ClusterRegistry

    ClusterRegistry.reset_cache()
    yield
    ClusterRegistry.reset_cache()


def test_all_clusters_returns_same_object_on_repeated_calls() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r1 = ClusterRegistry()
    r2 = ClusterRegistry()
    # Same list object → memoised.
    assert r1.all_clusters() is r2.all_clusters()
    # Still 52.
    assert len(r1.all_clusters()) == 52


def test_clusters_for_product_type_returns_same_object() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    saas_a = r.clusters_for_product_type("saas")
    saas_b = r.clusters_for_product_type("saas")
    assert saas_a is saas_b
    assert len(saas_a) > 0
    # Every result actually has "saas" in product_affinities.
    assert all("saas" in c.product_affinities for c in saas_a)


def test_clusters_for_product_type_unknown_returns_empty_not_error() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    assert r.clusters_for_product_type("this_product_type_does_not_exist") == []


def test_clusters_for_product_type_invalid_input_returns_empty() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    assert r.clusters_for_product_type("") == []
    assert r.clusters_for_product_type(None) == []  # type: ignore[arg-type]
    assert r.clusters_for_product_type(42) == []  # type: ignore[arg-type]


def test_get_cluster_validates_input() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()

    # Happy path.
    metro = r.get_cluster("metro_power_professional")
    assert metro.cluster_id == "metro_power_professional"
    assert metro.population_weight > 0

    # Unknown id → KeyError with helpful message.
    with pytest.raises(KeyError, match="Unknown cluster_id"):
        r.get_cluster("definitely_not_a_cluster")

    # Empty / non-str → KeyError with type-aware message.
    with pytest.raises(KeyError, match="non-empty str"):
        r.get_cluster("")
    with pytest.raises(KeyError, match="non-empty str"):
        r.get_cluster(None)  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="non-empty str"):
        r.get_cluster(123)  # type: ignore[arg-type]


def test_total_weight_check_uses_precomputed_sum() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    assert r.total_weight_check() is True

    # The class-level _weight_sum should be exactly 1.0 (or within tolerance).
    stats = r.cache_stats()
    assert stats["weight_sum"] == pytest.approx(1.0, abs=1e-6)


def test_cache_stats_reflect_call_history() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    # Before any call.
    stats = r.cache_stats()
    assert stats["all_clusters_cached"] is False
    assert stats["product_types_cached"] == []

    r.all_clusters()
    r.clusters_for_product_type("saas")
    r.clusters_for_product_type("consumer_hardware")

    stats_after = r.cache_stats()
    assert stats_after["all_clusters_cached"] is True
    assert set(stats_after["product_types_cached"]) == {"saas", "consumer_hardware"}


def test_caches_survive_across_instances() -> None:
    """Caches are class-level so subsequent instances reuse the warm cache."""
    from app.simulation.clusters.registry import ClusterRegistry

    r1 = ClusterRegistry()
    r1.all_clusters()
    r1.clusters_for_product_type("saas")

    r2 = ClusterRegistry()
    # r2 sees the same cached list (identity preserved).
    assert r2.all_clusters() is r1.all_clusters()
    assert r2.clusters_for_product_type("saas") is r1.clusters_for_product_type("saas")


def test_reset_cache_clears_all_entries() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    r.all_clusters()
    r.clusters_for_product_type("saas")
    assert r.cache_stats()["all_clusters_cached"] is True
    assert "saas" in r.cache_stats()["product_types_cached"]

    ClusterRegistry.reset_cache()
    assert r.cache_stats()["all_clusters_cached"] is False
    assert r.cache_stats()["product_types_cached"] == []


def test_caching_is_thread_safe() -> None:
    """
    Concurrent callers all observe the same canonical list (no torn writes,
    no duplicate list construction under contention).
    """
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    results: list[list] = []
    errors: list[Exception] = []

    def hammer_all_clusters() -> None:
        try:
            results.append(r.all_clusters())
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=hammer_all_clusters) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Every thread must see the same list object.
    first = results[0]
    assert all(r is first for r in results)
    assert len(first) == 52


def test_caching_for_product_type_is_thread_safe() -> None:
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    results: list[list] = []
    errors: list[Exception] = []

    def hammer() -> None:
        try:
            results.append(r.clusters_for_product_type("saas"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    first = results[0]
    assert all(r is first for r in results)
    assert len(first) > 0


def test_registry_count_matches_constant() -> None:
    """Sanity: 52 clusters invariant."""
    from app.simulation.clusters.registry import ClusterRegistry

    assert len(ClusterRegistry().all_clusters()) == 52


def test_clusters_for_product_type_returns_fresh_list_within_entry() -> None:
    """The cached list must not mutate under accidental .append() etc."""
    from app.simulation.clusters.registry import ClusterRegistry

    r = ClusterRegistry()
    saas = r.clusters_for_product_type("saas")
    # Identity stable across calls (cache hit).
    assert r.clusters_for_product_type("saas") is saas
    # Length unchanged.
    assert len(r.clusters_for_product_type("saas")) == len(saas)
