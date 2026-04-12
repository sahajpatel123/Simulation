from sqlalchemy import text

from app.core.database import engine
from app.models import (
    Base,
    User,
    Project,
    Assumption,
    Environment,
    Simulation,
    Decision,
    Outcome,
)


def run_migrations():
    print("━━━ Running TheCee migrations ━━━")

    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
            print("✅ pgvector extension ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ pgvector skip: {e}")

    Base.metadata.create_all(bind=engine)
    print("✅ All tables created or verified")

    with engine.connect() as conn:
        for table, column, col_type in [
            ("users", "tier", "VARCHAR(50) DEFAULT 'free'"),
            ("projects", "prototype_html", "TEXT"),
            ("projects", "funnel_graph_json", "TEXT"),
            ("projects", "premortem_json", "JSONB"),
            ("projects", "stress_test_json", "JSONB"),
            ("projects", "interventions_json", "JSONB"),
            ("projects", "competitive_json", "JSONB"),
            ("simulations", "results_json", "TEXT"),
            ("simulations", "confidence_score", "FLOAT"),
            ("simulations", "task_id", "VARCHAR(255)"),
            ("simulations", "error_message", "TEXT"),
            ("simulations", "consumer_volume", "INTEGER DEFAULT 10000"),
            ("decisions", "title", "VARCHAR(200)"),
            ("decisions", "status", "VARCHAR(50) DEFAULT 'PENDING'"),
            ("decisions", "results_json", "JSONB"),
            ("decisions", "task_id", "VARCHAR(255)"),
            ("decisions", "error_message", "TEXT"),
            ("outcomes", "actual_dau", "FLOAT"),
            ("outcomes", "actual_nps", "FLOAT"),
            ("outcomes", "days_since_launch", "INTEGER DEFAULT 30"),
            ("outcomes", "predicted_conversion_rate", "FLOAT"),
            ("outcomes", "predicted_mrr", "FLOAT"),
            ("outcomes", "simulation_id", "INTEGER"),
            ("outcomes", "variance_conversion", "FLOAT"),
            ("outcomes", "variance_mrr", "FLOAT"),
            ("outcomes", "variance_cac", "FLOAT"),
            ("outcomes", "variance_churn", "FLOAT"),
            ("outcomes", "calibration_score", "FLOAT"),
            ("prototypes", "html_content", "TEXT"),
            ("prototypes", "funnel_graph_json", "TEXT"),
            ("environments", "consumer_volume", "INTEGER DEFAULT 10000"),
            ("environments", "growth_rate_per_month", "FLOAT DEFAULT 5.0"),
            ("environments", "average_order_value", "FLOAT DEFAULT 999.0"),
            ("environments", "price_sensitivity", "FLOAT DEFAULT 0.5"),
            ("environments", "market_maturity", "FLOAT DEFAULT 0.3"),
            ("environments", "scenario_type", "VARCHAR(50)"),
            ("environments", "manual_params_json", "JSONB"),
            ("environments", "trend_data_json", "JSONB"),
        ]:
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};")
                )
                conn.commit()
            except Exception:
                conn.rollback()

        # Ensure simulations.results_json matches current SQLAlchemy JSONB model.
        try:
            conn.execute(
                text(
                    """
                    ALTER TABLE simulations
                    ALTER COLUMN results_json
                    TYPE JSONB
                    USING CASE
                        WHEN results_json IS NULL THEN NULL
                        ELSE results_json::jsonb
                    END;
                    """
                )
            )
            conn.commit()
        except Exception:
            conn.rollback()

        # Step 36a: add signal_quality and claim_confidence_distribution to simulations
        for column, col_type in [
            ("signal_quality", "FLOAT"),
            ("claim_confidence_distribution", "JSONB"),
        ]:
            try:
                conn.execute(
                    text(f"ALTER TABLE simulations ADD COLUMN IF NOT EXISTS {column} {col_type};")
                )
                conn.commit()
            except Exception:
                conn.rollback()

    # Step 36a: learning system tables
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cluster_parameters (
                    id SERIAL PRIMARY KEY,
                    cluster_id VARCHAR(100) NOT NULL,
                    trait_name VARCHAR(100) NOT NULL,
                    base_value FLOAT NOT NULL,
                    calibrated_value FLOAT NOT NULL,
                    calibration_count INTEGER DEFAULT 0,
                    effective_sample_count FLOAT DEFAULT 0.0,
                    last_updated TIMESTAMP DEFAULT NOW(),
                    calibration_source VARCHAR(50) DEFAULT 'AUTHORED',
                    UNIQUE(cluster_id, trait_name)
                );
            """))
            conn.commit()
            print("✅ cluster_parameters ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ cluster_parameters skip: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cluster_run_summaries (
                    id SERIAL PRIMARY KEY,
                    simulation_id INTEGER REFERENCES simulations(id),
                    cluster_id VARCHAR(100) NOT NULL,
                    agents_assigned INTEGER NOT NULL,
                    agents_converted INTEGER NOT NULL,
                    conversion_rate FLOAT NOT NULL,
                    drop_state_distribution JSONB NOT NULL,
                    mean_drop_state VARCHAR(50),
                    architect_scores JSONB NOT NULL,
                    primary_drop_trigger VARCHAR(100),
                    signal_quality FLOAT DEFAULT 0.0,
                    claim_confidence_distribution JSONB,
                    product_type VARCHAR(50),
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """))
            conn.commit()
            print("✅ cluster_run_summaries ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ cluster_run_summaries skip: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS architect_corrections (
                    id SERIAL PRIMARY KEY,
                    architect_name VARCHAR(100) NOT NULL,
                    product_type VARCHAR(50) NOT NULL,
                    product_attribute VARCHAR(200) NOT NULL,
                    cluster_id VARCHAR(100) NOT NULL,
                    correction_scalar FLOAT NOT NULL DEFAULT 1.0,
                    confidence_weight FLOAT NOT NULL DEFAULT 0.0,
                    sample_count INTEGER DEFAULT 0,
                    effective_sample_count FLOAT DEFAULT 0.0,
                    scope VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    last_updated TIMESTAMP DEFAULT NOW(),
                    UNIQUE(architect_name, product_type, product_attribute, cluster_id)
                );
            """))
            conn.commit()
            print("✅ architect_corrections ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ architect_corrections skip: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS founder_outcomes (
                    id SERIAL PRIMARY KEY,
                    simulation_id INTEGER REFERENCES simulations(id),
                    project_id INTEGER REFERENCES projects(id),
                    days_since_launch INTEGER NOT NULL,
                    actual_conversion_rate FLOAT NOT NULL,
                    actual_drop_at_browse_pct FLOAT,
                    actual_drop_at_consider_pct FLOAT,
                    actual_drop_at_decide_pct FLOAT,
                    primary_failure_reason VARCHAR(50),
                    product_changed_since_sim BOOLEAN DEFAULT FALSE,
                    pricing_changed BOOLEAN DEFAULT FALSE,
                    target_market_changed BOOLEAN DEFAULT FALSE,
                    data_confidence VARCHAR(20) NOT NULL DEFAULT 'ESTIMATED',
                    validated BOOLEAN DEFAULT FALSE,
                    signal_quality_at_run FLOAT,
                    learning_weight FLOAT DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """))
            conn.commit()
            print("✅ founder_outcomes ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ founder_outcomes skip: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_claim_accuracy_profiles (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    architect_name VARCHAR(100) NOT NULL,
                    ema_delta FLOAT DEFAULT 0.0,
                    reliability_score FLOAT DEFAULT 0.0,
                    sample_count INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, architect_name)
                );
            """))
            conn.commit()
            print("✅ user_claim_accuracy_profiles ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ user_claim_accuracy_profiles skip: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_market_blindspots (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    blindspot_type VARCHAR(50) NOT NULL,
                    blindspot_value VARCHAR(200) NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT NOW(),
                    last_surfaced_to_user TIMESTAMP,
                    UNIQUE(user_id, blindspot_type, blindspot_value)
                );
            """))
            conn.commit()
            print("✅ user_market_blindspots ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ user_market_blindspots skip: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_simulation_accuracy_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    simulation_id INTEGER REFERENCES simulations(id),
                    predicted_conversion FLOAT NOT NULL,
                    actual_conversion FLOAT,
                    absolute_gap FLOAT,
                    signal_quality_at_run FLOAT NOT NULL,
                    accuracy_trend VARCHAR(30) DEFAULT 'INSUFFICIENT_DATA',
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """))
            conn.commit()
            print("✅ user_simulation_accuracy_history ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ user_simulation_accuracy_history skip: {e}")

    # Seed cluster_parameters with 416 placeholder rows (52 clusters × 8 traits)
    _seed_cluster_parameters()

    print("━━━ All migrations complete ━━━")


_CLUSTER_IDS = [
    # Step 37 canonical cluster IDs (47 explicit + 5 additional = 52 total)
    "metro_power_professional", "senior_enterprise_decision_maker",
    "high_income_early_adopter", "affluent_metro_late_majority",
    "high_income_hardware_enthusiast", "wealthy_health_conscious_buyer",
    "urban_mid_income_saas_buyer", "urban_mid_income_hardware_considerer",
    "young_urban_professional_first_job", "urban_couple_joint_purchaser",
    "mid_income_startup_founder", "urban_working_mother",
    "high_literacy_student_freemium_ceiling", "low_literacy_student_passive",
    "student_high_intent_specific_need", "college_group_purchase",
    "recent_graduate_job_seeker",
    "tier2_aspirational_founder", "tier2_established_business_owner",
    "tier3_first_time_app_user", "tier2_price_sensitive_pragmatist",
    "tier3_community_influenced_buyer", "tier2_educated_young_parent",
    "smb_owner_self_serve", "smb_owner_referral_dependent",
    "mid_market_it_decision_maker", "enterprise_procurement_gatekeeper",
    "technical_founder_evaluator", "non_technical_co_founder_buyer",
    "early_hardware_adopter_tech_enthusiast", "considered_hardware_researcher",
    "value_hardware_buyer", "gift_hardware_buyer", "replacement_hardware_buyer",
    "health_hardware_skeptic", "health_hardware_enthusiast",
    "smart_home_early_adopter",
    "anxiety_driven_researcher", "impulsive_trend_follower",
    "loyalist_returning_buyer", "price_anchor_manipulated_buyer",
    "peer_pressure_converter", "deliberate_minimalist",
    "productivity_maximiser", "budget_constrained_high_intent",
    "passive_enterprise_user", "burnt_previously_buyer",
    # 5 additional clusters
    "retiree_digital_explorer", "gig_economy_worker",
    "ngo_nonprofit_buyer", "diaspora_remittance_buyer",
    "vernacular_content_creator",
]

_TRAIT_NAMES = [
    "income_level",
    "digital_literacy",
    "motivation",
    "trust",
    "price_sensitivity",
    "risk_aversion",
    "patience_score",
    "social_orientation",
]


def _seed_cluster_parameters():
    with engine.connect() as conn:
        try:
            row = conn.execute(text("SELECT COUNT(*) FROM cluster_parameters")).scalar()
            if row and row > 0:
                print(f"✅ cluster_parameters already seeded ({row} rows)")
                return

            rows = [
                {"cluster_id": cid, "trait_name": trait}
                for cid in _CLUSTER_IDS
                for trait in _TRAIT_NAMES
            ]
            conn.execute(
                text("""
                    INSERT INTO cluster_parameters
                        (cluster_id, trait_name, base_value, calibrated_value,
                         calibration_count, effective_sample_count, calibration_source)
                    VALUES
                        (:cluster_id, :trait_name, 0.5, 0.5, 0, 0.0, 'AUTHORED')
                    ON CONFLICT (cluster_id, trait_name) DO NOTHING
                """),
                rows,
            )
            conn.commit()
            inserted = conn.execute(text("SELECT COUNT(*) FROM cluster_parameters")).scalar()
            print(f"✅ cluster_parameters seeded: {inserted} rows")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ cluster_parameters seed failed: {e}")


if __name__ == "__main__":
    run_migrations()
    print("🚀 Starting TheCee backend on http://localhost:8000")
    import uvicorn

    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
