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
            ("simulations", "results_json", "TEXT"),
            ("simulations", "confidence_score", "FLOAT"),
            ("prototypes", "html_content", "TEXT"),
            ("prototypes", "funnel_graph_json", "TEXT"),
        ]:
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};")
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
