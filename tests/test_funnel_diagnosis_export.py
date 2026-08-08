"""Unit tests for the funnel-diagnosis export helpers.

Covers the pure CSV / JSON / Markdown rendering in
``app.simulation.funnel_diagnosis_export``. These run without DB, Redis,
or Celery so they are safe to execute anywhere.
"""
from __future__ import annotations

from app.schemas.funnel_diagnosis import (
    ClusterDrag,
    DiagnosisRecommendation,
    DropTriggerCount,
    FunnelDiagnosisOut,
    StageDiagnosis,
)
from app.simulation.funnel_diagnosis_export import (
    funnel_diagnosis_to_csv,
    funnel_diagnosis_to_json,
    funnel_diagnosis_to_markdown,
)


def _sample_diagnosis() -> FunnelDiagnosisOut:
    """A representative funnel diagnosis with all major sections populated."""
    return FunnelDiagnosisOut(
        simulation_id=7,
        project_id=3,
        status="COMPLETED",
        overall_conversion=0.031,
        total_agents=10000,
        converted_agents=310,
        primary_bottleneck="DECIDE",
        bottleneck_severity="CRITICAL",
        health_score=52,
        recoverable_conversion=0.045,
        primary_failure_domain="PRICING",
        product_type_detected="saas",
        signal_quality=0.82,
        stages=[
            StageDiagnosis(
                stage="ARRIVE",
                agent_count=10000,
                entry_rate=1.0,
                drop_off_rate=0.14,
                agents_lost=1400,
                healthy_drop_off=0.13,
                delta_from_healthy=0.01,
                severity="INFO",
                primary_domain="ACQUISITION",
            ),
            StageDiagnosis(
                stage="DECIDE",
                agent_count=2500,
                entry_rate=0.31,
                drop_off_rate=0.72,
                agents_lost=1800,
                healthy_drop_off=0.55,
                delta_from_healthy=0.17,
                severity="CRITICAL",
                primary_domain="PRICING",
                recommended_architects=["PricingArchitect", "TrustArchitect"],
                is_primary_bottleneck=True,
            ),
        ],
        cluster_drag=[
            ClusterDrag(
                cluster_id="tier3_first_time_app_user",
                cluster_name="Tier 3 First-Time App User",
                conversion_rate=0.012,
                population_weight=0.22,
                lost_conversion_share=0.217,
                primary_drop_trigger="price_sensitivity",
                mean_drop_state="DECIDE",
            )
        ],
        drop_triggers=[
            DropTriggerCount(
                trigger="price_sensitivity",
                cluster_count=4,
                agents_affected=1800,
                mean_conversion=0.02,
            )
        ],
        recommendations=[
            DiagnosisRecommendation(
                priority=1,
                stage="DECIDE",
                domain="PRICING",
                severity="CRITICAL",
                title="Fix DECIDE bottleneck (PRICING)",
                rationale=(
                    "DECIDE drop-off is 72% (healthy ≤ 55%; Δ=+17%). "
                    "Approximately 1800 simulated agents leave here."
                ),
                estimated_lift=0.014,
                architects=["PricingArchitect"],
                related_clusters=["tier3_first_time_app_user"],
            )
        ],
        meta={"stages_source": "stage_metrics", "recovery_fraction": 0.35},
    )


def test_csv_contains_all_sections():
    csv_text = funnel_diagnosis_to_csv(_sample_diagnosis())
    assert "Funnel Diagnosis Summary" in csv_text
    assert "Stage Diagnosis" in csv_text
    assert "Cluster Drag" in csv_text
    assert "Drop Triggers" in csv_text
    assert "Recommendations" in csv_text
    assert "Meta" in csv_text


def test_csv_escapes_formula_cells():
    payload = _sample_diagnosis()
    payload.primary_failure_domain = "=HYPERLINK(https://evil.example)"
    csv_text = funnel_diagnosis_to_csv(payload)
    assert "'=HYPERLINK(https://evil.example)" in csv_text


def test_csv_handles_empty_payload():
    csv_text = funnel_diagnosis_to_csv(
        FunnelDiagnosisOut(simulation_id=1, project_id=1)
    )
    assert "Funnel Diagnosis Summary" in csv_text
    # Empty sections are still labelled so the download is self-describing.
    assert "Stage Diagnosis" in csv_text
    assert "Recommendations" in csv_text


def test_json_round_trips_fields():
    payload = _sample_diagnosis()
    rendered = funnel_diagnosis_to_json(payload, metadata={"simulation_id": 7})
    parsed = __import__("json").loads(rendered)
    assert parsed["metadata"]["simulation_id"] == 7
    assert parsed["funnel_diagnosis"]["primary_bottleneck"] == "DECIDE"
    assert parsed["funnel_diagnosis"]["health_score"] == 52


def test_markdown_summary_and_recommendations():
    payload = _sample_diagnosis()
    md = funnel_diagnosis_to_markdown(
        payload,
        simulation_id=7,
        project_id=3,
        project_name="D2C Hardware",
        metadata={"generated_at": "2026-08-08T12:00:00Z"},
    )
    assert "# D2C Hardware — Funnel Diagnosis" in md
    assert "| Overall conversion | 3.10% |" in md
    assert "| Primary bottleneck | DECIDE |" in md
    assert "| Health score | 52/100 |" in md
    assert "estimated lift 1.40%" in md
    assert "Simulation 7" in md


def test_markdown_escapes_table_cells():
    payload = _sample_diagnosis()
    payload.primary_failure_domain = "PRIC|ING"
    md = funnel_diagnosis_to_markdown(payload)
    assert "PRIC\\|ING" in md
    assert "\nPRIC|ING" not in md


def test_markdown_handles_empty_payload():
    md = funnel_diagnosis_to_markdown(
        FunnelDiagnosisOut(simulation_id=1, project_id=1)
    )
    assert "# TheCee — Funnel Diagnosis" in md
    assert "No stage metrics are available." in md
    assert "No recommendations are currently available." in md


def test_markdown_accepts_plain_dict_payload():
    md = funnel_diagnosis_to_markdown(
        {
            "simulation_id": 7,
            "project_id": 3,
            "overall_conversion": 0.031,
            "total_agents": 10000,
            "converted_agents": 310,
            "primary_bottleneck": "DECIDE",
            "bottleneck_severity": "CRITICAL",
            "health_score": 52,
            "stages": [],
            "recommendations": [],
        },
        simulation_id=7,
        project_id=3,
        metadata={},
    )
    assert "| Overall conversion | 3.10% |" in md
    assert "Simulation 7" in md
    assert "Project 3" in md
