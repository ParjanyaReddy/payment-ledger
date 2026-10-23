"""Unit Tests for Application Configuration."""

from app.config import Settings


def test_settings_default_values() -> None:
    """Verify default configuration attributes are properly initialized."""
    settings = Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
    )
    assert settings.app_env == "test"
    assert settings.app_port == 8000
    assert "postgresql+asyncpg" in settings.database_url
    assert settings.outbox_batch_size == 10
    assert settings.outbox_poll_interval_seconds == 2.0
