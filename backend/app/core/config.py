from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    DATABASE_URL: str
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "thecee"

    SECRET_KEY: str = "dev-secret-change-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    ANTHROPIC_API_KEY: str = ""

    # xAI Grok (OpenAI-compatible). Active LLM provider for development.
    # Set GROK_API_KEY in the deployment environment; the rest have sensible defaults.
    GROK_API_KEY: str = ""
    GROK_BASE_URL: str = "https://api.x.ai/v1"
    GROK_MODEL: str = "grok-3-mini"
    GROK_FAST_MODEL: str = "grok-3-mini"
    # Alias fields: pydantic-settings loads these from .env AND OS env, so the
    # validator below can read them via self.* (os.environ.get() misses .env values).
    OPENAI_API_KEY: str = ""
    XAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    PUBLIC_API_BASE_URL: str = "http://127.0.0.1:8000"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    REDIS_CONNECT_TIMEOUT_SECONDS: float = 2.0
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 2.0

    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_CONNECT_TIMEOUT_SECONDS: int = 10
    DB_STATEMENT_TIMEOUT_MS: int = 30000

    VECTOR_DIMENSION: int = 1536

    # In-process fan-out for heavy simulation paths (tunable per deployment).
    CONDUCTOR_WORKERS: int = 4

    # Simulation enhancement: multiplier for intra-cluster trait variance
    # Values > 1.0 increase behavioral variation within clusters for better edge-case detection
    CLUSTER_VARIANCE_MULTIPLIER: float = 1.0

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_PRO_PLAN_ID: str = ""
    RAZORPAY_ENTERPRISE_PLAN_ID: str = ""

    SENTRY_DSN: str = ""
    # Comma-separated admin emails; may access GET /api/v1/analytics/platform
    ADMIN_EMAILS: str = ""
    ALLOW_INDEXING: bool = False

    @model_validator(mode="after")
    def _coerce_llm_env_aliases(self) -> "Settings":
        """Accept OPENAI_* / XAI_* env vars as fallbacks when GROK_* are unset.

        Reads from model fields (populated by pydantic-settings from .env AND OS env)
        so .env file aliases are honoured — unlike os.environ.get() which only sees OS-level vars.
        """
        if not self.GROK_API_KEY:
            for fallback in (self.XAI_API_KEY, self.OPENAI_API_KEY):
                if fallback.strip():
                    self.GROK_API_KEY = fallback.strip()
                    break

        if self.OPENAI_BASE_URL.strip() and self.OPENAI_BASE_URL.strip() != self.GROK_BASE_URL:
            self.GROK_BASE_URL = self.OPENAI_BASE_URL.strip()

        if self.OPENAI_MODEL.strip() and self.GROK_MODEL == "grok-3-mini":
            self.GROK_MODEL = self.OPENAI_MODEL.strip()
            if self.GROK_FAST_MODEL == "grok-3-mini":
                self.GROK_FAST_MODEL = self.OPENAI_MODEL.strip()

        return self

    @model_validator(mode="after")
    def _reject_weak_jwt_secret_in_production(self) -> "Settings":
        if self.ENVIRONMENT.lower() != "production":
            return self
        weak = {
            "dev-secret-change-in-prod",
            "change-this-to-a-long-random-string-in-production",
        }
        key = self.SECRET_KEY.strip()
        if len(key) < 32 or key.lower() in weak or key.lower().startswith("change-"):
            raise ValueError(
                "SECRET_KEY must be a random string of at least 32 characters in production "
                "(set via environment; do not use dev defaults)."
            )
        return self

    def cors_allowed_origins(self) -> list[str]:
        defaults = ["http://localhost:3000", "http://localhost:3001"]
        frontend = self.FRONTEND_URL.strip()
        if self.ENVIRONMENT.lower() == "production":
            return [frontend] if frontend else []
        origins = [*defaults]
        if frontend and frontend not in origins:
            origins.insert(0, frontend)
        return origins


settings = Settings()
