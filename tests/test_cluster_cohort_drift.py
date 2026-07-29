import pytest
from app.simulation.cluster_cohort_drift import (
    compute_cluster_cohort_drift,
    SIGNAL_OK,
    SIGNAL_WATCH,
    SIGNAL_CRITICAL,
)


def test_cluster_cohort_drift_empty():
    res = compute_cluster_cohort_drift(None, None)
    assert res["clusters_analyzed"] == 0
    assert res["overall_drift_score"] == 0.0
    assert res["stability_classification"] == "STABLE"
    assert res["top_drifting_clusters"] == []
    assert res["drift_by_cluster"] == {}


def test_cluster_cohort_drift_stable():
    baseline = {
        "cluster_breakdown": {
            "c1": {"conversion_rate": 0.10},
            "c2": {"conversion_rate": 0.20},
        }
    }
    latest = {
        "cluster_breakdown": {
            "c1": {"conversion_rate": 0.101},
            "c2": {"conversion_rate": 0.199},
        }
    }
    res = compute_cluster_cohort_drift(baseline, latest)
    assert res["clusters_analyzed"] == 2
    assert res["stability_classification"] == "STABLE"
    assert res["drift_by_cluster"]["c1"]["direction"] in ("EXPANDING", "NEUTRAL")
    assert res["drift_by_cluster"]["c1"]["severity"] == SIGNAL_OK


def test_cluster_cohort_drift_high_drift():
    baseline = {
        "cluster_breakdown": {
            "c1": {"conversion_rate": 0.30},
            "c2": {"conversion_rate": 0.40},
        }
    }
    latest = {
        "cluster_breakdown": {
            "c1": {"conversion_rate": 0.05},  # -25% drop
            "c2": {"conversion_rate": 0.50},  # +10% gain
        }
    }
    res = compute_cluster_cohort_drift(baseline, latest)
    assert res["clusters_analyzed"] == 2
    assert res["stability_classification"] in ("MODERATE_DRIFT", "HIGH_DRIFT")
    assert len(res["top_drifting_clusters"]) == 2
    top1 = res["top_drifting_clusters"][0]
    assert top1["cluster_id"] == "c1"
    assert top1["direction"] == "CONTRACTING"
    assert top1["severity"] == SIGNAL_CRITICAL
