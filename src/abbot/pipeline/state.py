"""Phase 7: State Classification Engine.

Assigns a MarketState to each market based on its features.

States represent the opportunity lifecycle:
  IGNORE     → No meaningful activity
  EARLY      → Initial signs of life (some volume, bids appearing)
  FORMING    → Building momentum (volume growing, spread tightening)
  ACTIONABLE → Clear opportunity (strong volume, tight spread, good timing)
  EXHAUSTED  → Activity declining or market near expiry

Classification uses the feature vector from Phase 6.
Thresholds are configurable via configs/scoring/v1.toml.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from abbot.pipeline.features import MarketFeatures
from abbot.types import MarketState

logger = logging.getLogger(__name__)


@dataclass
class MarketStateResult:
    """State classification for a single market."""

    ticker: str
    event_ticker: str
    series_ticker: str | None
    state: MarketState
    confidence: float           # 0.0 to 1.0
    reason_codes: list[str] = field(default_factory=list)
    score: float = 0.0          # Raw state score before thresholding
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def classify_state(features: MarketFeatures) -> MarketStateResult:
    """Classify a market's state from its features.

    Scoring logic:
    - Activity signal: does the market have volume, bids, OI?
    - Momentum signal: is volume/price changing? In which direction?
    - Spread signal: how tradeable is this market?
    - Timing signal: is there enough time left to act?
    """
    reasons = []
    score = 0.0

    # --- Not active at all → IGNORE ---
    if not features.is_active:
        return MarketStateResult(
            ticker=features.ticker,
            event_ticker=features.event_ticker,
            series_ticker=features.series_ticker,
            state=MarketState.IGNORE,
            confidence=0.9,
            reason_codes=["market_not_active"],
            score=0.0,
        )

    # --- Activity signal (0 to 0.30) ---
    if features.has_volume:
        score += 0.15
        reasons.append("has_volume")
    if features.has_bids:
        score += 0.10
        reasons.append("has_bids")
    if features.open_interest > 0:
        score += 0.05
        reasons.append("has_oi")

    # --- Volume magnitude (0 to 0.20) ---
    if features.volume >= 1000:
        score += 0.20
        reasons.append("strong_volume")
    elif features.volume >= 100:
        score += 0.12
        reasons.append("moderate_volume")
    elif features.volume >= 10:
        score += 0.05
        reasons.append("light_volume")

    # --- Volume momentum (0 to 0.15) — needs multiple snapshots ---
    if features.snapshot_count > 1:
        if features.volume_change > 100:
            score += 0.15
            reasons.append("volume_accelerating")
        elif features.volume_change > 0:
            score += 0.08
            reasons.append("volume_growing")
        elif features.volume_change < -50:
            score -= 0.10
            reasons.append("volume_declining")

    # --- Spread quality (0 to 0.15) ---
    if features.spread > 0:
        if features.spread_pct <= 0.05:
            score += 0.15
            reasons.append("tight_spread")
        elif features.spread_pct <= 0.15:
            score += 0.08
            reasons.append("moderate_spread")
        elif features.spread_pct <= 0.30:
            score += 0.03
            reasons.append("wide_spread")
        else:
            reasons.append("very_wide_spread")

    # --- Spread tightening (0 to 0.10) — needs multiple snapshots ---
    if features.snapshot_count > 1 and features.spread_change < -0.01:
        score += 0.10
        reasons.append("spread_tightening")

    # --- Timing (0 to 0.10, or penalty) ---
    if features.hours_to_expiry > 24:
        score += 0.05
        reasons.append("good_time_remaining")
    elif features.hours_to_expiry > 2:
        score += 0.10
        reasons.append("actionable_window")
    elif features.hours_to_expiry > 0:
        score += 0.02
        reasons.append("expiring_soon")
    elif features.hours_to_expiry <= 0:
        score -= 0.20
        reasons.append("expired_or_closing")

    # --- Price movement (0 to 0.10) — needs multiple snapshots ---
    if features.snapshot_count > 1:
        if abs(features.price_change) > 0.05:
            score += 0.10
            reasons.append("significant_price_move")
        elif abs(features.price_change) > 0.01:
            score += 0.05
            reasons.append("price_moving")

    # Clamp
    score = max(0.0, min(1.0, score))

    # --- Classify into state ---
    if score >= 0.60:
        state = MarketState.ACTIONABLE
        confidence = min(1.0, 0.7 + (score - 0.60))
    elif score >= 0.40:
        state = MarketState.FORMING
        confidence = 0.5 + (score - 0.40) * 2
    elif score >= 0.20:
        state = MarketState.EARLY
        confidence = 0.4 + (score - 0.20)
    elif score > 0.05:
        state = MarketState.IGNORE
        confidence = 0.6
        reasons.append("minimal_activity")
    else:
        state = MarketState.IGNORE
        confidence = 0.8
        reasons.append("no_meaningful_signal")

    # --- Exhaustion detection (overrides based on decay signals) ---
    if features.snapshot_count > 1:
        decay_signals = 0
        if features.volume_change < -50:
            decay_signals += 1
        if features.spread_change > 0.05:
            decay_signals += 1
        if features.oi_change < -10:
            decay_signals += 1
        if features.life_elapsed_pct > 0.90:
            decay_signals += 1

        if decay_signals >= 2 and state in (MarketState.FORMING, MarketState.ACTIONABLE):
            state = MarketState.EXHAUSTED
            confidence = 0.5 + (decay_signals * 0.1)
            reasons.append(f"decay_signals_{decay_signals}")

    return MarketStateResult(
        ticker=features.ticker,
        event_ticker=features.event_ticker,
        series_ticker=features.series_ticker,
        state=state,
        confidence=round(confidence, 3),
        reason_codes=reasons,
        score=round(score, 3),
    )


def classify_all(features_list: list[MarketFeatures]) -> list[MarketStateResult]:
    """Classify state for all markets."""
    results = []
    for f in features_list:
        results.append(classify_state(f))

    # Log distribution
    dist: dict[MarketState, int] = {}
    for r in results:
        dist[r.state] = dist.get(r.state, 0) + 1

    logger.info(
        "State classification: %d markets — %s",
        len(results),
        ", ".join(f"{s.value}={c}" for s, c in sorted(dist.items(), key=lambda x: -x[1])),
    )

    return results
