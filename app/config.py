"""Application Configuration Module.

Loads configuration from environment variables and .env file using Pydantic Settings.
Enforces typed settings across development, testing, and production environments.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable bindings."""

    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    debug: bool = Field(default=False, alias="DEBUG")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/payment_ledger",
        alias="DATABASE_URL",
    )
    test_database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/payment_ledger_test",
        alias="TEST_DATABASE_URL",
    )

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    outbox_poll_interval_seconds: float = Field(default=2.0, alias="OUTBOX_POLL_INTERVAL_SECONDS")
    outbox_batch_size: int = Field(default=10, alias="OUTBOX_BATCH_SIZE")

    # Velocity fraud controls
    velocity_max_tx_per_window: int = Field(default=5, alias="VELOCITY_MAX_TX_PER_WINDOW")
    velocity_window_seconds: int = Field(default=60, alias="VELOCITY_WINDOW_SECONDS")
    velocity_max_daily_volume: str = Field(default="10000.00", alias="VELOCITY_MAX_DAILY_VOLUME")
    velocity_daily_window_seconds: int = Field(default=86400, alias="VELOCITY_DAILY_WINDOW_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton instance."""
    return Settings()
