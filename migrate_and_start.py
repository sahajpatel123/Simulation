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
    OutcomeTracker,
    GeneratedUI,
    UISimulationSession,
    UISimulationRun,
    HardwareProduct,
    Hardware3DModel,
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
            ("users", "handle", "VARCHAR(64)"),
            ("users", "reduced_motion", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("users", "email_notices", "BOOLEAN DEFAULT TRUE NOT NULL"),
            ("users", "weekly_brief", "BOOLEAN DEFAULT FALSE NOT NULL"),
            ("users", "default_units", "VARCHAR(8) DEFAULT 'inr' NOT NULL"),
            ("users", "default_reader_count", "INTEGER DEFAULT 10000 NOT NULL"),
            ("users", "default_scenario", "VARCHAR(32) DEFAULT 'base' NOT NULL"),
            ("users", "default_aov", "FLOAT DEFAULT 1000.0 NOT NULL"),
            ("users", "keep_past_results", "BOOLEAN DEFAULT TRUE NOT NULL"),
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

        try:
            conn.execute(
                text(
                    """
                    ALTER TABLE simulations
                    ADD COLUMN IF NOT EXISTS error_message TEXT;
                    """
                )
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
                CREATE UNIQUE INDEX IF NOT EXISTS uq_cluster_run_summaries_sim_cluster
                ON cluster_run_summaries (simulation_id, cluster_id);
            """))
            conn.commit()
        except Exception:
            conn.rollback()

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

        # Step 92: founder_outcomes soft-gate columns + index; user retention + admin
        for col_sql in [
            "ALTER TABLE founder_outcomes ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)",
            "ALTER TABLE founder_outcomes ADD COLUMN IF NOT EXISTS launched BOOLEAN DEFAULT FALSE",
            "ALTER TABLE founder_outcomes ADD COLUMN IF NOT EXISTS notes TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS retention_email_sent_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",
        ]:
            try:
                conn.execute(text(col_sql))
                conn.commit()
            except Exception:
                conn.rollback()
        try:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_founder_outcomes_sim ON founder_outcomes(simulation_id);"
                )
            )
            conn.commit()
            print("✅ idx_founder_outcomes_sim ready (Step 92)")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ idx_founder_outcomes_sim skip: {e}")

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

        # Step 53: UI generation schema (additive)
        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS generated_uis (
                        id               SERIAL PRIMARY KEY,
                        project_id       INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                        prompt           TEXT NOT NULL,
                        html_content     TEXT NOT NULL,
                        version          INTEGER DEFAULT 1,
                        product_type     VARCHAR(100),
                        pages_generated  INTEGER DEFAULT 1,
                        created_at       TIMESTAMP DEFAULT NOW(),
                        updated_at       TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ generated_uis ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ generated_uis skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS ui_simulation_sessions (
                        id                 SERIAL PRIMARY KEY,
                        generated_ui_id    INTEGER REFERENCES generated_uis(id) ON DELETE CASCADE,
                        agent_cluster_id   VARCHAR(100) NOT NULL,
                        agent_profile_json JSONB NOT NULL,
                        events_json        JSONB,
                        outcome            VARCHAR(50),
                        duration_seconds   INTEGER,
                        pages_visited      INTEGER DEFAULT 1,
                        converted          BOOLEAN DEFAULT FALSE,
                        created_at         TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ ui_simulation_sessions ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ ui_simulation_sessions skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS ui_simulation_runs (
                        id                    SERIAL PRIMARY KEY,
                        project_id            INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                        generated_ui_id       INTEGER REFERENCES generated_uis(id) ON DELETE CASCADE,
                        status                VARCHAR(50) DEFAULT 'QUEUED',
                        agent_count           INTEGER NOT NULL,
                        results_json          JSONB,
                        conductor_result_json JSONB,
                        created_at            TIMESTAMP DEFAULT NOW(),
                        completed_at          TIMESTAMP
                    );
                """)
            )
            conn.commit()
            print("✅ ui_simulation_runs ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ ui_simulation_runs skip: {e}")

        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_generated_uis_project_id ON generated_uis(project_id);",
            "CREATE INDEX IF NOT EXISTS idx_ui_sessions_generated_ui_id ON ui_simulation_sessions(generated_ui_id);",
            "CREATE INDEX IF NOT EXISTS idx_ui_sessions_cluster_id ON ui_simulation_sessions(agent_cluster_id);",
            "CREATE INDEX IF NOT EXISTS idx_ui_runs_project_id ON ui_simulation_runs(project_id);",
            "CREATE INDEX IF NOT EXISTS idx_ui_runs_status ON ui_simulation_runs(status);",
        ]:
            try:
                conn.execute(text(idx_sql))
                conn.commit()
            except Exception:
                conn.rollback()

        # Step 69: hardware module schema (additive, CREATE TABLE IF NOT EXISTS)
        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS hardware_products (
                        id SERIAL PRIMARY KEY,
                        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        name VARCHAR(500) NOT NULL,
                        description TEXT,
                        category VARCHAR(200),
                        product_type VARCHAR(50) NOT NULL,
                        target_price_inr DOUBLE PRECISION,
                        material_spec TEXT,
                        dimensions_json JSONB,
                        weight_grams DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ hardware_products ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_products skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS hardware_3d_models (
                        id SERIAL PRIMARY KEY,
                        hardware_product_id INTEGER NOT NULL
                            REFERENCES hardware_products(id) ON DELETE CASCADE,
                        model_type VARCHAR(20) NOT NULL,
                        model_data_json JSONB,
                        polygon_count INTEGER,
                        generation_prompt TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ hardware_3d_models ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_3d_models skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS hardware_test_configs (
                        id SERIAL PRIMARY KEY,
                        hardware_product_id INTEGER NOT NULL
                            REFERENCES hardware_products(id) ON DELETE CASCADE,
                        test_type VARCHAR(100) NOT NULL,
                        parameters_json JSONB,
                        environment_conditions_json JSONB,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ hardware_test_configs ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_test_configs skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS hardware_test_results (
                        id SERIAL PRIMARY KEY,
                        hardware_product_id INTEGER NOT NULL
                            REFERENCES hardware_products(id) ON DELETE CASCADE,
                        test_config_id INTEGER NOT NULL
                            REFERENCES hardware_test_configs(id) ON DELETE CASCADE,
                        test_type VARCHAR(100) NOT NULL,
                        status VARCHAR(50) NOT NULL,
                        results_json JSONB,
                        failure_points_json JSONB,
                        pass_rate DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ hardware_test_results ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_test_results skip: {e}")

        # Step 76: runs may use auto-generated configs (no persisted row) — FK optional
        try:
            conn.execute(
                text(
                    "ALTER TABLE hardware_test_results "
                    "ALTER COLUMN test_config_id DROP NOT NULL"
                )
            )
            conn.commit()
            print("✅ hardware_test_results.test_config_id nullable (Step 76)")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_test_results nullable alter skip: {e}")

        try:
            conn.execute(
                text(
                    "ALTER TABLE hardware_products "
                    "ADD COLUMN IF NOT EXISTS last_test_summary_json JSONB"
                )
            )
            conn.commit()
            print("✅ hardware_products.last_test_summary_json ready (Step 76)")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_products last_test_summary_json skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS hardware_manufacturing_estimates (
                        id SERIAL PRIMARY KEY,
                        hardware_product_id INTEGER NOT NULL
                            REFERENCES hardware_products(id) ON DELETE CASCADE,
                        bom_json JSONB,
                        unit_cost_inr DOUBLE PRECISION,
                        tooling_cost_inr DOUBLE PRECISION,
                        moq INTEGER,
                        lead_time_days INTEGER,
                        margin_at_target_price DOUBLE PRECISION,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
            )
            conn.commit()
            print("✅ hardware_manufacturing_estimates ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_manufacturing_estimates skip: {e}")

        try:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS hardware_consumer_simulation_runs (
                        id SERIAL PRIMARY KEY,
                        hardware_product_id INTEGER NOT NULL
                            REFERENCES hardware_products(id) ON DELETE CASCADE,
                        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        status VARCHAR(50) DEFAULT 'QUEUED',
                        agent_count INTEGER NOT NULL,
                        product_type VARCHAR(50),
                        results_json JSONB,
                        conductor_result_json JSONB,
                        generated_ui_id INTEGER REFERENCES generated_uis(id) ON DELETE SET NULL,
                        created_at TIMESTAMP DEFAULT NOW(),
                        completed_at TIMESTAMP
                    );
                """)
            )
            conn.commit()
            print("✅ hardware_consumer_simulation_runs ready")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ hardware_consumer_simulation_runs skip: {e}")

        for hw_idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_hw_products_project_id ON hardware_products(project_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_products_product_type ON hardware_products(product_type);",
            "CREATE INDEX IF NOT EXISTS idx_hw_3d_models_product_id ON hardware_3d_models(hardware_product_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_test_configs_product_id ON hardware_test_configs(hardware_product_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_test_results_product_id ON hardware_test_results(hardware_product_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_test_results_config_id ON hardware_test_results(test_config_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_mfg_estimates_product_id ON hardware_manufacturing_estimates(hardware_product_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_consumer_runs_product_id ON hardware_consumer_simulation_runs(hardware_product_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_consumer_runs_project_id ON hardware_consumer_simulation_runs(project_id);",
            "CREATE INDEX IF NOT EXISTS idx_hw_consumer_runs_status ON hardware_consumer_simulation_runs(status);",
        ]:
            try:
                conn.execute(text(hw_idx_sql))
                conn.commit()
            except Exception:
                conn.rollback()

        # Step 85: intake_mode + subscription / usage
        try:
            conn.execute(
                text(
                    """
                    ALTER TABLE projects
                    ADD COLUMN IF NOT EXISTS intake_mode VARCHAR(20) DEFAULT 'IDEA';
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE projects
                    ADD COLUMN IF NOT EXISTS landing_page_url TEXT;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE projects
                    ADD COLUMN IF NOT EXISTS mvp_feature_list JSONB;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE projects
                    ADD COLUMN IF NOT EXISTS existing_product_description TEXT;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE projects
                    ADD COLUMN IF NOT EXISTS dossier_axis VARCHAR(20);
                    """
                )
            )
            print("✅ intake_mode fields added to projects")
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(20) DEFAULT 'free';
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS simulations_used_this_month INTEGER DEFAULT 0;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS usage_reset_at TIMESTAMP DEFAULT NOW();
                    """
                )
            )
            print("✅ subscription_tier fields added to users")
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"⚠️ step 85 migration skip: {e}")

        # Step 86: Razorpay (idempotent with Step 85 subscription columns)
        try:
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(20) DEFAULT 'free';
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS razorpay_customer_id VARCHAR(100);
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS razorpay_subscription_id VARCHAR(100);
                    """
                )
            )
            print("✅ Razorpay columns added to users")
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"⚠️ step 86 migration skip: {e}")

        # Step 87: performance indexes (hot API / simulation paths)
        try:
            for perf_idx_sql in [
                """
                CREATE INDEX IF NOT EXISTS idx_simulations_project_status
                ON simulations (project_id, status);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_simulations_user_created
                ON simulations (project_id, created_at DESC);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_ui_simulation_sessions_ui_id
                ON ui_simulation_sessions (generated_ui_id);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cluster_run_summaries_sim_id
                ON cluster_run_summaries (simulation_id);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_hardware_test_results_hw_id
                ON hardware_test_results (hardware_product_id);
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_hardware_products_project_id
                ON hardware_products (project_id);
                """,
            ]:
                conn.execute(text(perf_idx_sql.strip()))
            conn.commit()
            print("✅ Performance indexes created")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ step 87 performance indexes skip: {e}")

        # Step 88: refresh tokens (opaque, hashed)
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS refresh_tokens (
                        id         SERIAL PRIMARY KEY,
                        user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
                        token_hash VARCHAR(64) NOT NULL UNIQUE,
                        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        revoked    BOOLEAN    DEFAULT FALSE
                    );
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash
                    ON refresh_tokens (token_hash);
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id
                    ON refresh_tokens (user_id);
                    """
                )
            )
            conn.commit()
            print("✅ refresh_tokens table created")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ step 88 refresh_tokens skip: {e}")

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
