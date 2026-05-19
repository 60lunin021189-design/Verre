"""Runtime configuration loaded from environment variables / .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings populated from env vars and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    encryption_key: str = Field(default="", alias="VERRE_ENCRYPTION_KEY")
    db_path: Path = Field(default=Path("verre.db"), alias="VERRE_DB_PATH")
    allowed_telegram_ids_raw: str = Field(default="", alias="VERRE_ALLOWED_TELEGRAM_IDS")
    poll_interval_seconds: int = Field(default=20, alias="VERRE_POLL_INTERVAL_SECONDS")
    binance_testnet: bool = Field(default=False, alias="VERRE_BINANCE_TESTNET")
    leaderboard_timeout: float = Field(default=10.0, alias="VERRE_LEADERBOARD_TIMEOUT")

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def allowed_telegram_ids(self) -> set[int]:
        """Parse VERRE_ALLOWED_TELEGRAM_IDS into a set of ints."""
        if not self.allowed_telegram_ids_raw.strip():
            return set()
        result: set[int] = set()
        for chunk in self.allowed_telegram_ids_raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                result.add(int(chunk))
            except ValueError:
                continue
        return result


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force re-reading settings (used in tests)."""
    global _settings
    _settings = Settings()
    return _settings
