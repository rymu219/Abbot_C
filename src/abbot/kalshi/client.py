"""Kalshi API client wrapper.

Provides a configured KalshiClient that reads credentials from .env
and handles RSA-PSS auth signing automatically.

Usage:
    from abbot.kalshi.client import get_kalshi_client

    client = get_kalshi_client()
    markets = client.market.get_markets()
"""

from functools import lru_cache

from kalshi_python_sync import Configuration, KalshiClient

from abbot.kalshi.auth import load_private_key_pem
from abbot.config import get_settings


@lru_cache
def get_kalshi_client() -> KalshiClient:
    """Create and cache a fully authenticated KalshiClient."""
    settings = get_settings()

    config = Configuration()
    # Set credentials for KalshiClient's auth handler
    config.api_key_id = settings.kalshi_api_key_id
    config.private_key_pem = load_private_key_pem()

    return KalshiClient(configuration=config)
