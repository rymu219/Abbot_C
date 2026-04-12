"""Phase 10: Testing Framework.

Determines whether a Monk config deserves trust by replaying it
against historical market snapshots.

Test stages:
  1. Replay — run config rules against stored snapshots
  2. Paper — forward-test without real capital (future)
  3. Probation — small real capital with tight limits (future)

Priority order (from Requirements Section 5):
  1. Sample size — enough data to be meaningful?
  2. Robustness — does it work across different conditions?
  3. Profitability — is it actually profitable?
  4. Drawdown — how bad can it get?
  5. Explainability — can we understand why it works?

Evaluation metrics:
  - Trade count, win rate, profit factor
  - Total P&L, ROI, max drawdown
  - Average gain, average loss
  - Exposure (time in market)

Verdicts: REJECT, REVISE, PAPER_LONGER, ELIGIBLE_FOR_DEPLOY
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.types import MonkConfig, TestVerdict

logger = logging.getLogger(__name__)


@dataclass
class SimulatedTrade:
    """A trade produced by replaying a Monk config against historical data."""

    ticker: str
    entry_price: float
    exit_price: float
    side: str  # "yes" or "no"
    size: float
    pnl: float
    entry_reason: str
    exit_reason: str


@dataclass
class TestReport:
    """Standardized test report for a Monk config."""

    config_name: str
    family_id: str
    test_type: str  # "replay", "paper", "probation"

    # Sample
    snapshots_analyzed: int = 0
    markets_analyzed: int = 0
    data_days: float = 0.0

    # Trades
    trades: list[SimulatedTrade] = field(default_factory=list)
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0

    # P&L
    total_pnl: float = 0.0
    avg_gain: float = 0.0
    avg_loss: float = 0.0
    max_gain: float = 0.0
    max_loss: float = 0.0
    max_drawdown: float = 0.0

    # Ratios
    win_rate: float = 0.0
    profit_factor: float = 0.0
    roi: float = 0.0

    # Verdict
    verdict: TestVerdict = TestVerdict.REJECT
    verdict_reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0

    tested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "config_name": self.config_name,
            "family_id": self.family_id,
            "test_type": self.test_type,
            "sample": {
                "snapshots": self.snapshots_analyzed,
                "markets": self.markets_analyzed,
                "data_days": round(self.data_days, 1),
            },
            "performance": {
                "trade_count": self.trade_count,
                "win_rate": round(self.win_rate, 3),
                "total_pnl": round(self.total_pnl, 2),
                "avg_gain": round(self.avg_gain, 2),
                "avg_loss": round(self.avg_loss, 2),
                "max_drawdown": round(self.max_drawdown, 2),
                "profit_factor": round(self.profit_factor, 3),
                "roi": round(self.roi, 3),
            },
            "verdict": self.verdict.value,
            "verdict_reasons": self.verdict_reasons,
            "confidence": round(self.confidence, 2),
        }


def run_replay_test(config: MonkConfig) -> TestReport:
    """Replay a Monk config against historical snapshots.

    Simulates what would have happened if the Monk had been
    running with this config over the stored data.
    """
    family_id = config.identity.family_id
    name = config.identity.name

    report = TestReport(
        config_name=name,
        family_id=family_id or "",
        test_type="replay",
    )

    if not family_id:
        report.verdict = TestVerdict.REJECT
        report.verdict_reasons = ["no_family_id"]
        return report

    engine = get_engine()

    with Session(engine) as session:
        # Get all snapshots for this family's markets, ordered by time
        rows = session.execute(text("""
            SELECT
                m.ticker,
                m.data,
                m.ingested_at,
                e.series_ticker
            FROM raw_market_snapshots m
            LEFT JOIN raw_event_snapshots e ON m.event_ticker = e.event_ticker
            WHERE e.series_ticker = :series
            ORDER BY m.ticker, m.ingested_at ASC
        """), {"series": family_id}).fetchall()

        report.snapshots_analyzed = len(rows)

        # Group by ticker
        by_ticker: dict[str, list[tuple]] = {}
        for ticker, data, ingested_at, _ in rows:
            by_ticker.setdefault(ticker, []).append((data, ingested_at))

        report.markets_analyzed = len(by_ticker)

        if not rows:
            report.verdict = TestVerdict.REJECT
            report.verdict_reasons = ["no_data_for_family"]
            return report

        # Compute data span
        timestamps = [r[2] for r in rows]
        if len(timestamps) >= 2:
            span = (max(timestamps) - min(timestamps)).total_seconds()
            report.data_days = span / 86400
        else:
            report.data_days = 0.0

    # --- Simulate trades ---
    entry_rules = config.entry
    exit_rules = config.exit

    trades = []
    for ticker, snapshots in by_ticker.items():
        ticker_trades = _simulate_ticker(ticker, snapshots, config)
        trades.extend(ticker_trades)

    report.trades = trades
    report.trade_count = len(trades)

    # --- Compute metrics ---
    if trades:
        gains = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl < 0]

        report.win_count = len(gains)
        report.loss_count = len(losses)
        report.total_pnl = sum(t.pnl for t in trades)
        report.avg_gain = sum(gains) / len(gains) if gains else 0.0
        report.avg_loss = sum(losses) / len(losses) if losses else 0.0
        report.max_gain = max(gains) if gains else 0.0
        report.max_loss = min(losses) if losses else 0.0
        report.win_rate = len(gains) / len(trades) if trades else 0.0

        total_gains = sum(gains)
        total_losses = abs(sum(losses))
        report.profit_factor = total_gains / total_losses if total_losses > 0 else (
            float("inf") if total_gains > 0 else 0.0
        )

        # Max drawdown (peak to trough in cumulative P&L)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cumulative += t.pnl
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
        report.max_drawdown = max_dd

        # ROI (total P&L / total capital deployed)
        total_deployed = sum(t.size for t in trades)
        report.roi = report.total_pnl / total_deployed if total_deployed > 0 else 0.0

    # --- Assign verdict ---
    _assign_verdict(report)

    logger.info(
        "Replay test: %s — %d trades, P&L=%.2f, win_rate=%.1f%%, verdict=%s",
        name, report.trade_count, report.total_pnl,
        report.win_rate * 100, report.verdict.value,
    )

    return report


def _simulate_ticker(
    ticker: str,
    snapshots: list[tuple],
    config: MonkConfig,
) -> list[SimulatedTrade]:
    """Simulate trades for a single market ticker across its snapshots.

    Simple simulation logic:
    - Entry: when market meets the config's entry thresholds
    - Exit: when market hits exit conditions or reaches expiry
    - Size: fixed at config's max_position_size or $10 default
    """
    if len(snapshots) < 1:
        return []

    trades = []
    position = None  # None = no position, else (entry_price, side, size)

    entry_thresholds = config.entry.thresholds or {}
    min_volume = entry_thresholds.get("min_volume", 10)
    max_life_pct = entry_thresholds.get("max_life_elapsed_pct", 0.85)

    size = config.risk.max_position_size or 10.0

    for data, ingested_at in snapshots:
        price = _f(data.get("last_price_dollars", "0"))
        volume = _f(data.get("volume_fp", "0"))
        yes_bid = _f(data.get("yes_bid_dollars", "0"))
        yes_ask = _f(data.get("yes_ask_dollars", "0"))
        spread = yes_ask - yes_bid if yes_ask > yes_bid else 0.0
        status = data.get("status", "")

        # Skip if market is not active
        if status != "active":
            if position:
                # Force exit
                exit_price = price if price > 0 else position[0]
                pnl = _calc_pnl(position[0], exit_price, position[1], position[2])
                trades.append(SimulatedTrade(
                    ticker=ticker, entry_price=position[0], exit_price=exit_price,
                    side=position[1], size=position[2], pnl=pnl,
                    entry_reason="threshold_met", exit_reason="market_closed",
                ))
                position = None
            continue

        if position is None:
            # --- Entry check ---
            if volume >= min_volume and yes_bid > 0 and price > 0:
                # Check spread
                spread_rules = config.entry.spread_rules or {}
                max_spread = spread_rules.get("max_spread_pct", 0.30)
                midpoint = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else 1.0
                spread_pct = spread / midpoint if midpoint > 0 else 1.0

                if spread_pct <= max_spread:
                    # Enter: buy yes at current ask
                    side = "yes"
                    entry_price = yes_ask if yes_ask > 0 else price
                    position = (entry_price, side, size)
        else:
            # --- Exit check ---
            entry_price_pos, side, pos_size = position
            current_price = yes_bid if side == "yes" else (1.0 - yes_ask)

            if current_price > 0:
                unrealized_pnl_pct = (current_price - entry_price_pos) / entry_price_pos if entry_price_pos > 0 else 0

                exit_logic = config.exit.exit_logic or {}
                take_profit = exit_logic.get("exit_on_profit_pct", 0.15)
                stop_loss = exit_logic.get("exit_on_loss_pct", -0.10)

                exit_reason = None
                if unrealized_pnl_pct >= take_profit:
                    exit_reason = "take_profit"
                elif unrealized_pnl_pct <= stop_loss:
                    exit_reason = "stop_loss"

                if exit_reason:
                    pnl = _calc_pnl(entry_price_pos, current_price, side, pos_size)
                    trades.append(SimulatedTrade(
                        ticker=ticker, entry_price=entry_price_pos,
                        exit_price=current_price, side=side, size=pos_size,
                        pnl=pnl, entry_reason="threshold_met", exit_reason=exit_reason,
                    ))
                    position = None

    # Close any remaining position at last known price
    if position:
        last_data = snapshots[-1][0]
        last_price = _f(last_data.get("yes_bid_dollars", "0"))
        if last_price <= 0:
            last_price = _f(last_data.get("last_price_dollars", "0"))
        pnl = _calc_pnl(position[0], last_price, position[1], position[2])
        trades.append(SimulatedTrade(
            ticker=ticker, entry_price=position[0], exit_price=last_price,
            side=position[1], size=position[2], pnl=pnl,
            entry_reason="threshold_met", exit_reason="end_of_data",
        ))

    return trades


def _calc_pnl(entry: float, exit_price: float, side: str, size: float) -> float:
    """Calculate P&L for a trade."""
    if side == "yes":
        return (exit_price - entry) * size
    else:
        return (entry - exit_price) * size


def _assign_verdict(report: TestReport) -> None:
    """Assign a test verdict based on the report metrics.

    Priority: sample size > robustness > profitability > drawdown.
    """
    reasons = []

    # 1. Sample size gate
    if report.snapshots_analyzed < 5:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.2
        reasons.append("insufficient_snapshots")
        report.verdict_reasons = reasons
        return

    if report.trade_count == 0:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.3
        reasons.append("no_trades_generated")
        report.verdict_reasons = reasons
        return

    if report.trade_count < 5:
        reasons.append("low_trade_count")

    # 2. Robustness (win rate should be reasonable, not 100% or 0%)
    if report.trade_count >= 5:
        if report.win_rate >= 0.40:
            reasons.append("acceptable_win_rate")
        else:
            reasons.append("low_win_rate")

    # 3. Profitability
    if report.total_pnl > 0:
        reasons.append("profitable")
    elif report.total_pnl == 0:
        reasons.append("breakeven")
    else:
        reasons.append("unprofitable")

    # 4. Drawdown
    if report.max_drawdown > report.total_pnl * 2 and report.total_pnl > 0:
        reasons.append("high_drawdown_ratio")

    # 5. Profit factor
    if report.profit_factor >= 1.5:
        reasons.append("strong_profit_factor")
    elif report.profit_factor >= 1.0:
        reasons.append("positive_profit_factor")

    # --- Verdict ---
    if report.trade_count < 5:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.3
    elif report.total_pnl <= 0:
        if report.win_rate >= 0.35:
            report.verdict = TestVerdict.REVISE
            report.confidence = 0.4
        else:
            report.verdict = TestVerdict.REJECT
            report.confidence = 0.5
    elif report.profit_factor >= 1.2 and report.win_rate >= 0.40:
        report.verdict = TestVerdict.ELIGIBLE_FOR_DEPLOY
        report.confidence = min(0.9, 0.5 + report.trade_count * 0.02)
    elif report.total_pnl > 0:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.5
    else:
        report.verdict = TestVerdict.REVISE
        report.confidence = 0.4

    report.verdict_reasons = reasons


def _f(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
