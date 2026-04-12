"""Decision types used throughout the pipeline.

Family decisions come from distillation (Phase 5).
Monk candidate decisions come from pattern discovery (Phase 8).
Discovery decisions come from signal scanning (Section 3 of requirements).
Test verdicts come from the testing framework (Phase 10).
"""

from enum import StrEnum


class FamilyDecision(StrEnum):
    """Outcome of family-worthiness evaluation."""

    IGNORE = "ignore"
    WATCH = "watch"
    PRIORITIZE = "prioritize"


class DiscoveryDecision(StrEnum):
    """Outcome of signal discovery gates (Requirements Section 3)."""

    IGNORE = "ignore"
    WATCH = "watch"
    DISCOVERY_CANDIDATE = "discovery_candidate"
    MONK_CANDIDATE = "monk_candidate"


class MonkCandidateDecision(StrEnum):
    """Outcome of Monk candidate evaluation."""

    NO_MONK = "no_monk"
    WATCH_LONGER = "watch_longer"
    PROTOTYPE_CANDIDATE = "prototype_candidate"
    BUILD_CANDIDATE = "build_candidate"


class TestVerdict(StrEnum):
    """Outcome of Monk config testing."""

    REJECT = "reject"
    REVISE = "revise"
    PAPER_LONGER = "paper_longer"
    ELIGIBLE_FOR_DEPLOY = "eligible_for_deploy"
