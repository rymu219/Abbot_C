"""Historical data backfill from Kalshi.

Pulls settled markets with outcomes for backtesting. Targets series
with high volume and large numbers of settled markets.

This is the fast path to getting the testing framework producing
real verdicts — minutes of backfill instead of weeks of polling.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.db.models.raw import IngestLog, RawMarketSnapshot
from abbot.kalshi.client import get_kalshi_client
from abbot.kalshi.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

_rate_limiter = RateLimiter(calls_per_second=18.0)

# Top series by volume and settled market count — the real opportunities
BACKFILL_SERIES = [
    # Sports — highest volume, most settled markets
    "KXNBAGAME",       # NBA Game — $3.47B volume
    "KXNHLGAME",       # NHL Game — $407M
    "KXNBASPREAD",     # NBA Spread — $91M
    "KXNBATOTAL",      # NBA Total — $83M
    "KXMLBTOTAL",      # MLB Total — $42M
    "KXMLBSPREAD",     # MLB Spread — $35M
    "KXNHLTOTAL",      # NHL Total — $16M
    "KXNHLSPREAD",     # NHL Spread — $12M
    "KXMLBHR",         # MLB Home Runs — $2.3M
    "KXMLBKS",         # MLB Strikeouts — $2M
    # Finance — smaller but structured
    "KXINXU",          # S&P 500 above/below
    "KXNASDAQ100U",    # Nasdaq above/below
    "KXETHD",          # ETH directional
]

# Fields to keep (slimmed for storage)
_KEEP_FIELDS = {
    "ticker", "event_ticker", "market_type", "title",
    "created_time", "open_time", "close_time", "expiration_time",
    "status", "result",
    "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
    "last_price_dollars", "previous_price_dollars",
    "volume_fp", "volume_24h_fp", "open_interest_fp", "liquidity_dollars",
    "yes_bid_size_fp", "yes_ask_size_fp",
    "settlement_timer_seconds", "notional_value_dollars",
    "settlement_value_dollars", "settlement_ts",
    "strike_type", "custom_strike",
}


def _jsonb_safe(obj: dict) -> dict:
    return json.loads(json.dumps(obj, default=str))


def _slim(data: dict) -> dict:
    return {k: v for k, v in data.items() if k in _KEEP_FIELDS}


def backfill_series(
    series_ticker: str,
    max_pages: int = 0,
) -> dict:
    """Pull all markets (including settled) for a series and store them.

    This gives us settled markets with outcomes for backtesting.

    Args:
        series_ticker: The series to backfill.
        max_pages: Limit pages (0 = unlimited). Each page = 1000 markets.

    Returns:
        Result dict with counts.
    """
    client = get_kalshi_client()
    engine = get_engine()
    ingest_id = uuid.uuid4().hex[:16]
    count = 0
    settled = 0
    pages = 0
    started_at = datetime.now(timezone.utc)

    # Log start
    with Session(engine) as session:
        session.add(IngestLog(
            ingest_id=ingest_id,
            ingest_type=f"backfill:{series_ticker}",
            status="running",
            records_count=0,
            started_at=started_at,
        ))
        session.commit()

    try:
        cursor = None
        while True:
            if max_pages > 0 and pages >= max_pages:
                break

            _rate_limiter.wait()
            kwargs = {"limit": 1000, "series_ticker": series_ticker}
            if cursor:
                kwargs["cursor"] = cursor

            resp = client._market_api.get_markets(**kwargs)
            markets = resp.markets or []

            if not markets:
                break

            with Session(engine) as session:
                for m in markets:
                    full = _jsonb_safe(m.to_dict())
                    data = _slim(full)
                    session.add(RawMarketSnapshot(
                        ingest_id=ingest_id,
                        ticker=full.get("ticker", ""),
                        event_ticker=full.get("event_ticker"),
                        series_ticker=series_ticker,
                        data=data,
                    ))
                    count += 1
                    if full.get("result"):
                        settled += 1
                session.commit()

            pages += 1
            logger.info(
                "Backfill %s: %d markets (%d settled) — page %d",
                series_ticker, count, settled, pages,
            )

            cursor = resp.cursor
            if not cursor:
                break

        # Update log
        with Session(engine) as session:
            log = session.query(IngestLog).filter_by(ingest_id=ingest_id).first()
            if log:
                log.status = "success"
                log.records_count = count
                log.completed_at = datetime.now(timezone.utc)
            session.commit()

        logger.info(
            "Backfill complete: %s — %d markets (%d settled)",
            series_ticker, count, settled,
        )

    except Exception as e:
        with Session(engine) as session:
            log = session.query(IngestLog).filter_by(ingest_id=ingest_id).first()
            if log:
                log.status = "failed"
                log.records_count = count
                log.error_message = str(e)[:1000]
                log.completed_at = datetime.now(timezone.utc)
            session.commit()
        raise

    return {
        "series": series_ticker,
        "total": count,
        "settled": settled,
        "pages": pages,
        "ingest_id": ingest_id,
        "status": "success",
    }


def run_backfill(
    series_list: list[str] | None = None,
    max_pages_per_series: int = 5,
) -> list[dict]:
    """Backfill historical data for multiple series.

    Args:
        series_list: Series to backfill. If None, uses BACKFILL_SERIES.
        max_pages_per_series: Max pages per series (5 pages = 5000 markets).

    Returns:
        List of result dicts.
    """
    if series_list is None:
        series_list = BACKFILL_SERIES

    results = []
    for series in series_list:
        logger.info("Starting backfill for %s...", series)
        try:
            result = backfill_series(series, max_pages=max_pages_per_series)
            results.append(result)
        except Exception as e:
            logger.error("Backfill failed for %s: %s", series, str(e)[:200])
            results.append({
                "series": series,
                "status": "failed",
                "error": str(e)[:200],
            })

    total = sum(r.get("total", 0) for r in results)
    settled = sum(r.get("settled", 0) for r in results)
    logger.info("Backfill complete: %d total markets, %d settled", total, settled)

    return results
