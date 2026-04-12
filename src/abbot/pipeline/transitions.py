"""Phase 7 (cont.): Transition Detection.

Compares current state classifications against previous ones
to detect meaningful state changes.

Key transitions the system watches for:
  IGNORE → EARLY       (something is waking up)
  EARLY → FORMING      (momentum building)
  FORMING → ACTIONABLE (opportunity crystallizing)
  ACTIONABLE → EXHAUSTED (opportunity decaying)

Transitions are the primary signal for Monk candidate identification (Phase 8).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from abbot.pipeline.state import MarketStateResult
from abbot.types import MarketState, VALID_TRANSITIONS

logger = logging.getLogger(__name__)


@dataclass
class DetectedTransition:
    """A detected state change for a market."""

    ticker: str
    event_ticker: str
    series_ticker: str | None
    from_state: MarketState
    to_state: MarketState
    is_progression: bool     # Moving forward in the lifecycle?
    significance: str        # "high", "medium", "low"
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Transitions ranked by significance for Monk-01
TRANSITION_SIGNIFICANCE: dict[tuple[MarketState, MarketState], str] = {
    # Progressions (the ones we care about most)
    (MarketState.FORMING, MarketState.ACTIONABLE): "high",
    (MarketState.EARLY, MarketState.FORMING): "high",
    (MarketState.IGNORE, MarketState.EARLY): "medium",
    # Decay
    (MarketState.ACTIONABLE, MarketState.EXHAUSTED): "medium",
    (MarketState.FORMING, MarketState.EARLY): "low",
    (MarketState.EARLY, MarketState.IGNORE): "low",
}


def detect_transitions(
    current: list[MarketStateResult],
    previous: list[MarketStateResult],
) -> list[DetectedTransition]:
    """Compare current vs previous state classifications to find transitions.

    Args:
        current: Latest state classifications.
        previous: Previous state classifications (from last run).

    Returns:
        List of detected transitions, sorted by significance.
    """
    prev_map = {r.ticker: r for r in previous}
    transitions = []

    for curr in current:
        prev = prev_map.get(curr.ticker)
        if prev is None:
            continue  # New market, no transition to detect
        if curr.state == prev.state:
            continue  # No change

        # Validate the transition
        pair = (prev.state, curr.state)
        if pair not in VALID_TRANSITIONS:
            logger.warning(
                "Invalid transition for %s: %s → %s (skipped)",
                curr.ticker, prev.state.value, curr.state.value,
            )
            continue

        # Determine if progression or decay
        state_order = list(MarketState)
        is_prog = state_order.index(curr.state) > state_order.index(prev.state)

        significance = TRANSITION_SIGNIFICANCE.get(pair, "low")

        transitions.append(DetectedTransition(
            ticker=curr.ticker,
            event_ticker=curr.event_ticker,
            series_ticker=curr.series_ticker,
            from_state=prev.state,
            to_state=curr.state,
            is_progression=is_prog,
            significance=significance,
        ))

    # Sort: high significance first, then progressions before decay
    sig_order = {"high": 0, "medium": 1, "low": 2}
    transitions.sort(key=lambda t: (sig_order.get(t.significance, 3), not t.is_progression))

    logger.info(
        "Transitions detected: %d (high=%d, medium=%d, low=%d)",
        len(transitions),
        sum(1 for t in transitions if t.significance == "high"),
        sum(1 for t in transitions if t.significance == "medium"),
        sum(1 for t in transitions if t.significance == "low"),
    )

    return transitions
