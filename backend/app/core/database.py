from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.query_metrics import install_query_metrics

_connect_args: dict[str, object] = {}
if settings.DATABASE_URL.startswith("postgresql"):
    _connect_args["connect_timeout"] = settings.DB_CONNECT_TIMEOUT_SECONDS
    _connect_args["options"] = f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}"

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    connect_args=_connect_args,
)

# Observe every statement executed on this engine: per-kind counters and
# latency histograms plus a bounded slow-query ring for
# ``GET /api/v1/system/query-health``. Idempotent, so importing this module
# from the API, the Celery worker, or scripts installs the listener once.
install_query_metrics(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_extensions():
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
            print("✅ pgvector extension ready")
        except Exception:
            conn.rollback()
            print("⚠️ pgvector extension unavailable; continuing without it")
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
            conn.commit()
            print("✅ pgcrypto extension ready")
        except Exception:
            conn.rollback()
            print("⚠️ pgcrypto extension unavailable; continuing without it")
