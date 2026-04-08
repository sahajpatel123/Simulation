from sqlalchemy import text

from app.core.database import engine
from app.models import (
    Base,
    User,
    Project,
    Assumption,
    Environment,
    Simulation,
    ConsumerAgent,
    Decision,
    OutcomeTracker,
)


def run_migrations():
    print("━━━ Running TheCee migrations ━━━")

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
        print("✅ pgvector extension ready")

    Base.metadata.create_all(bind=engine)
    print("✅ All tables created or verified")

    with engine.connect() as conn:
        for table, column, col_type in [
            ("users", "tier", "VARCHAR(50) DEFAULT 'free'"),
            ("projects", "prototype_html", "TEXT"),
            ("projects", "funnel_graph_json", "TEXT"),
            ("projects", "premortem_json", "JSONB"),
            ("simulations", "results_json", "TEXT"),
            ("simulations", "confidence_score", "FLOAT"),
            ("simulations", "task_id", "VARCHAR(255)"),
            ("simulations", "error_message", "TEXT"),
            ("simulations", "consumer_volume", "INTEGER DEFAULT 10000"),
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

    print("━━━ All migrations complete ━━━")


if __name__ == "__main__":
    run_migrations()
    print("🚀 Starting TheCee backend on http://localhost:8000")
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
