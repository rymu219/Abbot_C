"""Market states, transitions, and validation.

States represent where a market sits in the opportunity lifecycle.
Transitions are the meaningful changes between states over time.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class MarketState(StrEnum):
    """Position in the opportunity lifecycle."""

    IGNORE = "ignore"
    EARLY = "early"
    FORMING = "forming"
    ACTIONABLE = "actionable"
    EXHAUSTED = "exhausted"


# Allowed state transitions. Forward progression and decay/reversal paths.
VALID_TRANSITIONS: frozenset[tuple[MarketState, MarketState]] = frozenset(
    {
        # Forward progression
        (MarketState.IGNORE, MarketState.EARLY),
        (MarketState.EARLY, MarketState.FORMING),
        (MarketState.FORMING, MarketState.ACTIONABLE),
        (MarketState.ACTIONABLE, MarketState.EXHAUSTED),
        # Decay / reversal
        (MarketState.EARLY, MarketState.IGNORE),
        (MarketState.FORMING, MarketState.EARLY),
        (MarketState.ACTIONABLE, MarketState.FORMING),
        (MarketState.EXHAUSTED, MarketState.ACTIONABLE),
        # Skip-level decay (market collapses)
        (MarketState.FORMING, MarketState.IGNORE),
        (MarketState.ACTIONABLE, MarketState.IGNORE),
        (MarketState.EXHAUSTED, MarketState.IGNORE),
    }
)


class StateTransition(BaseModel):
    """A detected change in market state."""

    from_state: MarketState
    to_state: MarketState
    instrument_ticker: str
    detected_at: datetime
    confidence: float = 0.0
    reason_codes: list[str] = []

    def is_valid(self) -> bool:
        """Check whether this transition is in the allowed set."""
        return (self.from_state, self.to_state) in VALID_TRANSITIONS

    @property
    def is_progression(self) -> bool:
        """True if this transition moves forward in the lifecycle."""
        order = list(MarketState)
        return order.index(self.to_state) > order.index(self.from_state)
