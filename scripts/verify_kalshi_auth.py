"""Verify Kalshi API auth + Neon DB connection end-to-end.

Usage:
    uv run python scripts/verify_kalshi_auth.py
"""

import sys

from abbot.config import get_settings


def verify_db() -> bool:
    """Test database connectivity via DATABASE_URL."""
    from sqlalchemy import text
    from abbot.db.engine import get_engine

    print("--- Database ---")
    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version()")).scalar()
            print(f"  Connected: {row}")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False


def verify_kalshi() -> bool:
    """Test Kalshi API auth by pulling a single market listing."""
    print("--- Kalshi API ---")
    settings = get_settings()

    if not settings.kalshi_api_key_id:
        print("  SKIPPED: KALSHI_API_KEY_ID not set in .env")
        return False

    key_path = settings.kalshi_private_key_path
    if not key_path.exists():
        print(f"  SKIPPED: Private key not found at {key_path}")
        return False

    print(f"  API Key: {settings.kalshi_api_key_id[:8]}...")
    print(f"  Key file: {key_path}")

    try:
        from abbot.kalshi.client import get_kalshi_client

        client = get_kalshi_client()
        resp = client._market_api.get_markets(limit=1)
        markets = resp.markets or []
        if markets:
            m = markets[0]
            print(f"  First market: {m.ticker} — {m.title}")
        else:
            print("  Connected (no markets returned)")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False


def main() -> None:
    db_ok = verify_db()
    print()
    kalshi_ok = verify_kalshi()
    print()

    if db_ok and kalshi_ok:
        print("All connections verified.")
    elif db_ok:
        print("DB verified. Kalshi needs attention.")
    else:
        print("Issues found. Check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
