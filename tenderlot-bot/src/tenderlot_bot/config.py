"""Application configuration via pydantic-settings."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Bot identity ───────────────────────────────────────────────────────────
    telegram_bot_token: str

    # "polling" for Replit dev; "webhook" for Render production
    bot_mode: Literal["polling", "webhook"] = "polling"

    # ── Database URLs ──────────────────────────────────────────────────────────
    # Bot's own state DB: SQLite in dev, Neon PostgreSQL in production
    bot_database_url: str = "sqlite+aiosqlite:///./tenderlot_bot.db"

    # Tenderlot read-only DB: SQLite mock in dev, MariaDB in production
    # In production, replace with: mysql+pymysql://user:pass@host/tenderlot
    tenderlot_database_url: str = "sqlite+aiosqlite:///./tenderlot_mock.db"

    # ── Polling ────────────────────────────────────────────────────────────────
    poll_interval_seconds: int = 30
    poll_batch_size: int = 50

    # ── Behaviour ─────────────────────────────────────────────────────────────
    consent_required: bool = True
    environment: Literal["replit_dev", "render_staging", "render_prod"] = "replit_dev"

    # ── Logging ────────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TENDERLOT_BOT_",
        case_sensitive=False,
    )


settings = Settings()  # type: ignore[call-arg]
