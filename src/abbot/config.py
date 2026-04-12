"""Application configuration loaded from environment variables.

Uses Pydantic BaseSettings for validation. Fails loudly at startup if
required configuration is missing.

Usage:
    from abbot.config import get_settings
    settings = get_settings()
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Abbot application settings.

    Required values come from environment variables or a .env file.
    """

    # Kalshi API
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: Path = Path("~/.kalshi/private_key.pem")

    # Database
    database_url: str = ""

    # Application
    app_name: str = "Abbot"
    debug: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings. Reads .env on first call."""
    return Settings()
