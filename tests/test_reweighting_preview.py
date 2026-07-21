"""
Tests for the reweighting-preview helpers and the
``GET /projects/{id}/reweighting-preview`` endpoint smoke-check
(cycle 32 reweighting-preview).

The preview is pure — these tests construct dict-shaped inputs and assert
the rollup output without spinning up the engine or DB.
"""
from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# summarise_rule_bundle
# ---------------------------------------------------------------------------


def _baseline() -> dict[str, float]:
    """Realistic-ish baseline cluster weights summing to ~1.0."""
    return {
        "metro_power_professional": 0.06,
        "urban_mid_income_saas_buyer": 0.05,
        "high_literacy_student_freemium_ceiling": 0.04,
        "value_hardware_buyer": 0.03,
        "tier3_first_time_app_user": 0.04,
        "smb_owner_self_serve": 0.04,
    }


def _names() -> dict[str, str]:
    return {
        "metro_power_professional": "Metro Power Professional",
        "urban_mid_income_saas_buyer": "Urban Mid-Income SaaS Buyer",
        "high_literacy_student_freemium_ceiling": "High-Literacy Student",
        "value_hardware_buyer": "Value Hardware Buyer",
        "tier3_first_time_app_user": "Tier-3 First-Time App User",
        "smb_owner_self_serve": "SMB Owner (Self-Serve)",
    }


def test_summarise_rule_bundle_default_rule() -> None:
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    final = dict(baseline)  # no rule → identical weights
    out = summarise_rule_bundle(
        rule_key="DEFAULT",
        rules={"suppress": [], "amplify": {}},
        final_weights=final,
        baseline_weights=baseline,
        cluster_names=_names(),
    )
    assert out["rule_bundle"] == "DEFAULT"
    assert out["suppressed"] == []
    assert out["amplified"] == []
    assert out["baseline_weight_sum"] == pytest_sum(baseline.values())
    assert out["total_weight_sum"] == pytest_sum(final.values())
    assert "DEFAULT" in out["message"] or "baseline" in out["message"]


def test_summarise_rule_bundle_with_suppress_and_amplify() -> None:
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    rules = {
        "suppress": ["tier3_first_time_app_user"],
        "amplify": {
            "smb_owner_self_serve": 2.5,
            "urban_mid_income_saas_buyer": 1.5,
        },
    }
    final = {
        "metro_power_professional": 0.06,
        "urban_mid_income_saas_buyer": 0.075,  # 0.05 * 1.5
        "high_literacy_student_freemium_ceiling": 0.04,
        "value_hardware_buyer": 0.03,
        "tier3_first_time_app_user": 0.0,
        "smb_owner_self_serve": 0.10,  # 0.04 * 2.5
    }
    out = summarise_rule_bundle(
        rule_key="SAAS_B2B_SMB",
        rules=rules,
        final_weights=final,
        baseline_weights=baseline,
        cluster_names=_names(),
    )
    assert out["rule_bundle"] == "SAAS_B2B_SMB"
    assert out["suppressed"] == ["tier3_first_time_app_user"]
    # Two amplified clusters; sorted by final_weight desc → SMB first.
    assert [r["cluster_id"] for r in out["amplified"]] == [
        "smb_owner_self_serve",
        "urban_mid_income_saas_buyer",
    ]
    assert out["amplified"][0]["multiplier"] == 2.5
    assert out["amplified"][0]["final_weight"] == pytest_close(0.10)


def test_summarise_rule_bundle_drops_zero_weight_amplified() -> None:
    """If the final weight is 0, skip the amplification row even though the
    rule listed the cluster."""
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    rules = {
        "suppress": [],
        "amplify": {
            "value_hardware_buyer": 4.0,
            "smb_owner_self_serve": 2.0,
        },
    }
    final = {
        "metro_power_professional": 0.06,
        "urban_mid_income_saas_buyer": 0.05,
        "high_literacy_student_freemium_ceiling": 0.04,
        "value_hardware_buyer": 0.0,  # zeroed out by another rule
        "tier3_first_time_app_user": 0.04,
        "smb_owner_self_serve": 0.08,
    }
    out = summarise_rule_bundle(
        rule_key="CONSUMER_HARDWARE_LOW_PRICE",
        rules=rules,
        final_weights=final,
        baseline_weights=baseline,
        cluster_names=_names(),
    )
    amplified_ids = [r["cluster_id"] for r in out["amplified"]]
    assert "value_hardware_buyer" not in amplified_ids
    assert "smb_owner_self_serve" in amplified_ids


def test_summarise_rule_bundle_top_clusters_have_source_tag() -> None:
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    rules = {
        "suppress": ["high_literacy_student_freemium_ceiling"],
        "amplify": {"smb_owner_self_serve": 3.0},
    }
    final = {
        "metro_power_professional": 0.06,
        "urban_mid_income_saas_buyer": 0.05,
        "high_literacy_student_freemium_ceiling": 0.0,
        "value_hardware_buyer": 0.03,
        "tier3_first_time_app_user": 0.04,
        "smb_owner_self_serve": 0.12,
    }
    out = summarise_rule_bundle(
        rule_key="SAAS_ENTERPRISE",
        rules=rules,
        final_weights=final,
        baseline_weights=baseline,
        cluster_names=_names(),
    )
    by_id = {c["cluster_id"]: c for c in out["top_clusters"]}
    by_bottom = {c["cluster_id"]: c for c in out["bottom_clusters"]}
    assert by_id["smb_owner_self_serve"]["source"] == "amplified"
    assert by_bottom["high_literacy_student_freemium_ceiling"]["source"] == "suppressed"
    assert by_id["metro_power_professional"]["source"] == "registry"


def test_summarise_rule_bundle_top_n_capped() -> None:
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    out = summarise_rule_bundle(
        rule_key="DEFAULT",
        rules={"suppress": [], "amplify": {}},
        final_weights=baseline,
        baseline_weights=baseline,
        cluster_names=_names(),
        top_n=2,
        bottom_n=2,
    )
    assert len(out["top_clusters"]) == 2
    assert len(out["bottom_clusters"]) == 2


def test_summarise_rule_bundle_handles_missing_cluster_names() -> None:
    """Cluster names fallback to cluster_id when unknown."""
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    final = dict(baseline)
    out = summarise_rule_bundle(
        rule_key="DEFAULT",
        rules={"suppress": [], "amplify": {}},
        final_weights=final,
        baseline_weights=baseline,
        cluster_names={},  # no name mapping
    )
    # Every cluster falls back to its id.
    for c in out["top_clusters"]:
        assert c["cluster_name"] == c["cluster_id"]


def test_summarise_rule_bundle_message_distinguishes_default() -> None:
    from app.simulation.reweighting_preview import summarise_rule_bundle

    baseline = _baseline()
    final = dict(baseline)
    default_msg = summarise_rule_bundle(
        rule_key="DEFAULT",
        rules={"suppress": [], "amplify": {}},
        final_weights=final,
        baseline_weights=baseline,
        cluster_names={},
    )["message"]
    rule_msg = summarise_rule_bundle(
        rule_key="SAAS_ENTERPRISE",
        rules={"suppress": ["a"], "amplify": {"b": 2.0}},
        final_weights={"a": 0.0, "b": 0.1, "c": 0.9},
        baseline_weights=baseline,
        cluster_names={},
    )["message"]
    assert "DEFAULT" in default_msg or "baseline" in default_msg
    assert "SAAS_ENTERPRISE" in rule_msg
    assert "1 suppressed" in rule_msg
    assert "1 amplified" in rule_msg


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------


def test_reweighting_preview_out_serialises_full_payload() -> None:
    from app.schemas.reweighting import ClusterWeight, ReweightingPreviewOut

    out = ReweightingPreviewOut(
        project_id=42,
        rule_bundle="SAAS_B2B_SMB",
        product_type="saas",
        aov=99.0,
        geography="METRO",
        segment="SMB",
        age_target="25-34",
        suppressed=["student_cluster"],
        amplified=[
            {
                "cluster_id": "smb_owner_self_serve",
                "cluster_name": "SMB Owner",
                "multiplier": 2.5,
                "final_weight": 0.10,
            }
        ],
        top_clusters=[
            ClusterWeight(
                cluster_id="smb_owner_self_serve",
                cluster_name="SMB Owner",
                population_weight=0.10,
                source="amplified",
            )
        ],
        bottom_clusters=[
            ClusterWeight(
                cluster_id="student_cluster",
                cluster_name="Student Cluster",
                population_weight=0.0,
                source="suppressed",
            )
        ],
        total_weight_sum=1.0,
        baseline_weight_sum=1.0,
        message="Applied rule bundle 'SAAS_B2B_SMB'.",
    )
    dumped = out.model_dump()
    assert dumped["project_id"] == 42
    assert dumped["rule_bundle"] == "SAAS_B2B_SMB"
    assert dumped["amplified"][0]["multiplier"] == 2.5
    assert dumped["top_clusters"][0]["source"] == "amplified"
    assert dumped["bottom_clusters"][0]["population_weight"] == 0.0
    # Round-trip via JSON without errors.
    json.dumps(dumped)


def test_reweighting_preview_out_defaults_when_empty() -> None:
    from app.schemas.reweighting import ReweightingPreviewOut

    out = ReweightingPreviewOut(project_id=1)
    assert out.rule_bundle == ""
    assert out.product_type == ""
    assert out.suppressed == []
    assert out.amplified == []
    assert out.top_clusters == []
    assert out.bottom_clusters == []
    assert out.total_weight_sum == 1.0
    assert out.baseline_weight_sum == 1.0


# ---------------------------------------------------------------------------
# Route registration smoke check
# ---------------------------------------------------------------------------


def test_projects_router_exposes_reweighting_preview_endpoint() -> None:
    """Source-level check: the new route is declared and wired correctly."""
    src_path = "backend/app/api/v1/projects.py"
    with open(src_path) as fh:
        source = fh.read()
    assert '"/{project_id}/reweighting-preview"' in source
    assert "def get_reweighting_preview(" in source
    assert "response_model=ReweightingPreviewOut" in source
    # Engine + helper wired in.
    assert "ClusterReweightingEngine" in source
    assert "_summarise_rule_bundle" in source
    assert "REWEIGHTING_RULES" in source


def test_reweighting_preview_helper_is_pure() -> None:
    """summarise_rule_bundle must not import or call any DB / engine code."""
    import inspect

    from app.simulation import reweighting_preview

    source = inspect.getsource(reweighting_preview)
    forbidden_imports = ("sqlalchemy", "session", "SessionLocal", "get_db")
    for token in forbidden_imports:
        assert token.lower() not in source.lower(), (
            f"reweighting_preview.py must not depend on {token}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pytest_close(value: float, tol: float = 1e-9) -> float:
    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, float) and abs(other - value) < tol

        def __repr__(self) -> str:
            return f"≈{value}"

    return _Approx()  # type: ignore[return-value]


def pytest_sum(values, tol: float = 1e-6) -> float:
    target = round(sum(values), 6)

    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, (int, float)) and abs(other - target) < tol

        def __repr__(self) -> str:
            return f"≈{target}"

    return _Approx()  # type: ignore[return-value]
