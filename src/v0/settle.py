"""Settlement poller.

Finds bets without settlement rows, checks Kalshi for market resolution,
and writes settlement records with correct outcome and PnL.

Build spec ref: §4.7 (fill model), §4.8 (settlement), §5 "Settlement poller".
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from v0.db import get_engine

logger = logging.getLogger(__name__)


def run_settle() -> dict:
    """Poll for unresolved bets and settle any that Kalshi has resolved.

    Returns {checked, settled, still_pending}.
    """
    engine = get_engine()
    result = {"checked": 0, "settled": 0, "still_pending": 0}

    with Session(engine) as session:
        # Find bets without a settlement row
        unsettled = session.execute(
            text("""
                SELECT b.bet_id, b.game_id, b.kalshi_ticker, b.team_abbr,
                       b.entry_price_cents, b.stake_dollars, b.contracts
                FROM bets b
                LEFT JOIN settlements s ON s.bet_id = b.bet_id
                WHERE s.settlement_id IS NULL
            """)
        ).fetchall()

    result["checked"] = len(unsettled)

    if not unsettled:
        logger.debug("No unsettled bets")
        return result

    for bet_id, game_id, ticker, team_abbr, price_cents, stake, contracts in unsettled:
        resolution = _check_kalshi_resolution(ticker)

        if resolution is None:
            result["still_pending"] += 1
            continue

        outcome, payout, pnl = _compute_settlement(
            resolution, Decimal(str(stake)), Decimal(str(contracts))
        )

        with Session(engine) as session:
            # Idempotency: UNIQUE(bet_id) prevents duplicates (build spec §4.9)
            try:
                session.execute(
                    text("""
                        INSERT INTO settlements
                            (bet_id, outcome, payout_dollars, pnl_dollars, settled_at)
                        VALUES
                            (:bet_id, :outcome, :payout, :pnl, :settled_at)
                    """),
                    {
                        "bet_id": bet_id,
                        "outcome": outcome,
                        "payout": payout,
                        "pnl": pnl,
                        "settled_at": datetime.now(timezone.utc),
                    },
                )
                session.commit()
                result["settled"] += 1
                logger.info(
                    "SETTLED: bet=%d game=%s team=%s outcome=%s pnl=$%.2f",
                    bet_id, game_id, team_abbr, outcome, pnl,
                )
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    logger.debug("Settlement already exists for bet %d", bet_id)
                else:
                    logger.error("Failed to settle bet %d: %s", bet_id, str(e)[:200])

    return result


def _compute_settlement(
    resolution: str,
    stake: Decimal,
    contracts: Decimal,
) -> tuple[str, Decimal, Decimal]:
    """Compute outcome, payout, and PnL per build spec §4.7.

    Returns (outcome, payout_dollars, pnl_dollars).
    """
    if resolution == "yes":
        # Our YES bet won
        payout = contracts * Decimal("1.00")
        pnl = payout - stake
        return "win", payout, pnl
    elif resolution == "no":
        # Our YES bet lost
        return "loss", Decimal("0.00"), -stake
    else:
        # Void — stake returned, PnL = 0
        return "void", stake, Decimal("0.00")


def _check_kalshi_resolution(ticker: str) -> str | None:
    """Check if a Kalshi market has resolved.

    Returns "yes", "no", or "void" if resolved, None if still open.

    TODO: This is a stub. Replace with actual Kalshi API call.
    The Kalshi SDK provides market.result after settlement.
    """
    logger.debug(
        "STUB: _check_kalshi_resolution called for ticker=%s — "
        "replace with actual Kalshi API call",
        ticker,
    )
    return None
