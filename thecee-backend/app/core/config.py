from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    DATABASE_URL: str
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "thecee"

    SECRET_KEY: str = "dev-secret-change-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080

    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:3000"

    VECTOR_DIMENSION: int = 1536


settings = Settings()
