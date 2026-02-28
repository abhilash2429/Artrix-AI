"""Application configuration via pydantic-settings.

All values loaded from environment variables / .env file.
No hardcoded secrets anywhere.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings. Loaded from env vars / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- LLM ---
    gemini_api_key: str = ""

    # --- Database ---
    postgres_url: str = "postgresql+asyncpg://user:password@localhost:5432/agentdb"
    redis_url: str = "redis://localhost:6379/0"

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""

    # --- Cohere ---
    cohere_api_key: str = ""

    # --- Auth ---
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    api_key_prefix: str = "ent_live_"

    # --- App ---
    app_env: str = "development"
    log_level: str = "INFO"
    max_sessions_per_tenant: int = 1000
    idle_session_timeout_minutes: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_postgres_url(self) -> str:
        """Synchronous Postgres URL for Alembic migrations."""
        return self.postgres_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"
        )


settings = Settings()
