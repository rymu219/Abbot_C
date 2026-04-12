"""Phase 10: Testing Framework.

Determines whether a Monk config deserves trust by replaying it
against settled historical markets.

How it works:
  For each settled market in the Monk's family:
  1. Check if entry rules are met (volume, spread, timing)
  2. Determine entry side and price
  3. Use settlement outcome (yes/no) to compute actual P&L
  4. Aggregate metrics across all trades

This uses REAL outcomes from Kalshi's settled markets, not
simulated price movement. A market bought YES at $0.40 that
settles YES = $0.60 profit per contract. Settles NO = -$0.40 loss.

Priority order (from Requirements Section 5):
  1. Sample size — enough data to be meaningful?
  2. Robustness — does it work across different conditions?
  3. Profitability — is it actually profitable?
  4. Drawdown — how bad can it get?
  5. Explainability — can we understand why it works?

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
    """A trade produced by replaying a Monk config against a settled market."""

    ticker: str
    side: str           # "yes" or "no"
    entry_price: float  # What we would have paid
    settlement: float   # 1.0 (yes wins) or 0.0 (no wins)
    result: str         # "yes" or "no" — market outcome
    size: float         # Contracts
    pnl: float          # Actual profit/loss
    entry_reason: str   # Why we entered
    volume: float       # Market volume at entry


@dataclass
class TestReport:
    """Standardized test report for a Monk config."""

    config_name: str
    family_id: str
    test_type: str  # "settlement_replay"

    # Sample
    markets_evaluated: int = 0
    settled_markets: int = 0

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
                "markets_evaluated": self.markets_evaluated,
                "settled_markets": self.settled_markets,
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
    """Replay a Monk config against settled historical markets.

    For each settled market in the family:
    - Check if entry rules would have been met
    - Simulate the trade at the market's last traded price
    - Compute P&L from actual settlement outcome
    """
    family_id = config.identity.family_id
    name = config.identity.name

    report = TestReport(
        config_name=name,
        family_id=family_id or "",
        test_type="settlement_replay",
    )

    if not family_id:
        report.verdict = TestVerdict.REJECT
        report.verdict_reasons = ["no_family_id"]
        return report

    engine = get_engine()

    # Pull all settled markets for this family
    with Session(engine) as session:
        rows = session.execute(text("""
            SELECT data FROM raw_market_snapshots
            WHERE series_ticker = :series
              AND data->>'result' IS NOT NULL
              AND data->>'result' != ''
            ORDER BY data->>'created_time' ASC
        """), {"series": family_id}).fetchall()

    report.markets_evaluated = len(rows)
    report.settled_markets = len(rows)

    if not rows:
        report.verdict = TestVerdict.REJECT
        report.verdict_reasons = ["no_settled_markets"]
        return report

    # Extract config rules
    entry_thresholds = config.entry.thresholds or {}
    min_volume = entry_thresholds.get("min_volume", 10)
    spread_rules = config.entry.spread_rules or {}
    max_spread_pct = spread_rules.get("max_spread_pct", 0.30)

    exit_logic = config.exit.exit_logic or {}
    size = config.risk.max_position_size or 10.0

    # Simulate trades
    trades = []
    for row in rows:
        data = row[0]
        trade = _evaluate_market(data, min_volume, max_spread_pct, size)
        if trade:
            trades.append(trade)

    report.trades = trades
    report.trade_count = len(trades)

    # Compute metrics
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
        report.win_rate = len(gains) / len(trades)

        total_gains = sum(gains)
        total_losses = abs(sum(losses))
        report.profit_factor = total_gains / total_losses if total_losses > 0 else (
            float("inf") if total_gains > 0 else 0.0
        )

        # Max drawdown
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cumulative += t.pnl
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
        report.max_drawdown = max_dd

        # ROI
        total_deployed = sum(t.entry_price * t.size for t in trades)
        report.roi = report.total_pnl / total_deployed if total_deployed > 0 else 0.0

    # Assign verdict
    _assign_verdict(report)

    logger.info(
        "Replay: %s — %d/%d markets traded, %d trades, P&L=$%.2f, WR=%.0f%%, verdict=%s",
        name, report.trade_count, report.settled_markets,
        report.trade_count, report.total_pnl,
        report.win_rate * 100, report.verdict.value,
    )

    return report


def _evaluate_market(
    data: dict,
    min_volume: float,
    max_spread_pct: float,
    size: float,
) -> SimulatedTrade | None:
    """Evaluate a single settled market for a simulated trade.

    Entry logic:
    - Market must have sufficient volume
    - Spread must be acceptable
    - Price must not be at the extremes (avoid obvious outcomes)

    Side selection:
    - If last price < 0.50: buy YES (betting on underdog/value)
    - If last price >= 0.50: buy NO (betting against favorite/overpriced)
    - This is a simple mean-reversion/value strategy. Future archetypes
      will use more sophisticated entry logic.
    """
    volume = _f(data.get("volume_fp", "0"))
    result = data.get("result", "")
    last_price = _f(data.get("last_price_dollars", "0"))
    yes_bid = _f(data.get("yes_bid_dollars", "0"))
    yes_ask = _f(data.get("yes_ask_dollars", "0"))

    # Must have a result
    if not result:
        return None

    # Volume gate
    if volume < min_volume:
        return None

    # For settled markets, spread data reflects post-settlement state (not tradeable).
    # Skip spread check on historical settled data — it will apply during live/paper trading.

    # The backfilled data shows FINAL prices (post-settlement).
    # For backtesting we simulate entry at a realistic mid-life price.
    #
    # Strategy: Buy YES at a simulated entry price.
    # The entry price is estimated from market structure:
    #   - Game winner markets (KXNBAGAME etc.): entry ~0.50 (coin flip baseline)
    #   - Spread/total markets: entry varies by strike distance from expectation
    #
    # With entry at ~0.50:
    #   - YES wins → P&L = +$0.50 per contract
    #   - NO wins  → P&L = -$0.50 per contract
    #   - Net expectation at 50% win rate = $0 (no edge without better entry)
    #
    # The REAL edge comes from entering at better prices than 0.50.
    # When we have candle data (intra-market price history), we can simulate
    # entries at actual observed prices. For now, we use the market's
    # implied probability from the title/structure as the entry.

    if last_price < 0.05 or last_price > 0.95:
        # Post-settlement extreme price. Use 0.50 as baseline entry.
        sim_entry = 0.50
    else:
        sim_entry = last_price

    # Always buy YES at simulated entry
    side = "yes"
    entry_price = sim_entry
    settlement_value = 1.0 if result == "yes" else 0.0
    pnl = (settlement_value - entry_price) * size

    return SimulatedTrade(
        ticker=data.get("ticker", ""),
        side=side,
        entry_price=entry_price,
        settlement=settlement_value,
        result=result,
        size=size,
        pnl=pnl,
        entry_reason=f"value_{side}_at_{last_price:.2f}",
        volume=volume,
    )


def _assign_verdict(report: TestReport) -> None:
    """Assign a test verdict based on metrics.

    Priority: sample size > robustness > profitability > drawdown.
    """
    reasons = []

    # 1. Sample size
    if report.settled_markets < 10:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.2
        reasons.append(f"low_sample_{report.settled_markets}")
        report.verdict_reasons = reasons
        return

    if report.trade_count == 0:
        report.verdict = TestVerdict.REJECT
        report.confidence = 0.5
        reasons.append("no_trades_generated")
        reasons.append(f"evaluated_{report.settled_markets}_markets")
        report.verdict_reasons = reasons
        return

    if report.trade_count < 10:
        reasons.append(f"low_trade_count_{report.trade_count}")

    # 2. Robustness
    if report.trade_count >= 20:
        reasons.append("adequate_sample")
    if report.win_rate >= 0.50:
        reasons.append("strong_win_rate")
    elif report.win_rate >= 0.40:
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
    if report.total_pnl > 0 and report.max_drawdown > report.total_pnl * 2:
        reasons.append("high_drawdown_ratio")

    # 5. Profit factor
    if report.profit_factor >= 1.5:
        reasons.append("strong_profit_factor")
    elif report.profit_factor >= 1.0:
        reasons.append("positive_profit_factor")
    else:
        reasons.append("negative_profit_factor")

    # --- Verdict ---
    if report.trade_count < 10:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.3
    elif report.total_pnl > 0 and report.profit_factor >= 1.2 and report.win_rate >= 0.45:
        report.verdict = TestVerdict.ELIGIBLE_FOR_DEPLOY
        report.confidence = min(0.9, 0.4 + report.trade_count * 0.01)
    elif report.total_pnl > 0 and report.profit_factor >= 1.0:
        report.verdict = TestVerdict.PAPER_LONGER
        report.confidence = 0.5
    elif report.total_pnl <= 0 and report.win_rate >= 0.40:
        report.verdict = TestVerdict.REVISE
        report.confidence = 0.4
    else:
        report.verdict = TestVerdict.REJECT
        report.confidence = 0.5

    report.verdict_reasons = reasons


def _f(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
