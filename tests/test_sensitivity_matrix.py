from app.simulation.sensitivity_matrix import (
    compute_simulation_sensitivity_matrix,
    SENSITIVITY_TRAITS,
)


def test_compute_simulation_sensitivity_matrix_empty():
    res = compute_simulation_sensitivity_matrix(None)
    assert res["overall_elasticity_score"] >= 0.0
    assert len(res["trait_sensitivities"]) == len(SENSITIVITY_TRAITS)
    assert "narrative" in res
    assert isinstance(res["leverage_traits"], list)


def test_compute_simulation_sensitivity_matrix_with_clusters():
    results = {
        "stage_conversions": {
            "PURCHASE": 0.15,
        },
        "cluster_breakdown": {
            "c1": {
                "weight": 0.6,
                "traits": {"price_sensitivity": 0.8, "trust": 0.3},
                "conversion_rate": 0.12,
            },
            "c2": {
                "weight": 0.4,
                "traits": {"price_sensitivity": 0.2, "trust": 0.9},
                "conversion_rate": 0.20,
            },
        },
    }
    res = compute_simulation_sensitivity_matrix(results, delta_step=0.1)
    assert res["baseline_conversion"] == 0.15
    assert len(res["trait_sensitivities"]) == len(SENSITIVITY_TRAITS)
    assert len(res["recommendations"]) >= 1
