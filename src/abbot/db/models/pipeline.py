"""Pipeline persistence models.

Stores pipeline outputs, Monk configs, and trade records so they
survive page loads and build queryable history.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from abbot.db.models import Base


class StoredMonkConfig(Base):
    """Persisted Monk configuration with version history."""

    __tablename__ = "monk_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    test_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    deployment_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="analysis_only")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonkTrade(Base):
    """Record of a paper or live trade executed by a Monk."""

    __tablename__ = "monk_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monk_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(256), nullable=False)
    ticker: Mapped[str] = mapped_column(String(256), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # "yes" or "no"
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    is_paper: Mapped[bool] = mapped_column(nullable=False, default=True)

    # Fill/settlement
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open, closed, canceled
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineRun(Base):
    """Record of each pipeline execution."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)  # distill, scan, candidates
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
