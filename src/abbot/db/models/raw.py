"""Raw ingested data tables.

Stores the raw Kalshi API responses with timestamps and metadata.
These tables are append-only snapshots — each ingest run creates new rows.
This preserves the full history for auditability (Requirements Section 6).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from abbot.db.models import Base


class RawMarketSnapshot(Base):
    """Raw market data from Kalshi get_markets endpoint.

    One row per market per ingest run.
    """

    __tablename__ = "raw_market_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(256), nullable=False)
    event_ticker: Mapped[str] = mapped_column(String(256), nullable=True)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_raw_market_ticker_ingested", "ticker", "ingested_at"),
    )


class RawEventSnapshot(Base):
    """Raw event data from Kalshi get_events endpoint."""

    __tablename__ = "raw_event_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_ticker: Mapped[str] = mapped_column(String(256), nullable=False)
    series_ticker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_raw_event_ticker_ingested", "event_ticker", "ingested_at"),
    )


class RawSeriesSnapshot(Base):
    """Raw series data from Kalshi get_series endpoint."""

    __tablename__ = "raw_series_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    series_ticker: Mapped[str] = mapped_column(String(256), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_raw_series_ticker_ingested", "series_ticker", "ingested_at"),
    )


class RawTradeSnapshot(Base):
    """Raw trade data from Kalshi get_trades endpoint."""

    __tablename__ = "raw_trade_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingest_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trade_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ticker: Mapped[str] = mapped_column(String(256), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_raw_trade_ticker_ingested", "ticker", "ingested_at"),
    )


class IngestLog(Base):
    """Log of each ingestion run for auditability.

    Every ingest run gets a unique ingest_id that links to the raw snapshot rows.
    """

    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingest_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ingest_type: Mapped[str] = mapped_column(String(32), nullable=False)  # markets, events, series, trades
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # running, success, failed
    records_count: Mapped[int] = mapped_column(BigInteger, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
