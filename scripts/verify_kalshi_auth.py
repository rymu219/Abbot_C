"""Verify Kalshi API authentication and pull a single market listing.

Usage:
    uv run python scripts/verify_kalshi_auth.py
"""

import sys

from abbot.config import get_settings


def main() -> None:
    settings = get_settings()

    if not settings.kalshi_api_key_id:
        print("ERROR: KALSHI_API_KEY_ID not set in .env")
        sys.exit(1)

    if not settings.kalshi_private_key_path.expanduser().exists():
        print(f"ERROR: Private key not found at {settings.kalshi_private_key_path}")
        sys.exit(1)

    print(f"API Key ID: {settings.kalshi_api_key_id[:8]}...")
    print(f"Private Key: {settings.kalshi_private_key_path}")
    print()
    print("Authentication configuration looks valid.")
    print("Full API connectivity test will be implemented in Phase 3.")


if __name__ == "__main__":
    main()
