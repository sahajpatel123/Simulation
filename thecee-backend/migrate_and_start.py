from sqlalchemy import text

from app.core.database import engine

MIGRATIONS = [
    """
    CREATE EXTENSION IF NOT EXISTS vector;
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        name VARCHAR(255),
        hashed_password VARCHAR(255) NOT NULL,
        tier VARCHAR(50) DEFAULT 'free',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        name VARCHAR(500) NOT NULL,
        description_raw TEXT,
        assumptions_extracted JSONB DEFAULT '[]',
        status VARCHAR(50) DEFAULT 'draft',
        prototype_html TEXT,
        funnel_graph JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS simulations (
        id SERIAL PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        status VARCHAR(50) DEFAULT 'queued',
        consumer_volume INTEGER DEFAULT 10000,
        results JSONB,
        confidence_score FLOAT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    );
    """,
]


def run_migrations():
    print("━━━ Running TheCee migrations ━━━")
    with engine.connect() as conn:
        for i, migration in enumerate(MIGRATIONS):
            try:
                conn.execute(text(migration))
                conn.commit()
                print(f"✅ Migration {i + 1}/{len(MIGRATIONS)} complete")
            except Exception as e:
                print(f"⚠️  Migration {i + 1} skipped or errored: {e}")
                conn.rollback()
    print("━━━ All migrations done ━━━")


if __name__ == "__main__":
    run_migrations()
    print("🚀 Starting TheCee backend on http://localhost:8000")
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
