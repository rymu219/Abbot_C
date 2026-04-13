"""Discover and decide worker.

Finds games entering the T-30 decision window, captures paired Kalshi
YES contract prices, determines the favorite, and writes one paper bet.

Build spec ref: §4 (frozen execution contract), §5 "Discover/decide" worker.

Kalshi API assumptions (to be validated during discovery probe):
- MLB moneyline markets use series ticker prefix "KXMLB"
- Each game has two YES contracts (one per team)
- Price field used: yes_ask (simulating a buy)
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from v0.db import get_engine

logger = logging.getLogger(__name__)

# The frozen rule constants
STAKE_DOLLARS = Decimal("10.00")
SIDE = "YES"
MODE = "paper"

# Decision window: [T-30:00, T-29:00)
WINDOW_BEFORE_PITCH = timedelta(minutes=30)
WINDOW_DURATION = timedelta(minutes=1)

# Max time gap between paired snapshots (build spec §4.5)
MAX_PAIR_GAP_SECONDS = 5


def run_discover_decide() -> dict:
    """Run one cycle of discover + decide.

    Returns a summary dict: {checked, snapshotted, bet, skipped_reasons}.
    """
    engine = get_engine()
    now = datetime.now(timezone.utc)
    result = {"checked": 0, "snapshotted": 0, "bet": 0, "skipped": []}

    # Find games whose T-30 window is now
    window_start = now
    window_end = now + WINDOW_DURATION

    with Session(engine) as session:
        # Games where first_pitch - 30min falls within [now, now+1min)
        # i.e., first_pitch is between now+29min and now+31min
        rows = session.execute(
            text("""
                SELECT game_id, first_pitch_utc, home_team_abbr, away_team_abbr
                FROM games
                WHERE status = 'scheduled'
                  AND first_pitch_utc - INTERVAL '30 minutes' >= :window_start
                  AND first_pitch_utc - INTERVAL '30 minutes' < :window_end
            """),
            {"window_start": window_start, "window_end": window_end},
        ).fetchall()

    result["checked"] = len(rows)

    if not rows:
        return result

    for game_id, first_pitch, home_abbr, away_abbr in rows:
        try:
            _process_game(engine, game_id, home_abbr, away_abbr, now, result)
        except Exception as e:
            logger.error("Failed to process game %s: %s", game_id, str(e)[:200])
            result["skipped"].append({"game_id": game_id, "reason": str(e)[:200]})

    return result


def _process_game(
    engine, game_id: str, home_abbr: str, away_abbr: str,
    now: datetime, result: dict,
) -> None:
    """Process a single game: snapshot prices, determine favorite, place bet."""

    with Session(engine) as session:
        # Check if bet already exists (idempotency — build spec §4.9)
        existing = session.execute(
            text("SELECT bet_id FROM bets WHERE game_id = :gid"),
            {"gid": game_id},
        ).fetchone()
        if existing:
            logger.debug("Bet already exists for game %s, skipping", game_id)
            return

    # Fetch Kalshi prices for both sides
    home_price, home_ticker = _fetch_kalshi_price(game_id, home_abbr)
    away_price, away_ticker = _fetch_kalshi_price(game_id, away_abbr)

    # Validate pair (build spec §4.3, §4.6)
    if home_price is None or away_price is None:
        reason = f"missing price: home={home_price}, away={away_price}"
        logger.warning("Skipping game %s: %s", game_id, reason)
        result["skipped"].append({"game_id": game_id, "reason": reason})
        return

    if not (1 <= home_price <= 99) or not (1 <= away_price <= 99):
        reason = f"price out of range: home={home_price}, away={away_price}"
        logger.warning("Skipping game %s: %s", game_id, reason)
        result["skipped"].append({"game_id": game_id, "reason": reason})
        return

    # Tie handling (build spec §4.6)
    if home_price == away_price:
        reason = f"tie price: {home_price}c"
        logger.info("Skipping game %s: %s", game_id, reason)
        result["skipped"].append({"game_id": game_id, "reason": reason})
        return

    # Determine favorite (build spec §4.1 — higher YES price)
    if home_price > away_price:
        fav_abbr, fav_price, fav_ticker = home_abbr, home_price, home_ticker
        dog_abbr, dog_price, dog_ticker = away_abbr, away_price, away_ticker
    else:
        fav_abbr, fav_price, fav_ticker = away_abbr, away_price, away_ticker
        dog_abbr, dog_price, dog_ticker = home_abbr, home_price, home_ticker

    captured_at = datetime.now(timezone.utc)

    with Session(engine) as session:
        # Write both snapshots
        session.execute(
            text("""
                INSERT INTO market_snapshots
                    (game_id, kalshi_ticker, team_abbr, yes_price_cents, captured_at, is_favorite)
                VALUES
                    (:gid, :fav_ticker, :fav_abbr, :fav_price, :captured, true),
                    (:gid, :dog_ticker, :dog_abbr, :dog_price, :captured, false)
                ON CONFLICT (game_id, team_abbr, captured_at) DO NOTHING
            """),
            {
                "gid": game_id,
                "fav_ticker": fav_ticker,
                "fav_abbr": fav_abbr,
                "fav_price": fav_price,
                "dog_ticker": dog_ticker,
                "dog_abbr": dog_abbr,
                "dog_price": dog_price,
                "captured": captured_at,
            },
        )
        result["snapshotted"] += 2

        # Get the favorite snapshot_id for the bet FK
        fav_snapshot = session.execute(
            text("""
                SELECT snapshot_id FROM market_snapshots
                WHERE game_id = :gid AND team_abbr = :abbr AND is_favorite = true
                ORDER BY captured_at DESC LIMIT 1
            """),
            {"gid": game_id, "abbr": fav_abbr},
        ).fetchone()

        if not fav_snapshot:
            logger.error("Snapshot not found after insert for game %s", game_id)
            return

        snapshot_id = fav_snapshot[0]

        # Compute contracts (build spec §4.7)
        contracts = STAKE_DOLLARS / (Decimal(fav_price) / Decimal(100))

        # Write the bet (UNIQUE on game_id prevents duplicates)
        try:
            session.execute(
                text("""
                    INSERT INTO bets
                        (game_id, snapshot_id, kalshi_ticker, team_abbr,
                         side, entry_price_cents, stake_dollars, contracts,
                         placed_at, mode)
                    VALUES
                        (:gid, :sid, :ticker, :abbr,
                         :side, :price, :stake, :contracts,
                         :placed, :mode)
                """),
                {
                    "gid": game_id,
                    "sid": snapshot_id,
                    "ticker": fav_ticker,
                    "abbr": fav_abbr,
                    "side": SIDE,
                    "price": fav_price,
                    "stake": STAKE_DOLLARS,
                    "contracts": contracts,
                    "placed": captured_at,
                    "mode": MODE,
                },
            )
            result["bet"] += 1
            logger.info(
                "BET placed: game=%s team=%s price=%dc contracts=%.4f",
                game_id, fav_abbr, fav_price, contracts,
            )
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                logger.debug("Duplicate bet for game %s (idempotent skip)", game_id)
            else:
                raise

        session.commit()


def _fetch_kalshi_price(game_id: str, team_abbr: str) -> tuple[int | None, str]:
    """Fetch the current YES ask price from Kalshi for a team's moneyline contract.

    Returns (price_in_cents, kalshi_ticker) or (None, "") if unavailable.

    TODO: This is a stub. Replace with actual Kalshi API call once the
    ticker format is confirmed via the discovery probe. The build spec §4.4
    recommends using the YES ask price.
    """
    # STUB — actual implementation needs:
    # 1. Determine exact Kalshi ticker format (e.g., KXMLB-25APR13-NYY)
    # 2. Call client.market_api.get_market(ticker=ticker)
    # 3. Extract yes_ask price in cents
    #
    # For now, return None so the engine safely skips until the probe is done.
    logger.debug(
        "STUB: _fetch_kalshi_price called for game=%s team=%s — "
        "replace with actual Kalshi API call after discovery probe",
        game_id, team_abbr,
    )
    return None, ""
