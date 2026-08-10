"""Pure-helper tests for the per-project risk register digest."""
from __future__ import annotations

from app.schemas.risk_register import RiskRegisterOut
from app.simulation.risk_register import (
    MAX_RISKS,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_LOW,
    RISK_LEVEL_MODERATE,
    RISK_LEVEL_SEVERE,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    SOURCE_COMPETITIVE,
    SOURCE_PREMORTEM,
    SOURCE_SIMULATION,
    SOURCE_STRESS_TEST,
    build_risk_register,
)


def _premortem(*modes: dict) -> dict:
    return {"failure_modes": list(modes)}


def _stress(*rows: dict) -> dict:
    return {"sensitivity_matrix": list(rows)}


def _competitive(*competitors: dict, position: str = "MODERATE") -> dict:
    return {
        "competitors": list(competitors),
        "overall_competitive_position": position,
        "gap_analysis": {
            "recommended_counter_moves": ["Ship the missing integration"],
        },
    }


def _finding(
    *,
    severity: str = "WARNING",
    conversion_impact: float = 0.05,
    architect: str = "PricingArchitect",
) -> dict:
    return {
        "architect_name": architect,
        "cluster_id": "a",
        "cluster_name": "Cluster A",
        "finding": "Pricing is above the cluster's willingness to pay",
        "metric_affected": "will_pay_probability",
        "actual_value": 0.10,
        "healthy_benchmark": 0.40,
        "conversion_impact": conversion_impact,
        "recommended_action": "Introduce a lower-priced tier",
        "severity": severity,
    }


def test_empty_register() -> None:
    out = build_risk_register(project_id=7)
    assert out["project_id"] == 7
    assert out["total_risks"] == 0
    assert out["top_risk_count"] == 0
    assert out["overall_risk_level"] == RISK_LEVEL_LOW
    assert out["top_risk_score"] is None
    assert out["severity_breakdown"] == {
        "CRITICAL": 0,
        "MAJOR": 0,
        "MINOR": 0,
        "INFO": 0,
    }
    assert out["source_breakdown"] == {
        SOURCE_PREMORTEM: 0,
        SOURCE_STRESS_TEST: 0,
        SOURCE_COMPETITIVE: 0,
        SOURCE_SIMULATION: 0,
    }
    assert out["risks"] == []
    assert "No risks identified" in out["narrative"]
    assert out["key_signals"][0]["label"] == "overall_risk_level"


def test_premortem_modes_are_parsed_and_scored() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Regulatory approval stalls launch",
                "description": "Certification takes 9 months",
                "severity": "CRITICAL",
                "probability": 0.5,
                "impact": 0.9,
                "intervention": "Start certification early",
            }
        ),
    )
    assert out["total_risks"] == 1
    item = out["risks"][0]
    assert item["source"] == SOURCE_PREMORTEM
    assert item["severity"] == SEVERITY_CRITICAL
    assert item["probability"] == 0.5
    assert item["impact"] == 0.9
    assert item["risk_score"] == 0.45
    assert item["recommended_action"] == "Start certification early"
    assert out["top_risk_score"] == 0.45
    assert out["overall_risk_level"] == RISK_LEVEL_HIGH
    assert "across 1 source(s)" in out["narrative"]


def test_premortem_missing_probability_uses_severity_fallback() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Unclear",
                "severity": "MEDIUM",
                "impact": 0.4,
            }
        ),
    )
    item = out["risks"][0]
    # MEDIUM -> MINOR -> default probability 0.30.
    assert item["probability"] == 0.3
    assert item["risk_score"] == 0.12


def test_stress_kill_shot_ranks_critical() -> None:
    out = build_risk_register(
        project_id=1,
        stress_test_data=_stress(
            {
                "assumption_text": "Users will pay for premium",
                "sensitivity": "CRITICAL",
                "baseline_conversion": 0.04,
                "stressed_conversion": 0.008,
                "delta": -0.032,
                "delta_pct": -45.0,
                "kill_shot": True,
                "kill_shot_prob": 0.75,
                "recommendation": "Run a landing-page A/B test",
            }
        ),
    )
    item = out["risks"][0]
    assert item["source"] == SOURCE_STRESS_TEST
    assert item["severity"] == SEVERITY_CRITICAL
    assert item["risk_score"] == 0.675
    assert item["impact"] == 0.9
    assert "collapse conversion" in item["description"]
    assert item["recommended_action"] == "Run a landing-page A/B test"
    assert item["metric"] == "conversion_delta_pct"
    assert out["overall_risk_level"] == RISK_LEVEL_HIGH


def test_stress_kill_shot_handles_string_booleans() -> None:
    false_string = build_risk_register(
        project_id=1,
        stress_test_data=_stress(
            {
                "assumption_text": "Onboarding is self-serve",
                "sensitivity": "MEDIUM",
                "delta": -0.004,
                "delta_pct": -10.0,
                "kill_shot": "false",
                "kill_shot_prob": 0.2,
            }
        ),
    )
    assert false_string["risks"][0]["severity"] == SEVERITY_MINOR
    assert false_string["risks"][0]["risk_score"] < 0.2

    true_string = build_risk_register(
        project_id=1,
        stress_test_data=_stress(
            {
                "assumption_text": "Users will pay for premium",
                "sensitivity": "CRITICAL",
                "delta": -0.04,
                "delta_pct": -100.0,
                "kill_shot": "true",
                "kill_shot_prob": 0.75,
            }
        ),
    )
    assert true_string["risks"][0]["severity"] == SEVERITY_CRITICAL
    assert true_string["risks"][0]["risk_score"] == 0.75


def test_stress_partial_kill_shot_maps_to_major() -> None:
    out = build_risk_register(
        project_id=1,
        stress_test_data=_stress(
            {
                "assumption_text": "Onboarding is self-serve",
                "sensitivity": "MEDIUM",
                "baseline_conversion": 0.04,
                "stressed_conversion": 0.022,
                "delta": -0.019,
                "delta_pct": -47.5,
                "kill_shot": False,
                "kill_shot_prob": 0.4,
                "recommendation": "Add guided onboarding",
            }
        ),
    )
    item = out["risks"][0]
    assert item["severity"] == SEVERITY_MAJOR
    assert item["risk_score"] > 0.0


def test_stress_legacy_kill_shots_without_matrix_are_parsed() -> None:
    out = build_risk_register(
        project_id=1,
        stress_test_data={
            "kill_shots": [
                {
                    "assumption_text": "Legacy assumption",
                    "sensitivity": "HIGH",
                    "delta": -0.04,
                    "delta_pct": -100.0,
                    "kill_shot": True,
                    "kill_shot_prob": 0.8,
                    "recommendation": "Micro-test it",
                }
            ]
        },
    )
    assert out["total_risks"] == 1
    item = out["risks"][0]
    assert item["source"] == SOURCE_STRESS_TEST
    assert item["severity"] == SEVERITY_CRITICAL
    assert item["risk_score"] == 0.8


def test_competitive_threats_are_scored_by_threat_and_position() -> None:
    out = build_risk_register(
        project_id=1,
        competitive_data=_competitive(
            {
                "name": "BigCo",
                "threat_level": "HIGH",
                "positioning": "Enterprise incumbent",
                "weaknesses": ["Slow support", "No mobile app"],
            },
            {
                "name": "TinyCo",
                "threat_level": "LOW",
                "positioning": "Niche tool",
                "weaknesses": [],
            },
            position="CHALLENGING",
        ),
    )
    assert out["total_risks"] == 2
    big, tiny = out["risks"]
    assert big["source"] == SOURCE_COMPETITIVE
    assert big["severity"] == SEVERITY_MAJOR
    assert big["risk_score"] == 0.5625  # 0.75 * 0.75
    assert big["recommended_action"] == "Ship the missing integration"
    assert "Slow support" in big["description"]
    assert tiny["severity"] == SEVERITY_INFO
    assert big["risk_score"] > tiny["risk_score"]


def test_findings_are_parsed_with_category_and_impact() -> None:
    out = build_risk_register(
        project_id=1,
        findings=[_finding()],
    )
    item = out["risks"][0]
    assert item["source"] == SOURCE_SIMULATION
    assert item["severity"] == SEVERITY_MAJOR  # WARNING -> MAJOR
    assert item["category"] == "PRICING"
    assert item["probability"] == 0.55
    assert item["impact"] == 0.25  # conversion_impact 0.05 * 5
    assert item["risk_score"] == 0.1375
    assert item["metric"] == "will_pay_probability"
    assert "Cluster A" in item["description"]
    assert item["recommended_action"] == "Introduce a lower-priced tier"


def test_negative_finding_conversion_impact_uses_absolute_magnitude() -> None:
    negative = _finding(conversion_impact=-0.05)
    out = build_risk_register(project_id=1, findings=[negative])
    item = out["risks"][0]
    assert item["impact"] == 0.25
    assert item["risk_score"] == 0.1375


def test_unknown_finding_architect_falls_back_to_product() -> None:
    raw = _finding(architect="MysteryArchitect")
    out = build_risk_register(project_id=1, findings=[raw])
    assert out["risks"][0]["category"] == "PRODUCT"


def test_premortem_category_derived_from_title() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Regulatory approval stalls launch",
                "severity": "HIGH",
            },
            {
                "title": "Team velocity collapses",
                "severity": "MEDIUM",
            },
        ),
    )
    categories = {item["title"]: item["category"] for item in out["risks"]}
    assert categories["Regulatory approval stalls launch"] == "REGULATORY"
    assert categories["Team velocity collapses"] == "STRATEGIC"


def test_register_is_sorted_by_score_then_severity() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Medium risk",
                "severity": "CRITICAL",
                "probability": 0.4,
                "impact": 0.5,
            },
            {
                "title": "Big risk",
                "severity": "HIGH",
                "probability": 0.8,
                "impact": 0.9,
            },
            {
                "title": "Same score higher severity",
                "severity": "CRITICAL",
                "probability": 0.5,
                "impact": 0.9,
            },
            {
                "title": "Same score lower severity",
                "severity": "MEDIUM",
                "probability": 0.5,
                "impact": 0.9,
            },
        ),
    )
    titles = [item["title"] for item in out["risks"]]
    assert titles[0] == "Big risk"
    # 0.45 tie: CRITICAL sorts before MINOR.
    assert titles[1] == "Same score higher severity"
    assert titles[2] == "Same score lower severity"
    assert titles[3] == "Medium risk"


def test_register_dedupes_exact_duplicates() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Same failure",
                "severity": "HIGH",
                "probability": 0.5,
                "impact": 0.8,
            },
            {
                "title": "Same failure",
                "severity": "HIGH",
                "probability": 0.5,
                "impact": 0.8,
            },
        ),
    )
    assert out["total_risks"] == 1


def test_register_dedupe_keeps_higher_risk_variant() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Same failure",
                "severity": "MINOR",
                "probability": 0.2,
                "impact": 0.3,
            },
            {
                "title": "Same failure",
                "severity": "CRITICAL",
                "probability": 0.8,
                "impact": 0.9,
            },
        ),
    )
    assert out["total_risks"] == 1
    item = out["risks"][0]
    assert item["severity"] == SEVERITY_CRITICAL
    assert item["risk_score"] == 0.72


def test_register_caps_ranked_list_but_counts_all() -> None:
    modes = [
        {
            "title": f"Failure {index}",
            "severity": "CRITICAL",
            "probability": 0.8,
            "impact": 0.9,
        }
        for index in range(MAX_RISKS + 5)
    ]
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(*modes),
    )
    assert out["total_risks"] == MAX_RISKS + 5
    assert out["top_risk_count"] == MAX_RISKS
    assert len(out["risks"]) == MAX_RISKS
    assert out["severity_breakdown"] == {
        SEVERITY_CRITICAL: MAX_RISKS + 5,
        SEVERITY_MAJOR: 0,
        SEVERITY_MINOR: 0,
        SEVERITY_INFO: 0,
    }
    assert out["source_breakdown"] == {
        SOURCE_PREMORTEM: MAX_RISKS + 5,
        SOURCE_STRESS_TEST: 0,
        SOURCE_COMPETITIVE: 0,
        SOURCE_SIMULATION: 0,
    }


def test_overall_risk_level_thresholds() -> None:
    severe = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Fatal",
                "severity": "CRITICAL",
                "probability": 0.9,
                "impact": 0.9,
            }
        ),
    )
    assert severe["overall_risk_level"] == RISK_LEVEL_SEVERE

    moderate = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Watch",
                "severity": "CRITICAL",
                "probability": 0.3,
                "impact": 0.9,
            }
        ),
    )
    assert moderate["overall_risk_level"] == RISK_LEVEL_MODERATE

    low = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Minor",
                "severity": "LOW",
                "probability": 0.2,
                "impact": 0.4,
            }
        ),
    )
    assert low["overall_risk_level"] == RISK_LEVEL_LOW


def test_payload_serialises_via_schema() -> None:
    payload = build_risk_register(
        project_id=3,
        premortem_data=_premortem(
            {
                "title": "Certification delay",
                "severity": "CRITICAL",
                "probability": 0.5,
                "impact": 0.9,
            }
        ),
        findings=[_finding()],
    )
    out = RiskRegisterOut(**payload)
    assert out.project_id == 3
    assert out.total_risks == 2
    assert out.overall_risk_level == RISK_LEVEL_HIGH
    assert out.risks[0].risk_score >= out.risks[1].risk_score
    assert out.narrative


def test_narrative_mentions_top_risk_and_action() -> None:
    out = build_risk_register(
        project_id=1,
        premortem_data=_premortem(
            {
                "title": "Certification delay",
                "severity": "CRITICAL",
                "probability": 0.8,
                "impact": 0.9,
                "intervention": "Start certification now",
            }
        ),
    )
    assert "Certification delay" in out["narrative"]
    assert "Start certification now" in out["narrative"]
