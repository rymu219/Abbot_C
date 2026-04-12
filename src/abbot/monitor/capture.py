"""Phase G: Capture Accounting.

Measures what each Monk catches vs misses, per Requirements Section 9.

Core metrics:
  - Portfolio Capture: captured / total eligible
  - Monk Capture: units acted on / units eligible for that Monk
  - Uncaptured: eligible but no Monk acted — WHY?
  - Overlap: multiple Monks acted on same opportunity
  - Unique Contribution: units captured only by this Monk

The uncaptured analysis drives Monk refinement and new Monk creation.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.db.models.pipeline import MonkTrade, StoredMonkConfig

logger = logging.getLogger(__name__)


@dataclass
class OpportunityUnit:
    """A single eligible opportunity that could have been acted on."""

    ticker: str
    family_id: str
    volume: float
    last_price: float
    spread: float
    hours_to_expiry: float
    result: str | None  # yes/no if settled, None if still open
    eligible: bool = True
    reason_not_eligible: str | None = None


@dataclass
class CaptureEvent:
    """Whether a Monk acted on an opportunity and why/why not."""

    ticker: str
    monk_name: str
    captured: bool
    reason: str  # "traded", "volume_too_low", "spread_too_wide", "max_positions", "price_extreme", "timing"


@dataclass
class MonkCaptureMetrics:
    """Capture metrics for a single Monk."""

    monk_name: str
    family_id: str
    eligible_units: int = 0
    captured_units: int = 0
    uncaptured_units: int = 0
    capture_rate: float = 0.0

    # Why uncaptured
    uncaptured_reasons: dict[str, int] = field(default_factory=dict)

    # P&L on captured
    realized_pnl: float = 0.0
    avg_pnl_per_capture: float = 0.0


@dataclass
class PortfolioCaptureMetrics:
    """Aggregate capture across all Monks."""

    total_eligible: int = 0
    total_captured: int = 0
    total_uncaptured: int = 0
    portfolio_capture_rate: float = 0.0
    overlap_count: int = 0
    overlap_rate: float = 0.0

    monk_metrics: list[MonkCaptureMetrics] = field(default_factory=list)

    # Top uncaptured reasons across all Monks
    top_uncaptured_reasons: dict[str, int] = field(default_factory=dict)

    # Suggestions for new Monks or refinements
    suggestions: list[str] = field(default_factory=list)

    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "total_eligible": self.total_eligible,
            "total_captured": self.total_captured,
            "total_uncaptured": self.total_uncaptured,
            "portfolio_capture_rate": round(self.portfolio_capture_rate, 3),
            "overlap_count": self.overlap_count,
            "overlap_rate": round(self.overlap_rate, 3),
            "monks": [
                {
                    "name": m.monk_name,
                    "family": m.family_id,
                    "eligible": m.eligible_units,
                    "captured": m.captured_units,
                    "capture_rate": round(m.capture_rate, 3),
                    "pnl": round(m.realized_pnl, 2),
                    "uncaptured_reasons": m.uncaptured_reasons,
                }
                for m in self.monk_metrics
            ],
            "top_uncaptured_reasons": self.top_uncaptured_reasons,
            "suggestions": self.suggestions,
        }


def compute_capture_metrics() -> PortfolioCaptureMetrics:
    """Compute capture metrics across all active Monks.

    For each active Monk:
    1. Get all markets in its family from the latest ingest
    2. Determine which are "eligible" (active, has volume, acceptable spread)
    3. Check which eligible markets have trades from this Monk
    4. Compute capture rate and analyze uncaptured reasons
    """
    engine = get_engine()
    portfolio = PortfolioCaptureMetrics()

    with Session(engine) as session:
        # Get active Monks
        active_configs = session.execute(
            select(StoredMonkConfig).where(
                StoredMonkConfig.lifecycle_status.in_(["paper", "probation", "live", "scaled"]),
                StoredMonkConfig.approval_status == "approved",
            )
        ).scalars().all()

        if not active_configs:
            return portfolio

        all_captured_tickers: dict[str, list[str]] = {}  # ticker → [monk_names]

        for config in active_configs:
            monk_metrics = _compute_monk_capture(session, config)
            portfolio.monk_metrics.append(monk_metrics)

            # Track for overlap detection
            traded_tickers = session.execute(
                select(MonkTrade.ticker).where(
                    MonkTrade.monk_name == config.name,
                )
            ).scalars().all()

            for t in traded_tickers:
                all_captured_tickers.setdefault(t, []).append(config.name)

        # Portfolio-level aggregation
        portfolio.total_eligible = sum(m.eligible_units for m in portfolio.monk_metrics)
        portfolio.total_captured = sum(m.captured_units for m in portfolio.monk_metrics)
        portfolio.total_uncaptured = sum(m.uncaptured_units for m in portfolio.monk_metrics)

        if portfolio.total_eligible > 0:
            portfolio.portfolio_capture_rate = portfolio.total_captured / portfolio.total_eligible

        # Overlap: tickers acted on by >1 Monk
        portfolio.overlap_count = sum(
            1 for monks in all_captured_tickers.values() if len(monks) > 1
        )
        if portfolio.total_captured > 0:
            portfolio.overlap_rate = portfolio.overlap_count / portfolio.total_captured

        # Aggregate uncaptured reasons
        all_reasons: dict[str, int] = {}
        for m in portfolio.monk_metrics:
            for reason, count in m.uncaptured_reasons.items():
                all_reasons[reason] = all_reasons.get(reason, 0) + count
        portfolio.top_uncaptured_reasons = dict(
            sorted(all_reasons.items(), key=lambda x: -x[1])[:10]
        )

        # Generate suggestions
        portfolio.suggestions = _generate_suggestions(portfolio)

    return portfolio


def _compute_monk_capture(session: Session, config: StoredMonkConfig) -> MonkCaptureMetrics:
    """Compute capture metrics for a single Monk."""
    metrics = MonkCaptureMetrics(
        monk_name=config.name,
        family_id=config.family_id,
    )

    # Get config rules for eligibility determination
    config_data = config.config_data or {}
    entry = config_data.get("entry", {})
    thresholds = entry.get("thresholds", {})
    min_volume = thresholds.get("min_volume", 10)
    spread_rules = entry.get("spread_rules", {})
    max_spread_pct = spread_rules.get("max_spread_pct", 0.30)

    # Get all current markets for this family
    markets = session.execute(text("""
        SELECT DISTINCT ON (ticker) ticker, data
        FROM raw_market_snapshots
        WHERE series_ticker = :family
        ORDER BY ticker, ingested_at DESC
    """), {"family": config.family_id}).fetchall()

    # Get tickers this Monk has traded
    traded = set(session.execute(
        select(MonkTrade.ticker).where(MonkTrade.monk_name == config.name)
    ).scalars().all())

    # Get P&L
    pnl_result = session.execute(text("""
        SELECT COALESCE(SUM(pnl), 0) FROM monk_trades
        WHERE monk_name = :name AND status = 'closed'
    """), {"name": config.name}).scalar()
    metrics.realized_pnl = float(pnl_result or 0)

    reasons: dict[str, int] = {}

    for ticker, data in markets:
        status = data.get("status", "")
        if status not in ("active", "finalized"):
            continue

        volume = float(data.get("volume_fp", "0") or "0")
        last_price = float(data.get("last_price_dollars", "0") or "0")
        yes_bid = float(data.get("yes_bid_dollars", "0") or "0")
        yes_ask = float(data.get("yes_ask_dollars", "0") or "0")

        # Check eligibility
        eligible = True
        block_reason = None

        if volume < min_volume:
            eligible = False
            block_reason = "volume_too_low"
        elif last_price <= 0.05 or last_price >= 0.95:
            eligible = False
            block_reason = "price_extreme"
        elif yes_bid <= 0 and yes_ask <= 0:
            eligible = False
            block_reason = "no_bids"
        else:
            midpoint = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else last_price
            spread = yes_ask - yes_bid
            if midpoint > 0 and spread / midpoint > max_spread_pct:
                eligible = False
                block_reason = "spread_too_wide"

        if not eligible:
            if block_reason:
                reasons[block_reason] = reasons.get(block_reason, 0) + 1
            continue

        metrics.eligible_units += 1

        if ticker in traded:
            metrics.captured_units += 1
        else:
            metrics.uncaptured_units += 1
            reasons["not_traded"] = reasons.get("not_traded", 0) + 1

    if metrics.eligible_units > 0:
        metrics.capture_rate = metrics.captured_units / metrics.eligible_units

    if metrics.captured_units > 0:
        metrics.avg_pnl_per_capture = metrics.realized_pnl / metrics.captured_units

    metrics.uncaptured_reasons = reasons
    return metrics


def _generate_suggestions(portfolio: PortfolioCaptureMetrics) -> list[str]:
    """Generate actionable suggestions from capture analysis."""
    suggestions = []

    for m in portfolio.monk_metrics:
        if m.capture_rate < 0.30 and m.eligible_units > 10:
            suggestions.append(
                f"{m.monk_name}: low capture ({m.capture_rate:.0%}). "
                f"{m.uncaptured_units} eligible markets missed. "
                f"Consider loosening entry rules or increasing max_concurrent_positions."
            )

        not_traded = m.uncaptured_reasons.get("not_traded", 0)
        if not_traded > 20:
            suggestions.append(
                f"{m.monk_name}: {not_traded} eligible markets not traded. "
                f"Monk may need more frequent scan cycles or wider entry window."
            )

    # Cross-family suggestions
    families_covered = {m.family_id for m in portfolio.monk_metrics}
    if len(families_covered) == 1 and portfolio.total_eligible > 50:
        suggestions.append(
            "Only 1 family covered. Consider deploying Monks for additional "
            "high-scoring families to increase portfolio capture."
        )

    if portfolio.portfolio_capture_rate < 0.10 and portfolio.total_eligible > 0:
        suggestions.append(
            f"Portfolio capture is very low ({portfolio.portfolio_capture_rate:.0%}). "
            f"System is scanning but not acting on most opportunities."
        )

    return suggestions
