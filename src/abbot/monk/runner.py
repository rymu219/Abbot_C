"""Monk Execution Runner.

Runs active Monks (paper or live) against current market data.
Called on each scan cycle by the scheduler.

For each active Monk:
  1. Pull current markets for its family
  2. Check entry rules against each market
  3. If entry triggers fire → place trade (paper or live)
  4. Check exit rules on open positions
  5. Record results to monk_trades table
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.db.models.pipeline import MonkTrade, StoredMonkConfig
from abbot.kalshi.client import get_kalshi_client
from abbot.kalshi.rate_limit import RateLimiter
from abbot.types import MonkConfig

logger = logging.getLogger(__name__)

_rate_limiter = RateLimiter(calls_per_second=18.0)


def run_active_monks() -> list[dict]:
    """Execute one scan cycle for all active Monks.

    Returns list of results per Monk.
    """
    engine = get_engine()
    results = []

    with Session(engine) as session:
        # Get all active Monks (paper or live)
        active_configs = session.execute(
            select(StoredMonkConfig).where(
                StoredMonkConfig.lifecycle_status.in_(["paper", "probation", "live", "scaled"]),
                StoredMonkConfig.approval_status == "approved",
            )
        ).scalars().all()

    if not active_configs:
        logger.debug("No active Monks to run")
        return results

    logger.info("Running %d active Monks", len(active_configs))

    for stored in active_configs:
        try:
            result = _run_single_monk(stored)
            results.append(result)
        except Exception as e:
            logger.error("Monk %s failed: %s", stored.name, str(e)[:200])
            results.append({
                "monk": stored.name,
                "status": "error",
                "error": str(e)[:200],
            })

    return results


def _run_single_monk(stored: StoredMonkConfig) -> dict:
    """Run one scan cycle for a single Monk."""
    config = MonkConfig.model_validate(stored.config_data)
    family_id = stored.family_id
    is_paper = stored.deployment_mode in ("paper_only", "analysis_only")

    client = get_kalshi_client()
    engine = get_engine()

    # Get current markets for this family
    _rate_limiter.wait()
    try:
        resp = client._market_api.get_markets(limit=100, series_ticker=family_id)
        markets = resp.markets or []
    except Exception as e:
        logger.warning("Failed to pull markets for %s: %s", family_id, str(e)[:100])
        return {"monk": stored.name, "status": "api_error", "markets": 0}

    active_markets = [m for m in markets if m.status == "active"]

    # Get open positions for this Monk
    with Session(engine) as session:
        open_trades = session.execute(
            select(MonkTrade).where(
                MonkTrade.monk_name == stored.name,
                MonkTrade.status == "open",
            )
        ).scalars().all()
        open_tickers = {t.ticker for t in open_trades}

    # Check entry rules for each market
    entry_thresholds = config.entry.thresholds or {}
    min_volume = entry_thresholds.get("min_volume", 10)
    spread_rules = config.entry.spread_rules or {}
    max_spread_pct = spread_rules.get("max_spread_pct", 0.30)
    timing_rules = config.entry.timing or {}
    min_hours = timing_rules.get("min_hours_to_expiry", 2)

    risk_rules = config.risk
    max_concurrent = (risk_rules.additional_limits or {}).get("max_concurrent_positions", 3)
    max_trades_day = (risk_rules.additional_limits or {}).get("max_trades_per_day", 10)

    new_trades = 0
    for m in active_markets:
        # Skip if already have position
        if m.ticker in open_tickers:
            continue

        # Enforce position limits
        if len(open_tickers) + new_trades >= max_concurrent:
            break

        # Volume check
        volume = float(m.volume_fp or "0")
        if volume < min_volume:
            continue

        # Price check (need valid bid/ask)
        yes_bid = float(m.yes_bid_dollars or "0")
        yes_ask = float(m.yes_ask_dollars or "0")
        last_price = float(m.last_price_dollars or "0")

        if yes_bid <= 0 and yes_ask <= 0:
            continue

        # Spread check
        spread = yes_ask - yes_bid if yes_ask > yes_bid else 0.0
        midpoint = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else last_price
        if midpoint > 0 and spread / midpoint > max_spread_pct:
            continue

        # Timing check
        try:
            close_str = getattr(m, "close_time", None) or getattr(m, "expiration_time", None)
            if close_str:
                close_dt = close_str if isinstance(close_str, datetime) else datetime.fromisoformat(str(close_str))
                hours_left = (close_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_left < min_hours:
                    continue
        except (ValueError, TypeError):
            pass

        # Price must be in tradeable range
        if last_price <= 0.05 or last_price >= 0.95:
            continue

        # --- ENTRY: Use strategy-derived side and price from config ---
        preferred_side = entry_thresholds.get("preferred_side", "yes")
        entry_price_max = entry_thresholds.get("entry_price_max", 0.50)

        if preferred_side == "yes":
            if last_price > entry_price_max:
                continue  # Price too high for YES entry
            side = "yes"
            entry_price = yes_ask if yes_ask > 0 else last_price
        else:  # "no"
            no_price = 1.0 - last_price
            no_entry_max = 1.0 - entry_price_max
            if no_price > no_entry_max:
                continue  # NO price too high
            side = "no"
            entry_price = 1.0 - yes_bid if yes_bid > 0 else no_price

        if entry_price <= 0:
            continue

        trade_size = config.risk.max_position_size or 10.0

        # Record the trade
        with Session(engine) as session:
            trade = MonkTrade(
                monk_name=stored.name,
                family_id=family_id,
                ticker=m.ticker,
                side=side,
                entry_price=round(entry_price, 4),
                size=trade_size,
                is_paper=is_paper,
                status="open",
            )
            session.add(trade)
            session.commit()

        new_trades += 1

        if is_paper:
            logger.info(
                "[PAPER] %s entered %s %s @ $%.4f on %s",
                stored.name, side.upper(), trade_size, entry_price, m.ticker,
            )
        else:
            # Live execution would go here via deploy.execute_order()
            logger.info(
                "[LIVE] %s entered %s %s @ $%.4f on %s",
                stored.name, side.upper(), trade_size, entry_price, m.ticker,
            )

    # Check exit conditions on open positions
    closed = 0
    with Session(engine) as session:
        open_trades = session.execute(
            select(MonkTrade).where(
                MonkTrade.monk_name == stored.name,
                MonkTrade.status == "open",
            )
        ).scalars().all()

        market_map = {m.ticker: m for m in markets}

        for trade in open_trades:
            market = market_map.get(trade.ticker)
            if not market:
                continue

            # Check if market has settled
            if market.status == "finalized" and market.result:
                settlement = 1.0 if market.result == "yes" else 0.0
                if trade.side == "yes":
                    pnl = (settlement - trade.entry_price) * trade.size
                else:
                    pnl = ((1.0 - settlement) - trade.entry_price) * trade.size

                trade.exit_price = settlement
                trade.pnl = round(pnl, 2)
                trade.status = "closed"
                trade.exit_reason = f"settled_{market.result}"
                trade.closed_at = datetime.now(timezone.utc)
                closed += 1

                logger.info(
                    "[%s] %s closed %s on %s: P&L=$%.2f (%s)",
                    "PAPER" if trade.is_paper else "LIVE",
                    stored.name, trade.side, trade.ticker, pnl, market.result,
                )

        session.commit()

    return {
        "monk": stored.name,
        "family": family_id,
        "active_markets": len(active_markets),
        "new_entries": new_trades,
        "closed": closed,
        "open_positions": len(open_tickers) + new_trades - closed,
        "is_paper": is_paper,
        "status": "ok",
    }
