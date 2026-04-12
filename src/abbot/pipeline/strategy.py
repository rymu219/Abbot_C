"""Strategy Mining Engine.

The intelligence core of Abbot. Discovers entry/exit/risk rules
from settled market data instead of using hardcoded templates.

For each candidate family:
1. Query all settled markets with outcomes
2. Split chronologically: 70% train, 30% test
3. Scan entry parameters: 17 price thresholds × 2 sides = 34 combos
4. Analyze timing and volume signals
5. Derive exit levels from P&L distributions
6. Validate on holdout test set
7. Compute statistical confidence

Output: StrategyBlueprint with data-derived parameters.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.pipeline.candidates import MonkCandidate

logger = logging.getLogger(__name__)


# --- Data classes ---


@dataclass
class PriceThresholdResult:
    """Result of analyzing a single entry price threshold."""

    threshold: float
    side: str  # "yes" or "no"
    trade_count: int = 0
    win_count: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl_per_trade: float = 0.0
    expected_value: float = 0.0

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "side": self.side,
            "trades": self.trade_count,
            "wins": self.win_count,
            "win_rate": round(self.win_rate, 3),
            "pnl": round(self.total_pnl, 2),
            "ev": round(self.expected_value, 4),
        }


@dataclass
class TimingBucket:
    """Settlement stats for a timing window."""

    bucket: str  # "early", "mid", "late", "expiry"
    pct_range: tuple[float, float]
    market_count: int = 0
    yes_rate: float = 0.0
    avg_volume: float = 0.0

    def to_dict(self) -> dict:
        return {
            "bucket": self.bucket,
            "range": list(self.pct_range),
            "markets": self.market_count,
            "yes_rate": round(self.yes_rate, 3),
            "avg_volume": round(self.avg_volume, 0),
        }


@dataclass
class StrategyBlueprint:
    """Data-derived strategy for a family. The foundry's output."""

    family_id: str
    family_title: str

    # Sample
    total_settled: int = 0
    usable_markets: int = 0
    train_count: int = 0
    test_count: int = 0

    # Optimal parameters (from training set)
    recommended_side: str = "yes"
    entry_price_min: float = 0.0
    entry_price_max: float = 1.0
    optimal_entry: float = 0.50

    # Timing
    preferred_timing: str = "any"
    timing_pct_min: float = 0.0
    timing_pct_max: float = 1.0

    # Volume
    min_volume_threshold: float = 10.0
    volume_helps: bool = False

    # Exit (derived from P&L distribution)
    take_profit_pct: float = 0.15
    stop_loss_pct: float = 0.10

    # Risk
    suggested_position_size: float = 10.0
    suggested_max_daily_loss: float = 25.0

    # Training performance
    train_win_rate: float = 0.0
    train_total_pnl: float = 0.0
    train_profit_factor: float = 0.0
    train_expected_value: float = 0.0
    train_trade_count: int = 0

    # Holdout performance
    test_win_rate: float = 0.0
    test_total_pnl: float = 0.0
    test_profit_factor: float = 0.0
    test_expected_value: float = 0.0
    test_trade_count: int = 0

    # Confidence
    sample_sufficient: bool = False
    train_test_consistent: bool = False
    statistical_significance: float = 1.0  # p-value
    time_consistency: float = 0.0  # 0-1, higher = more consistent
    data_quality_pct: float = 0.0  # % of markets with usable price data

    # Full scan results (for UI)
    price_scan: list[PriceThresholdResult] = field(default_factory=list)
    timing_buckets: list[TimingBucket] = field(default_factory=list)

    # Meta
    mined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mining_duration_ms: int = 0

    # Overall viability
    viable: bool = False
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "family_id": self.family_id,
            "family_title": self.family_title,
            "sample": {
                "total_settled": self.total_settled,
                "usable": self.usable_markets,
                "train": self.train_count,
                "test": self.test_count,
                "data_quality_pct": round(self.data_quality_pct, 1),
            },
            "strategy": {
                "side": self.recommended_side,
                "entry_price_min": self.entry_price_min,
                "entry_price_max": self.entry_price_max,
                "optimal_entry": self.optimal_entry,
                "timing": self.preferred_timing,
                "timing_range": [self.timing_pct_min, self.timing_pct_max],
                "min_volume": self.min_volume_threshold,
                "take_profit_pct": round(self.take_profit_pct, 3),
                "stop_loss_pct": round(self.stop_loss_pct, 3),
            },
            "train": {
                "trades": self.train_trade_count,
                "win_rate": round(self.train_win_rate, 3),
                "pnl": round(self.train_total_pnl, 2),
                "profit_factor": round(self.train_profit_factor, 2),
                "ev_per_trade": round(self.train_expected_value, 4),
            },
            "test": {
                "trades": self.test_trade_count,
                "win_rate": round(self.test_win_rate, 3),
                "pnl": round(self.test_total_pnl, 2),
                "profit_factor": round(self.test_profit_factor, 2),
                "ev_per_trade": round(self.test_expected_value, 4),
            },
            "confidence": {
                "sample_sufficient": self.sample_sufficient,
                "train_test_consistent": self.train_test_consistent,
                "p_value": round(self.statistical_significance, 4),
                "time_consistency": round(self.time_consistency, 3),
            },
            "viable": self.viable,
            "rejection_reason": self.rejection_reason,
            "price_scan": [p.to_dict() for p in self.price_scan],
            "timing_buckets": [t.to_dict() for t in self.timing_buckets],
        }


# --- Mining engine ---


def mine_strategy(family_id: str, family_title: str = "") -> StrategyBlueprint:
    """Mine a data-derived strategy for a family from settled markets.

    This is the core intelligence function. It discovers entry/exit rules
    from historical outcomes, validates on holdout data, and returns a
    StrategyBlueprint that config_gen uses to create MonkConfigs.
    """
    start_ms = time.monotonic()
    bp = StrategyBlueprint(family_id=family_id, family_title=family_title)

    engine = get_engine()

    # 1. Query settled markets
    with Session(engine) as session:
        rows = session.execute(text("""
            SELECT
                data->>'ticker' as ticker,
                data->>'result' as result,
                COALESCE((data->>'volume_fp')::float, 0) as volume,
                COALESCE((data->>'last_price_dollars')::float, 0) as last_price,
                COALESCE((data->>'yes_bid_dollars')::float, 0) as yes_bid,
                COALESCE((data->>'yes_ask_dollars')::float, 0) as yes_ask,
                data->>'created_time' as created_time,
                data->>'close_time' as close_time
            FROM raw_market_snapshots
            WHERE series_ticker = :series
              AND data->>'result' IS NOT NULL
              AND data->>'result' != ''
            ORDER BY (data->>'created_time')::timestamptz ASC
        """), {"series": family_id}).fetchall()

    bp.total_settled = len(rows)

    if bp.total_settled < 30:
        bp.rejection_reason = f"insufficient_data_{bp.total_settled}"
        bp.mining_duration_ms = int((time.monotonic() - start_ms) * 1000)
        return bp

    # 2. Parse into usable records
    markets = []
    for ticker, result, volume, last_price, yes_bid, yes_ask, created, closed in rows:
        # Determine usable entry price
        # Prefer yes_bid (conservative), fall back to last_price
        entry_proxy = 0.0
        if 0.05 < yes_bid < 0.95:
            entry_proxy = yes_bid
        elif 0.05 < last_price < 0.95:
            entry_proxy = last_price

        markets.append({
            "ticker": ticker,
            "result": result,
            "volume": volume,
            "entry_proxy": entry_proxy,
            "has_price": entry_proxy > 0,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
        })

    usable = [m for m in markets if m["has_price"]]
    bp.usable_markets = len(usable)
    bp.data_quality_pct = (len(usable) / len(markets) * 100) if markets else 0

    # If most markets have post-settlement prices, fall back to structural analysis
    if len(usable) < 30:
        return _mine_structural(bp, markets, start_ms)

    # 3. Chronological train/test split
    split_idx = int(len(usable) * 0.70)
    train = usable[:split_idx]
    test = usable[split_idx:]
    bp.train_count = len(train)
    bp.test_count = len(test)

    # 4. Price threshold scan on training set
    bp.price_scan = _scan_price_thresholds(train)

    # 5. Find optimal parameters
    best = _select_best_threshold(bp.price_scan)

    if best is None:
        bp.rejection_reason = "no_profitable_threshold"
        bp.mining_duration_ms = int((time.monotonic() - start_ms) * 1000)
        return bp

    bp.recommended_side = best.side
    bp.optimal_entry = best.threshold
    bp.train_win_rate = best.win_rate
    bp.train_total_pnl = best.total_pnl
    bp.train_expected_value = best.expected_value
    bp.train_trade_count = best.trade_count

    # Compute profit factor for training
    train_gains = sum(
        _trade_pnl(m, best.side, best.threshold)
        for m in train
        if _would_enter(m, best.side, best.threshold)
        and _trade_pnl(m, best.side, best.threshold) > 0
    )
    train_losses = abs(sum(
        _trade_pnl(m, best.side, best.threshold)
        for m in train
        if _would_enter(m, best.side, best.threshold)
        and _trade_pnl(m, best.side, best.threshold) < 0
    ))
    bp.train_profit_factor = train_gains / train_losses if train_losses > 0 else (
        999.0 if train_gains > 0 else 0.0
    )

    # Entry price range (adjacent profitable thresholds)
    bp.entry_price_min, bp.entry_price_max = _find_price_range(bp.price_scan, best)

    # 6. Timing analysis
    bp.timing_buckets = _analyze_timing(train)
    bp.preferred_timing, bp.timing_pct_min, bp.timing_pct_max = _select_timing(bp.timing_buckets)

    # 7. Volume analysis
    bp.min_volume_threshold, bp.volume_helps = _analyze_volume(train)

    # 8. Exit levels
    bp.take_profit_pct, bp.stop_loss_pct = _derive_exit_levels(best)

    # 9. Risk sizing
    bp.suggested_position_size = min(50.0, max(5.0, 25.0 / max(bp.stop_loss_pct, 0.05)))
    bp.suggested_max_daily_loss = 25.0

    # 10. Validate on test set
    test_result = _evaluate_on_set(test, best.side, best.threshold)
    bp.test_win_rate = test_result.win_rate
    bp.test_total_pnl = test_result.total_pnl
    bp.test_expected_value = test_result.expected_value
    bp.test_trade_count = test_result.trade_count

    test_gains = sum(
        _trade_pnl(m, best.side, best.threshold)
        for m in test
        if _would_enter(m, best.side, best.threshold)
        and _trade_pnl(m, best.side, best.threshold) > 0
    )
    test_losses = abs(sum(
        _trade_pnl(m, best.side, best.threshold)
        for m in test
        if _would_enter(m, best.side, best.threshold)
        and _trade_pnl(m, best.side, best.threshold) < 0
    ))
    bp.test_profit_factor = test_gains / test_losses if test_losses > 0 else (
        999.0 if test_gains > 0 else 0.0
    )

    # 11. Confidence metrics
    bp.sample_sufficient = bp.train_trade_count >= 30
    bp.train_test_consistent = abs(bp.train_win_rate - bp.test_win_rate) <= 0.15
    bp.statistical_significance = _binomial_pvalue(bp.train_trade_count, bp.train_win_rate)
    bp.time_consistency = _time_consistency(train, best.side, best.threshold)

    # 12. Overall viability
    bp.viable = (
        bp.sample_sufficient
        and bp.train_expected_value > 0
        and bp.test_expected_value > 0
        and bp.statistical_significance < 0.10
        and bp.train_test_consistent
    )

    if not bp.viable:
        reasons = []
        if not bp.sample_sufficient:
            reasons.append("insufficient_trades")
        if bp.train_expected_value <= 0:
            reasons.append("negative_train_ev")
        if bp.test_expected_value <= 0:
            reasons.append("negative_test_ev")
        if bp.statistical_significance >= 0.10:
            reasons.append(f"not_significant_p{bp.statistical_significance:.2f}")
        if not bp.train_test_consistent:
            reasons.append("train_test_gap")
        bp.rejection_reason = ", ".join(reasons)

    bp.mining_duration_ms = int((time.monotonic() - start_ms) * 1000)

    logger.info(
        "Mined %s: %s side=%s entry=%.2f train_wr=%.1f%% test_wr=%.1f%% p=%.3f viable=%s (%dms)",
        family_id, "VIABLE" if bp.viable else "NOT_VIABLE",
        bp.recommended_side, bp.optimal_entry,
        bp.train_win_rate * 100, bp.test_win_rate * 100,
        bp.statistical_significance, bp.viable, bp.mining_duration_ms,
    )

    return bp


def mine_strategies(
    candidates: list[MonkCandidate],
) -> list[tuple[MonkCandidate, StrategyBlueprint]]:
    """Mine strategies for all eligible candidates."""
    eligible = [
        c for c in candidates
        if c.decision.value in ("build_candidate", "prototype_candidate")
    ]

    results = []
    for candidate in eligible:
        bp = mine_strategy(candidate.series_ticker, candidate.title)
        results.append((candidate, bp))

    viable = sum(1 for _, bp in results if bp.viable)
    logger.info(
        "Strategy mining: %d candidates → %d viable strategies",
        len(eligible), viable,
    )

    return results


# --- Structural fallback ---


def _mine_structural(
    bp: StrategyBlueprint, markets: list[dict], start_ms: float
) -> StrategyBlueprint:
    """Fallback: mine strategy from settlement rates alone (no price data).

    When most markets have post-settlement prices, we can still analyze
    whether YES or NO settles more often, and compute the break-even entry.
    """
    yes_count = sum(1 for m in markets if m["result"] == "yes")
    no_count = sum(1 for m in markets if m["result"] == "no")
    total = yes_count + no_count

    if total < 30:
        bp.rejection_reason = "insufficient_data"
        bp.mining_duration_ms = int((time.monotonic() - start_ms) * 1000)
        return bp

    yes_rate = yes_count / total

    # If YES settles >52%, buying YES below the yes_rate is +EV
    if yes_rate > 0.52:
        bp.recommended_side = "yes"
        bp.optimal_entry = round(yes_rate - 0.02, 2)  # Enter below fair value
        bp.entry_price_min = round(yes_rate - 0.08, 2)
        bp.entry_price_max = round(yes_rate - 0.02, 2)
    elif yes_rate < 0.48:
        bp.recommended_side = "no"
        bp.optimal_entry = round(1.0 - yes_rate - 0.02, 2)
        bp.entry_price_min = round(1.0 - yes_rate - 0.08, 2)
        bp.entry_price_max = round(1.0 - yes_rate - 0.02, 2)
    else:
        bp.rejection_reason = f"no_settlement_bias_yes_rate_{yes_rate:.2f}"
        bp.mining_duration_ms = int((time.monotonic() - start_ms) * 1000)
        return bp

    # Compute training metrics from structural analysis
    bp.train_win_rate = max(yes_rate, 1 - yes_rate)
    bp.train_expected_value = bp.train_win_rate - 0.50
    bp.train_trade_count = total
    bp.sample_sufficient = True
    bp.statistical_significance = _binomial_pvalue(total, bp.train_win_rate)
    bp.data_quality_pct = 0.0  # Structural fallback, no price data used

    bp.take_profit_pct = 1.0 - bp.optimal_entry
    bp.stop_loss_pct = bp.optimal_entry

    bp.viable = bp.statistical_significance < 0.10 and bp.train_expected_value > 0.02

    if not bp.viable:
        bp.rejection_reason = "structural_edge_too_small"

    bp.mining_duration_ms = int((time.monotonic() - start_ms) * 1000)
    return bp


# --- Core analysis functions ---


def _scan_price_thresholds(markets: list[dict]) -> list[PriceThresholdResult]:
    """Scan all price threshold × side combinations on the dataset."""
    results = []

    for threshold in [round(t * 0.05, 2) for t in range(2, 19)]:  # 0.10 to 0.90
        for side in ("yes", "no"):
            r = _evaluate_on_set(markets, side, threshold)
            results.append(r)

    return results


def _evaluate_on_set(
    markets: list[dict], side: str, threshold: float
) -> PriceThresholdResult:
    """Evaluate a side+threshold on a set of markets."""
    r = PriceThresholdResult(threshold=threshold, side=side)

    for m in markets:
        if not _would_enter(m, side, threshold):
            continue

        pnl = _trade_pnl(m, side, threshold)
        r.trade_count += 1
        r.total_pnl += pnl
        if pnl > 0:
            r.win_count += 1

    if r.trade_count > 0:
        r.win_rate = r.win_count / r.trade_count
        r.avg_pnl_per_trade = r.total_pnl / r.trade_count
        avg_gain = r.total_pnl / r.win_count if r.win_count > 0 else 0
        avg_loss = abs(r.total_pnl - avg_gain * r.win_count) / max(1, r.trade_count - r.win_count)
        r.expected_value = r.win_rate * abs(1.0 - threshold) - (1 - r.win_rate) * threshold if side == "yes" else (
            r.win_rate * abs(threshold) - (1 - r.win_rate) * (1.0 - threshold)
        )

    return r


def _would_enter(m: dict, side: str, threshold: float) -> bool:
    """Would we enter this market given side and threshold?"""
    price = m["entry_proxy"]
    if price <= 0:
        return False
    if side == "yes":
        return price <= threshold
    else:  # no
        return price >= (1.0 - threshold)


def _trade_pnl(m: dict, side: str, threshold: float) -> float:
    """Compute P&L for entering at threshold on this market."""
    entry = threshold  # We enter at our threshold price
    result = m["result"]

    if side == "yes":
        settlement = 1.0 if result == "yes" else 0.0
        return settlement - entry
    else:
        settlement = 1.0 if result == "no" else 0.0
        entry_no = 1.0 - threshold
        return settlement - entry_no


def _select_best_threshold(
    scan: list[PriceThresholdResult],
) -> PriceThresholdResult | None:
    """Select the best threshold from the price scan."""
    eligible = [
        r for r in scan
        if r.trade_count >= 10 and r.expected_value > 0
    ]

    if not eligible:
        return None

    # Sort by expected value, then trade count
    eligible.sort(key=lambda r: (r.expected_value, r.trade_count), reverse=True)
    return eligible[0]


def _find_price_range(
    scan: list[PriceThresholdResult], best: PriceThresholdResult
) -> tuple[float, float]:
    """Find the range of profitable thresholds around the optimal."""
    same_side = [r for r in scan if r.side == best.side and r.expected_value > 0]
    if not same_side:
        return best.threshold, best.threshold

    prices = sorted(r.threshold for r in same_side)
    return min(prices), max(prices)


def _analyze_timing(markets: list[dict]) -> list[TimingBucket]:
    """Analyze settlement patterns by market timing bucket."""
    buckets_def = [
        ("early", (0.0, 0.25)),
        ("mid", (0.25, 0.50)),
        ("late", (0.50, 0.75)),
        ("expiry", (0.75, 1.0)),
    ]

    # We don't have life_elapsed in the data, so analyze by volume as proxy
    # Higher volume often correlates with later market life
    results = []
    for name, (lo, hi) in buckets_def:
        bucket = TimingBucket(bucket=name, pct_range=(lo, hi))

        # Use volume quartiles as timing proxy
        vols = sorted(m["volume"] for m in markets if m["volume"] > 0)
        if not vols:
            results.append(bucket)
            continue

        vol_lo = vols[int(len(vols) * lo)] if int(len(vols) * lo) < len(vols) else 0
        vol_hi = vols[min(int(len(vols) * hi), len(vols) - 1)]

        bucket_markets = [m for m in markets if vol_lo <= m["volume"] <= vol_hi]
        bucket.market_count = len(bucket_markets)
        if bucket_markets:
            yes_count = sum(1 for m in bucket_markets if m["result"] == "yes")
            bucket.yes_rate = yes_count / len(bucket_markets)
            bucket.avg_volume = sum(m["volume"] for m in bucket_markets) / len(bucket_markets)

        results.append(bucket)

    return results


def _select_timing(buckets: list[TimingBucket]) -> tuple[str, float, float]:
    """Select the best timing window."""
    # For now, allow all timing windows
    return "any", 0.0, 1.0


def _analyze_volume(markets: list[dict]) -> tuple[float, bool]:
    """Analyze if volume level affects outcomes."""
    with_vol = [m for m in markets if m["volume"] > 0]
    if len(with_vol) < 20:
        return 10.0, False

    vols = sorted(m["volume"] for m in with_vol)
    median_vol = vols[len(vols) // 2]

    high_vol = [m for m in with_vol if m["volume"] >= median_vol]
    low_vol = [m for m in with_vol if m["volume"] < median_vol]

    high_yes = sum(1 for m in high_vol if m["result"] == "yes") / max(1, len(high_vol))
    low_yes = sum(1 for m in low_vol if m["result"] == "yes") / max(1, len(low_vol))

    volume_helps = abs(high_yes - low_yes) > 0.05
    threshold = vols[len(vols) // 3]  # Lower tercile boundary

    return threshold, volume_helps


def _derive_exit_levels(best: PriceThresholdResult) -> tuple[float, float]:
    """Derive take-profit and stop-loss from the optimal entry."""
    if best.side == "yes":
        # Max profit = 1.0 - entry, max loss = entry
        take_profit = (1.0 - best.threshold) * 0.75  # Take 75% of max profit
        stop_loss = best.threshold * 0.80  # Cut at 80% of max loss
    else:
        take_profit = best.threshold * 0.75
        stop_loss = (1.0 - best.threshold) * 0.80

    return round(take_profit, 3), round(stop_loss, 3)


def _binomial_pvalue(n: int, win_rate: float) -> float:
    """Compute one-sided p-value using normal approximation to binomial.

    Tests: is win_rate significantly > 0.50?
    """
    if n <= 0 or win_rate <= 0.5:
        return 1.0

    # Normal approximation: Z = (p_hat - 0.5) / sqrt(0.25/n)
    z = (win_rate - 0.5) / math.sqrt(0.25 / n)

    # One-sided p-value from Z using approximation
    # P(Z > z) ≈ erfc(z/sqrt(2))/2
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return min(1.0, max(0.0, p))


def _time_consistency(
    markets: list[dict], side: str, threshold: float
) -> float:
    """Check win rate consistency across time quartiles. Returns 0-1."""
    tradeable = [m for m in markets if _would_enter(m, side, threshold)]
    if len(tradeable) < 20:
        return 0.0

    q_size = len(tradeable) // 4
    if q_size < 3:
        return 0.0

    quartile_wrs = []
    for i in range(4):
        start = i * q_size
        end = start + q_size if i < 3 else len(tradeable)
        q = tradeable[start:end]
        wins = sum(1 for m in q if _trade_pnl(m, side, threshold) > 0)
        quartile_wrs.append(wins / len(q))

    if not quartile_wrs:
        return 0.0

    mean_wr = sum(quartile_wrs) / len(quartile_wrs)
    variance = sum((wr - mean_wr) ** 2 for wr in quartile_wrs) / len(quartile_wrs)
    std_dev = variance ** 0.5

    # Consistency = 1 - normalized std dev (lower std = more consistent)
    return max(0.0, min(1.0, 1.0 - std_dev * 4))
