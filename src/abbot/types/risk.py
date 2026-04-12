"""Risk control types mapped from Requirements Document Section 7.

Stop conditions are categorized by source: risk, behavior, market, system, data.
Each condition maps to an action: pause, kill, downgrade, or require review.
"""

from enum import StrEnum


class StopConditionType(StrEnum):
    """What triggered the stop."""

    # Risk
    DRAWDOWN_BREACH = "drawdown_breach"
    EXPOSURE_BREACH = "exposure_breach"
    LOSS_CLUSTERING = "loss_clustering"

    # Behavior
    INVALID_TRIGGER = "invalid_trigger"
    LOGIC_DEVIATION = "logic_deviation"

    # Market
    LOW_LIQUIDITY = "low_liquidity"
    WIDE_SPREAD = "wide_spread"

    # System
    API_FAILURE = "api_failure"
    STALE_DATA = "stale_data"

    # Data
    MISSING_DATA = "missing_data"
    CORRUPT_DATA = "corrupt_data"


class StopAction(StrEnum):
    """What to do when a stop condition fires."""

    PAUSE = "pause"
    KILL = "kill"
    DOWNGRADE = "downgrade"
    REQUIRE_REVIEW = "require_review"
