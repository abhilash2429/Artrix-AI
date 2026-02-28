"""Application configuration via pydantic-settings.

All values loaded from .env file at the project root.
The .env file takes precedence over OS-level environment variables
so stale system env vars never shadow the project config.
No hardcoded secrets anywhere.
"""

from pathlib import Path
from typing import Any, Tuple, Type

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Resolve .env from project root (three levels up from this file: app/core/config.py → backend → project root)
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Central application settings. .env file wins over OS env vars."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Override source priority: .env file > OS env vars > defaults."""
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)

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
