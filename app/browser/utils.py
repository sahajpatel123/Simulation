from app.simulation.clusters.registry import ClusterRegistry

_registry = ClusterRegistry()


def cluster_to_agent_profile(cluster_id: str) -> dict:
    try:
        c = _registry.get_cluster(cluster_id)
        return {
            **c.base_traits,
            "device_primary": c.demographic_profile.get("device_primary", "mobile"),
            "geography": c.demographic_profile.get("geography", "metro"),
            "age_bracket": c.demographic_profile.get("age_bracket", "25-35"),
            "cluster_id": cluster_id,
        }
    except Exception:
        return {"device_primary": "mobile", "patience_score": 0.5, "trust": 0.5}
