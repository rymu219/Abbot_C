"""Kalshi API authentication.

Reads the RSA private key from the file path in .env and creates
a KalshiAuth instance for request signing. Does not log or print secrets.

Usage:
    from abbot.kalshi.auth import load_private_key_pem, build_auth

    pem = load_private_key_pem()
    auth = build_auth()
"""

from pathlib import Path

from abbot.config import get_settings


def load_private_key_pem() -> str:
    """Read the RSA private key PEM from the path specified in .env."""
    settings = get_settings()
    key_path = Path(settings.kalshi_private_key_path).expanduser()
    if not key_path.exists():
        raise FileNotFoundError(
            f"Kalshi private key not found at: {key_path}. "
            "Set KALSHI_PRIVATE_KEY_PATH in .env to the correct path."
        )
    return key_path.read_text()


def build_auth():
    """Build a KalshiAuth instance from .env credentials.

    Returns a kalshi_python_sync.KalshiAuth ready to sign requests.
    """
    from kalshi_python_sync import KalshiAuth

    settings = get_settings()
    pem = load_private_key_pem()
    return KalshiAuth(key_id=settings.kalshi_api_key_id, private_key_pem=pem)
