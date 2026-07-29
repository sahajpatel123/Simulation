import pytest
from app.simulation.anomaly_detector import (
    detect_simulation_anomalies,
    SIGNAL_OK,
    SIGNAL_WATCH,
    SIGNAL_CRITICAL,
)


def test_detect_simulation_anomalies_empty():
    res = detect_simulation_anomalies(None)
    assert res["anomaly_score"] == 0.0
    assert res["status"] == "NORMAL"
    assert res["anomalies_count"] == 0
    assert res["anomalies"] == []
    assert res["stage_spikes"] == []
    assert res["cluster_outliers"] == []
    assert res["recommendations"] == []


def test_detect_simulation_anomalies_clean():
    results = {
        "stage_conversions": {
            "ARRIVE": 1.0,
            "BROWSE": 0.8,
            "CONSIDER": 0.6,
            "DECIDE": 0.4,
            "PURCHASE": 0.2,
        },
        "cluster_breakdown": {
            "c1": {"conversion_rate": 0.20},
            "c2": {"conversion_rate": 0.22},
            "c3": {"conversion_rate": 0.18},
            "c4": {"conversion_rate": 0.21},
        },
    }
    res = detect_simulation_anomalies(results)
    assert res["anomaly_score"] == 0.0
    assert res["status"] == "NORMAL"
    assert res["anomalies_count"] == 0
    assert res["recommendations"] == []


def test_detect_simulation_anomalies_stage_dropoff_spike():
    results = {
        "stage_conversions": {
            "arrive": 1.0,
            "browse": 0.9,
            "consider": 0.1,  # 88.8% dropoff spike from BROWSE to CONSIDER
            "decide": 0.08,
            "purchase": 0.05,
        }
    }
    res = detect_simulation_anomalies(results)
    assert res["anomalies_count"] >= 1
    assert len(res["stage_spikes"]) == 1
    spike = res["stage_spikes"][0]
    assert spike["stage_from"] == "BROWSE"
    assert spike["stage_to"] == "CONSIDER"
    assert spike["severity"] == SIGNAL_CRITICAL
    assert res["status"] in ("WATCH", "CRITICAL")
    assert len(res["recommendations"]) >= 1
    assert "BROWSE -> CONSIDER" in res["recommendations"][0]["target"]


def test_detect_simulation_anomalies_cluster_outliers():
    results = {
        "cluster_breakdown": {
            "c1": {"conversion_rate": 0.10},
            "c2": {"conversion_rate": 0.11},
            "c3": {"conversion_rate": 0.10},
            "c4": {"conversion_rate": 0.09},
            "c5": {"conversion_rate": 0.85},  # extreme high outlier
            "c6": {"conversion_rate": 0.001}, # extreme low outlier
        }
    }
    res = detect_simulation_anomalies(results, outlier_z_threshold=1.8)
    assert len(res["cluster_outliers"]) >= 1
    assert res["anomaly_score"] > 0.0
    assert len(res["recommendations"]) >= 1
