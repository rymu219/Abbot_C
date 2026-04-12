"""Raw data ingestion from Kalshi API.

Pulls markets, events, series, and trades. Stores raw JSON snapshots
in PostgreSQL with timestamps and ingest IDs for auditability.

Handles:
- Pagination (cursor-based)
- Retries with exponential backoff
- Rate limiting (18 req/s, under the 20/s limit)
- Chunked commits (one commit per API page, not one giant transaction)
- Malformed/partial responses (logged, not fatal)
- All failures logged to ingest_log table

Usage:
    from abbot.kalshi.ingest import run_ingest
    result = run_ingest("markets")
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.db.models.raw import (
    IngestLog,
    RawEventSnapshot,
    RawMarketSnapshot,
    RawSeriesSnapshot,
    RawTradeSnapshot,
)
from abbot.kalshi.auth import build_auth
from abbot.kalshi.client import get_kalshi_client
from abbot.kalshi.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

# Shared rate limiter across all ingest calls
_rate_limiter = RateLimiter(calls_per_second=18.0)

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds


def _retry(fn, *args, retries: int = MAX_RETRIES, **kwargs):
    """Call fn with exponential backoff on failure."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            _rate_limiter.wait()
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs",
                    attempt + 1, retries + 1, str(e)[:200], wait,
                )
                time.sleep(wait)
            else:
                logger.error("All %d attempts failed: %s", retries + 1, str(e)[:200])
    raise last_exc


def _new_ingest_id() -> str:
    return uuid.uuid4().hex[:16]


def _jsonb_safe(obj: dict) -> dict:
    """Convert a dict to be JSONB-safe (serialize datetimes to ISO strings)."""
    return json.loads(json.dumps(obj, default=str))


def _write_ingest_log(
    engine, ingest_id: str, ingest_type: str, status: str,
    count: int, error: str | None = None,
    started_at: datetime | None = None,
) -> None:
    """Write or update the ingest log in its own transaction."""
    with Session(engine) as session:
        existing = session.query(IngestLog).filter_by(ingest_id=ingest_id).first()
        if existing:
            existing.status = status
            existing.records_count = count
            existing.error_message = error
            existing.completed_at = datetime.now(timezone.utc)
        else:
            session.add(IngestLog(
                ingest_id=ingest_id,
                ingest_type=ingest_type,
                status=status,
                records_count=count,
                error_message=error,
                started_at=started_at or datetime.now(timezone.utc),
            ))
        session.commit()


# --- Payload slimming (free tier storage optimization) ---

# Fields we need for the pipeline. Everything else is dropped to save space.
_MARKET_KEEP_FIELDS = {
    "ticker", "event_ticker", "market_type", "title",
    "created_time", "open_time", "close_time", "expiration_time",
    "expected_expiration_time", "status", "result",
    "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
    "last_price_dollars", "previous_price_dollars",
    "volume_fp", "volume_24h_fp", "open_interest_fp", "liquidity_dollars",
    "yes_bid_size_fp", "yes_ask_size_fp",
    "can_close_early", "strike_type", "custom_strike",
    "settlement_timer_seconds", "notional_value_dollars",
    "category",
}

_EVENT_KEEP_FIELDS = {
    "event_ticker", "series_ticker", "title", "sub_title",
    "category", "mutually_exclusive", "strike_period",
    "collateral_return_type", "last_updated_ts", "strike_date",
}


def _slim_market(data: dict) -> dict:
    """Keep only pipeline-relevant fields from a market payload."""
    return {k: v for k, v in data.items() if k in _MARKET_KEEP_FIELDS}


def _slim_event(data: dict) -> dict:
    """Keep only pipeline-relevant fields from an event payload."""
    return {k: v for k, v in data.items() if k in _EVENT_KEEP_FIELDS}


def _extract_series_ticker(event_ticker: str | None) -> str | None:
    """Try to extract series ticker from event ticker."""
    if not event_ticker:
        return None
    parts = event_ticker.split("-")
    if len(parts) >= 2:
        return parts[0]
    return None


# --- Market ingestion ---


def ingest_markets(series_ticker: str | None = None, max_pages: int = 0) -> dict:
    """Pull markets from Kalshi and store raw snapshots.

    Args:
        series_ticker: If set, only pull markets for this series.
        max_pages: If > 0, stop after this many pages (1000 records/page).
                   0 means no limit. Useful for controlling scope.

    Each API page (1000 records) is committed in its own transaction.
    """
    client = get_kalshi_client()
    engine = get_engine()
    ingest_id = _new_ingest_id()
    count = 0
    pages = 0
    started_at = datetime.now(timezone.utc)

    _write_ingest_log(engine, ingest_id, "markets", "running", 0, started_at=started_at)

    try:
        cursor = None
        while True:
            if max_pages > 0 and pages >= max_pages:
                break

            kwargs = {"limit": 1000}
            if cursor:
                kwargs["cursor"] = cursor
            if series_ticker:
                kwargs["series_ticker"] = series_ticker

            resp = _retry(client._market_api.get_markets, **kwargs)
            markets = resp.markets or []

            if not markets:
                break

            # Commit this page in its own transaction
            with Session(engine) as session:
                for m in markets:
                    full = _jsonb_safe(m.to_dict())
                    data = _slim_market(full)
                    session.add(
                        RawMarketSnapshot(
                            ingest_id=ingest_id,
                            ticker=full.get("ticker", ""),
                            event_ticker=full.get("event_ticker"),
                            series_ticker=_extract_series_ticker(full.get("event_ticker")),
                            data=data,
                        )
                    )
                session.commit()

            count += len(markets)
            pages += 1
            logger.info("Markets ingested: %d (page %d)", count, pages)

            cursor = resp.cursor
            if not cursor:
                break

        _write_ingest_log(engine, ingest_id, "markets", "success", count, started_at=started_at)
        logger.info("Market ingest complete: %d records (ingest_id=%s)", count, ingest_id)

    except Exception as e:
        _write_ingest_log(engine, ingest_id, "markets", "failed", count, str(e)[:1000], started_at)
        raise

    return {"ingest_id": ingest_id, "type": "markets", "count": count, "status": "success"}


# --- Event ingestion ---


def ingest_events(max_pages: int = 0) -> dict:
    """Pull events from Kalshi and store raw snapshots.

    Args:
        max_pages: If > 0, stop after this many pages (200 records/page).
    """
    client = get_kalshi_client()
    engine = get_engine()
    ingest_id = _new_ingest_id()
    count = 0
    pages = 0
    started_at = datetime.now(timezone.utc)

    _write_ingest_log(engine, ingest_id, "events", "running", 0, started_at=started_at)

    try:
        cursor = None
        while True:
            if max_pages > 0 and pages >= max_pages:
                break
            kwargs = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            resp = _retry(client._events_api.get_events, **kwargs)
            events = resp.events or []

            if not events:
                break

            with Session(engine) as session:
                for e in events:
                    full = _jsonb_safe(e.to_dict())
                    data = _slim_event(full)
                    session.add(
                        RawEventSnapshot(
                            ingest_id=ingest_id,
                            event_ticker=full.get("event_ticker", ""),
                            series_ticker=full.get("series_ticker"),
                            data=data,
                        )
                    )
                session.commit()

            count += len(events)
            pages += 1
            logger.info("Events ingested: %d (page %d)", count, pages)

            cursor = resp.cursor
            if not cursor:
                break

        _write_ingest_log(engine, ingest_id, "events", "success", count, started_at=started_at)
        logger.info("Event ingest complete: %d records (ingest_id=%s)", count, ingest_id)

    except Exception as e:
        _write_ingest_log(engine, ingest_id, "events", "failed", count, str(e)[:1000], started_at)
        raise

    return {"ingest_id": ingest_id, "type": "events", "count": count, "status": "success"}


# --- Series ingestion (raw HTTP — SDK has a deserialization bug) ---


def ingest_series() -> dict:
    """Pull all series from Kalshi via raw HTTP and store snapshots."""
    auth = build_auth()
    engine = get_engine()
    ingest_id = _new_ingest_id()
    count = 0
    started_at = datetime.now(timezone.utc)
    base_url = "https://api.elections.kalshi.com/trade-api/v2/series"

    _write_ingest_log(engine, ingest_id, "series", "running", 0, started_at=started_at)

    try:
        cursor = None
        with httpx.Client(timeout=30.0) as http:
            while True:
                _rate_limiter.wait()
                params = {}
                if cursor:
                    params["cursor"] = cursor

                headers = auth.create_auth_headers("GET", "/trade-api/v2/series")
                resp = http.get(base_url, headers=headers, params=params)
                resp.raise_for_status()
                body = resp.json()

                series_list = body.get("series", [])
                if not series_list:
                    break

                with Session(engine) as session:
                    for s in series_list:
                        session.add(
                            RawSeriesSnapshot(
                                ingest_id=ingest_id,
                                series_ticker=s.get("ticker", ""),
                                data=s,
                            )
                        )
                    session.commit()

                count += len(series_list)
                logger.info("Series ingested: %d", count)

                cursor = body.get("cursor")
                if not cursor:
                    break

        _write_ingest_log(engine, ingest_id, "series", "success", count, started_at=started_at)
        logger.info("Series ingest complete: %d records (ingest_id=%s)", count, ingest_id)

    except Exception as e:
        _write_ingest_log(engine, ingest_id, "series", "failed", count, str(e)[:1000], started_at)
        raise

    return {"ingest_id": ingest_id, "type": "series", "count": count, "status": "success"}


# --- Trade ingestion ---


def ingest_trades(limit: int = 10000) -> dict:
    """Pull recent trades from Kalshi and store snapshots."""
    client = get_kalshi_client()
    engine = get_engine()
    ingest_id = _new_ingest_id()
    count = 0
    started_at = datetime.now(timezone.utc)

    _write_ingest_log(engine, ingest_id, "trades", "running", 0, started_at=started_at)

    try:
        cursor = None
        while count < limit:
            page_size = min(1000, limit - count)
            kwargs = {"limit": page_size}
            if cursor:
                kwargs["cursor"] = cursor

            resp = _retry(client._market_api.get_trades, **kwargs)
            trades = resp.trades or []

            if not trades:
                break

            with Session(engine) as session:
                for t in trades:
                    data = _jsonb_safe(t.to_dict())
                    session.add(
                        RawTradeSnapshot(
                            ingest_id=ingest_id,
                            trade_id=data.get("trade_id", ""),
                            ticker=data.get("ticker", ""),
                            data=data,
                        )
                    )
                session.commit()

            count += len(trades)
            logger.info("Trades ingested: %d", count)

            cursor = resp.cursor
            if not cursor:
                break

        _write_ingest_log(engine, ingest_id, "trades", "success", count, started_at=started_at)
        logger.info("Trade ingest complete: %d records (ingest_id=%s)", count, ingest_id)

    except Exception as e:
        _write_ingest_log(engine, ingest_id, "trades", "failed", count, str(e)[:1000], started_at)
        raise

    return {"ingest_id": ingest_id, "type": "trades", "count": count, "status": "success"}


# --- Full ingest ---


def run_ingest(
    ingest_type: str = "all",
    trade_limit: int = 10000,
    market_max_pages: int = 0,
    event_max_pages: int = 0,
    series_ticker: str | None = None,
) -> list[dict]:
    """Run ingestion for one or all data types.

    Args:
        ingest_type: One of "markets", "events", "series", "trades", or "all".
        trade_limit: Max trades to pull (only for trades ingest).
        market_max_pages: Max pages for market ingest (0=unlimited, 1000 records/page).
        series_ticker: If set, only pull markets for this series.

    Returns:
        List of result dicts with ingest_id, type, count, status.
    """
    runners = {
        "markets": lambda: ingest_markets(
            series_ticker=series_ticker, max_pages=market_max_pages
        ),
        "events": lambda: ingest_events(max_pages=event_max_pages),
        "series": ingest_series,
        "trades": lambda: ingest_trades(limit=trade_limit),
    }

    if ingest_type == "all":
        types_to_run = ["markets", "events", "series", "trades"]
    elif ingest_type in runners:
        types_to_run = [ingest_type]
    else:
        raise ValueError(
            f"Unknown ingest type: {ingest_type}. Use: {list(runners.keys())} or 'all'"
        )

    results = []
    for t in types_to_run:
        logger.info("Starting %s ingest...", t)
        try:
            result = runners[t]()
            results.append(result)
        except Exception as e:
            logger.error("%s ingest failed: %s", t, str(e)[:200])
            results.append({"type": t, "status": "failed", "error": str(e)[:200]})

    return results
