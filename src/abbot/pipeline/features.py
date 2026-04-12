"""Phase 6: Feature Engine.

Computes measurable signals from raw market snapshots that Monk-01
uses to classify state and detect transitions.

Features are computed per-market across time (multiple snapshots).
With 1 snapshot, only static features are available. As the 6-hour
ingest builds history, trend features activate.

Feature categories:
  - Price: last price, bid/ask midpoint, price change
  - Volume: total volume, volume velocity (change per snapshot)
  - Spread: bid-ask spread, spread trend
  - Interest: open interest, OI change
  - Timing: hours to expiration, % of life elapsed
  - Activity: whether market has any volume/OI at all
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine

logger = logging.getLogger(__name__)


@dataclass
class MarketFeatures:
    """Computed features for a single market at the latest snapshot."""

    ticker: str
    event_ticker: str
    series_ticker: str | None
    snapshot_count: int  # How many snapshots we have for this market

    # Price features
    last_price: float = 0.0
    midpoint: float = 0.0           # (yes_bid + yes_ask) / 2
    price_change: float = 0.0       # Change from first to last snapshot
    price_velocity: float = 0.0     # Price change per snapshot interval

    # Volume features
    volume: float = 0.0
    volume_change: float = 0.0      # Volume delta between snapshots
    volume_velocity: float = 0.0    # Volume change rate

    # Spread features
    spread: float = 0.0             # yes_ask - yes_bid
    spread_pct: float = 0.0         # spread / midpoint (relative tightness)
    spread_change: float = 0.0      # Spread narrowing (negative = tightening)

    # Interest features
    open_interest: float = 0.0
    oi_change: float = 0.0

    # Timing features
    hours_to_expiry: float = 0.0
    life_elapsed_pct: float = 0.0   # 0.0 = just opened, 1.0 = at expiry

    # Activity flags
    has_volume: bool = False
    has_bids: bool = False
    is_active: bool = False

    # Metadata
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def compute_features(prioritized_series: list[str] | None = None) -> list[MarketFeatures]:
    """Compute features for all markets in the latest snapshot.

    Args:
        prioritized_series: If set, only compute for markets in these series.
                           If None, compute for all markets.

    Returns:
        List of MarketFeatures, one per market.
    """
    engine = get_engine()
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        # Get the latest snapshot for each market (plus history if available)
        series_filter = ""
        if prioritized_series:
            tickers_str = ",".join(f"'{s}'" for s in prioritized_series)
            series_filter = f"AND e.series_ticker IN ({tickers_str})"

        # Latest snapshot per market
        latest_rows = session.execute(text(f"""
            SELECT
                m.ticker,
                m.event_ticker,
                e.series_ticker,
                m.data,
                m.ingested_at
            FROM raw_market_snapshots m
            LEFT JOIN raw_event_snapshots e ON m.event_ticker = e.event_ticker
            WHERE m.id IN (
                SELECT DISTINCT ON (ticker) id
                FROM raw_market_snapshots
                ORDER BY ticker, ingested_at DESC
            )
            {series_filter}
        """)).fetchall()

        logger.info("Computing features for %d markets", len(latest_rows))

        # Get snapshot counts per market (for trend features)
        snapshot_counts = dict(session.execute(text("""
            SELECT ticker, count(*) FROM raw_market_snapshots GROUP BY ticker
        """)).fetchall())

        # Get earliest snapshot per market (for price_change)
        earliest_rows = {}
        if any(v > 1 for v in snapshot_counts.values()):
            earliest_data = session.execute(text("""
                SELECT DISTINCT ON (ticker) ticker, data
                FROM raw_market_snapshots
                ORDER BY ticker, ingested_at ASC
            """)).fetchall()
            earliest_rows = {row[0]: row[1] for row in earliest_data}

    features = []
    for ticker, event_ticker, series_ticker, data, ingested_at in latest_rows:
        f = _compute_single(
            ticker=ticker,
            event_ticker=event_ticker or "",
            series_ticker=series_ticker,
            data=data,
            earliest_data=earliest_rows.get(ticker),
            snapshot_count=snapshot_counts.get(ticker, 1),
            now=now,
        )
        features.append(f)

    logger.info("Computed features for %d markets", len(features))
    return features


def _compute_single(
    ticker: str,
    event_ticker: str,
    series_ticker: str | None,
    data: dict,
    earliest_data: dict | None,
    snapshot_count: int,
    now: datetime,
) -> MarketFeatures:
    """Compute features for a single market."""

    yes_bid = _float(data.get("yes_bid_dollars", "0"))
    yes_ask = _float(data.get("yes_ask_dollars", "0"))
    last_price = _float(data.get("last_price_dollars", "0"))
    volume = _float(data.get("volume_fp", "0"))
    oi = _float(data.get("open_interest_fp", "0"))
    status = data.get("status", "")

    midpoint = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 0.0
    spread = yes_ask - yes_bid if yes_ask > yes_bid else 0.0
    spread_pct = spread / midpoint if midpoint > 0 else 0.0

    # Timing
    close_str = data.get("close_time") or data.get("expiration_time")
    open_str = data.get("open_time") or data.get("created_time")
    hours_to_expiry = 0.0
    life_elapsed_pct = 0.0

    if close_str:
        try:
            close_dt = datetime.fromisoformat(str(close_str))
            hours_to_expiry = max(0, (close_dt - now).total_seconds() / 3600)
            if open_str:
                open_dt = datetime.fromisoformat(str(open_str))
                total_life = (close_dt - open_dt).total_seconds()
                elapsed = (now - open_dt).total_seconds()
                if total_life > 0:
                    life_elapsed_pct = min(1.0, max(0.0, elapsed / total_life))
        except (ValueError, TypeError):
            pass

    # Trend features (require multiple snapshots)
    price_change = 0.0
    price_velocity = 0.0
    volume_change = 0.0
    spread_change = 0.0
    oi_change = 0.0

    if earliest_data and snapshot_count > 1:
        old_price = _float(earliest_data.get("last_price_dollars", "0"))
        old_volume = _float(earliest_data.get("volume_fp", "0"))
        old_bid = _float(earliest_data.get("yes_bid_dollars", "0"))
        old_ask = _float(earliest_data.get("yes_ask_dollars", "0"))
        old_oi = _float(earliest_data.get("open_interest_fp", "0"))
        old_spread = old_ask - old_bid if old_ask > old_bid else 0.0

        price_change = last_price - old_price
        price_velocity = price_change / snapshot_count
        volume_change = volume - old_volume
        spread_change = spread - old_spread  # negative = tightening (good)
        oi_change = oi - old_oi

    return MarketFeatures(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker=series_ticker,
        snapshot_count=snapshot_count,
        last_price=last_price,
        midpoint=midpoint,
        price_change=price_change,
        price_velocity=price_velocity,
        volume=volume,
        volume_change=volume_change,
        volume_velocity=volume_change / snapshot_count if snapshot_count > 1 else 0.0,
        spread=spread,
        spread_pct=spread_pct,
        spread_change=spread_change,
        open_interest=oi,
        oi_change=oi_change,
        hours_to_expiry=hours_to_expiry,
        life_elapsed_pct=life_elapsed_pct,
        has_volume=volume > 0,
        has_bids=yes_bid > 0,
        is_active=status == "active",
    )


def _float(val) -> float:
    """Safely convert to float."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
