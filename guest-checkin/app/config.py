"""Application configuration via pydantic-settings.

All settings are loaded from environment variables / .env file.
"""

import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = (
        "mysql+pymysql://guestcheckin:guestcheckin@localhost:3306/guestcheckin"
    )

    # ── LLM (Ollama) ─────────────────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"

    # ── SMTP ──────────────────────────────────────────────────────
    SMTP_HOST: str = "mailhog"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = "checkin@guestapp.local"

    # ── File uploads ──────────────────────────────────────────────
    UPLOAD_DIR: str = "/app/uploads"

    # ── Secure links ──────────────────────────────────────────────
    LINK_SECRET: str = secrets.token_hex(32)  # Auto-generated; set LINK_SECRET in production
    LINK_EXPIRY_HOURS: int = 1

    # ── Authentication ────────────────────────────────────────────
    API_KEY_HEADER: str = "X-API-Key"
    SESSION_TOKEN_EXPIRY_HOURS: int = 24

    # ── Rate limiting ─────────────────────────────────────────────
    RATE_LIMIT: str = "60/minute"

    # ── CORS ──────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]


settings = Settings()
