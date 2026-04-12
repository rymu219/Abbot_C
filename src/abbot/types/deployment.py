"""Deployment modes, lifecycle statuses, and their valid transitions.

Deployment modes control how a Monk operates.
Lifecycle statuses track where a Monk is in its overall journey.
"""

from enum import StrEnum


class DeploymentMode(StrEnum):
    """How a Monk is currently operating."""

    ANALYSIS_ONLY = "analysis_only"
    PAPER_ONLY = "paper_only"
    LIVE_SMALL = "live_small"
    LIVE_SCALED = "live_scaled"


class LifecycleStatus(StrEnum):
    """Where a Monk is in its overall journey."""

    IDEA = "idea"
    CANDIDATE = "candidate"
    TESTING = "testing"
    PAPER = "paper"
    PROBATION = "probation"
    LIVE = "live"
    SCALED = "scaled"
    PAUSED = "paused"
    RETIRED = "retired"


# Allowed lifecycle transitions. Maps each status to its valid next statuses.
VALID_LIFECYCLE_TRANSITIONS: dict[LifecycleStatus, frozenset[LifecycleStatus]] = {
    LifecycleStatus.IDEA: frozenset({LifecycleStatus.CANDIDATE, LifecycleStatus.RETIRED}),
    LifecycleStatus.CANDIDATE: frozenset(
        {LifecycleStatus.TESTING, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.TESTING: frozenset(
        {LifecycleStatus.PAPER, LifecycleStatus.CANDIDATE, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.PAPER: frozenset(
        {LifecycleStatus.PROBATION, LifecycleStatus.TESTING, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.PROBATION: frozenset(
        {LifecycleStatus.LIVE, LifecycleStatus.PAPER, LifecycleStatus.PAUSED, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.LIVE: frozenset(
        {LifecycleStatus.SCALED, LifecycleStatus.PAUSED, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.SCALED: frozenset(
        {LifecycleStatus.LIVE, LifecycleStatus.PAUSED, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.PAUSED: frozenset(
        {LifecycleStatus.LIVE, LifecycleStatus.PAPER, LifecycleStatus.TESTING, LifecycleStatus.RETIRED}
    ),
    LifecycleStatus.RETIRED: frozenset(),  # Terminal state
}


def is_valid_lifecycle_transition(
    from_status: LifecycleStatus, to_status: LifecycleStatus
) -> bool:
    """Check whether a lifecycle transition is allowed."""
    return to_status in VALID_LIFECYCLE_TRANSITIONS.get(from_status, frozenset())
