"""Phase 8: Pattern & Candidate Discovery.

Moves from "interesting markets" to "patterns that may deserve Monks."

Takes the output of distillation (scored families) and state classification
(market states), groups by family, and evaluates whether a family's pattern
is recurring, tradable, and distinct enough to justify a dedicated Monk.

Gates (from Requirements Section 3):
  1. Structural Reality: >= 5 occurrences, consistent structure, belongs to family
  2. Tradability: sufficient liquidity, acceptable spread, enough time to act
  3. Repeatability: consistent behavior, not one-off, testable sample size
  4. Distinctness: not redundant with existing Monks

Outputs:
  NO_MONK, WATCH_LONGER, PROTOTYPE_CANDIDATE, BUILD_CANDIDATE
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from abbot.pipeline.distill import DistilledFamily
from abbot.pipeline.state import MarketStateResult
from abbot.types import MarketState, MonkCandidateDecision

logger = logging.getLogger(__name__)


@dataclass
class FamilyPattern:
    """Aggregated pattern stats for a family across its markets."""

    series_ticker: str
    title: str
    domain: str
    frequency: str

    # From distillation
    family_composite_score: float
    family_decision: str

    # Market state distribution
    total_markets: int = 0
    actionable_count: int = 0
    forming_count: int = 0
    early_count: int = 0
    ignore_count: int = 0
    exhausted_count: int = 0

    # Tradability signals
    markets_with_volume: int = 0
    markets_with_bids: int = 0
    total_volume: float = 0.0
    avg_spread: float = 0.0

    # Event count (recurrence measure)
    event_count: int = 0


@dataclass
class MonkCandidate:
    """A family pattern evaluated for Monk worthiness."""

    series_ticker: str
    title: str
    domain: str
    frequency: str
    pattern: FamilyPattern

    # Gate scores (0.0 to 1.0)
    structural_score: float = 0.0
    tradability_score: float = 0.0
    repeatability_score: float = 0.0
    distinctness_score: float = 1.0  # Default to distinct (no existing Monks yet)

    # Overall
    monk_worthiness: float = 0.0
    decision: MonkCandidateDecision = MonkCandidateDecision.NO_MONK
    reason_codes: list[str] = field(default_factory=list)
    archetype_suggestion: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "series_ticker": self.series_ticker,
            "title": self.title,
            "domain": self.domain,
            "frequency": self.frequency,
            "gates": {
                "structural": round(self.structural_score, 3),
                "tradability": round(self.tradability_score, 3),
                "repeatability": round(self.repeatability_score, 3),
                "distinctness": round(self.distinctness_score, 3),
            },
            "monk_worthiness": round(self.monk_worthiness, 3),
            "decision": self.decision.value,
            "reason_codes": self.reason_codes,
            "archetype_suggestion": self.archetype_suggestion,
            "pattern": {
                "total_markets": self.pattern.total_markets,
                "actionable": self.pattern.actionable_count,
                "forming": self.pattern.forming_count,
                "early": self.pattern.early_count,
                "volume": self.pattern.total_volume,
                "event_count": self.pattern.event_count,
            },
        }


def discover_candidates(
    families: list[DistilledFamily],
    states: list[MarketStateResult],
    existing_monks: list[str] | None = None,
) -> list[MonkCandidate]:
    """Evaluate families for Monk candidacy.

    Args:
        families: Scored families from distillation (Phase 5).
        states: State classifications from scan (Phase 7).
        existing_monks: Series tickers of already-deployed Monks (for distinctness).

    Returns:
        Sorted list of MonkCandidates, best first.
    """
    if existing_monks is None:
        existing_monks = []

    # Build state lookup by series_ticker
    family_states: dict[str, list[MarketStateResult]] = {}
    for s in states:
        key = s.series_ticker
        if key:
            family_states.setdefault(key, []).append(s)

    # Only evaluate non-IGNORE families
    eligible = [f for f in families if f.decision.value != "ignore"]
    logger.info("Evaluating %d eligible families (from %d total)", len(eligible), len(families))

    candidates = []
    for family in eligible:
        market_states = family_states.get(family.series_ticker, [])
        pattern = _build_pattern(family, market_states)
        candidate = _evaluate_candidate(pattern, family, existing_monks)
        candidates.append(candidate)

    # Sort by worthiness
    candidates.sort(key=lambda c: c.monk_worthiness, reverse=True)

    # Log summary
    decisions: dict[str, int] = {}
    for c in candidates:
        decisions[c.decision.value] = decisions.get(c.decision.value, 0) + 1

    logger.info(
        "Candidate discovery: %d evaluated — %s",
        len(candidates),
        ", ".join(f"{d}={c}" for d, c in sorted(decisions.items(), key=lambda x: -x[1])),
    )

    return candidates


def _build_pattern(family: DistilledFamily, states: list[MarketStateResult]) -> FamilyPattern:
    """Aggregate market states into a family-level pattern."""
    pattern = FamilyPattern(
        series_ticker=family.series_ticker,
        title=family.title,
        domain=family.domain.value,
        frequency=family.frequency,
        family_composite_score=family.composite_score,
        family_decision=family.decision.value,
        total_markets=len(states),
        event_count=family.event_count,
        total_volume=family.total_volume,
        avg_spread=family.avg_spread,
        markets_with_volume=family.markets_with_volume,
    )

    for s in states:
        if s.state == MarketState.ACTIONABLE:
            pattern.actionable_count += 1
        elif s.state == MarketState.FORMING:
            pattern.forming_count += 1
        elif s.state == MarketState.EARLY:
            pattern.early_count += 1
        elif s.state == MarketState.EXHAUSTED:
            pattern.exhausted_count += 1
        else:
            pattern.ignore_count += 1

    return pattern


def _evaluate_candidate(
    pattern: FamilyPattern,
    family: DistilledFamily,
    existing_monks: list[str],
) -> MonkCandidate:
    """Run the four gates and assign a Monk candidate decision."""
    candidate = MonkCandidate(
        series_ticker=pattern.series_ticker,
        title=pattern.title,
        domain=pattern.domain,
        frequency=pattern.frequency,
        pattern=pattern,
    )

    reasons = []

    # --- Gate 1: Structural Reality ---
    # Do we have enough occurrences and consistent structure?
    if pattern.event_count >= 10:
        candidate.structural_score = 1.0
        reasons.append("strong_recurrence")
    elif pattern.event_count >= 5:
        candidate.structural_score = 0.7
        reasons.append("moderate_recurrence")
    elif pattern.event_count >= 2:
        candidate.structural_score = 0.4
        reasons.append("low_recurrence")
    else:
        candidate.structural_score = 0.1
        reasons.append("insufficient_recurrence")

    # Bonus for having markets in non-IGNORE states
    active_ratio = (
        (pattern.actionable_count + pattern.forming_count + pattern.early_count)
        / max(1, pattern.total_markets)
    )
    if active_ratio > 0.5:
        candidate.structural_score = min(1.0, candidate.structural_score + 0.15)
        reasons.append("active_markets")

    # --- Gate 2: Tradability ---
    # Sufficient liquidity, acceptable spread, time to act
    trad_score = 0.0

    if pattern.total_volume >= 1000:
        trad_score += 0.4
        reasons.append("good_volume")
    elif pattern.total_volume >= 100:
        trad_score += 0.2
        reasons.append("some_volume")
    elif pattern.markets_with_volume > 0:
        trad_score += 0.1

    if pattern.avg_spread > 0:
        if pattern.avg_spread <= 0.10:
            trad_score += 0.4
            reasons.append("tight_spreads")
        elif pattern.avg_spread <= 0.25:
            trad_score += 0.2
            reasons.append("moderate_spreads")
        else:
            trad_score += 0.05
            reasons.append("wide_spreads")

    if pattern.actionable_count > 0:
        trad_score += 0.2
        reasons.append("has_actionable")

    candidate.tradability_score = min(1.0, trad_score)

    # --- Gate 3: Repeatability ---
    # Consistent behavior, not one-off, enough data to test
    repeat_score = family.repeatability_score * 0.5  # From distillation
    repeat_score += family.cadence_score * 0.3       # Frequency matters
    repeat_score += family.automation_score * 0.2    # Automation fit

    candidate.repeatability_score = min(1.0, repeat_score)

    if family.frequency in ("fifteen_min", "hourly", "daily"):
        reasons.append("high_cadence")
    elif family.frequency in ("weekly", "monthly"):
        reasons.append("moderate_cadence")

    # --- Gate 4: Distinctness ---
    # Not redundant with existing Monks
    if pattern.series_ticker in existing_monks:
        candidate.distinctness_score = 0.0
        reasons.append("already_has_monk")
    else:
        candidate.distinctness_score = 1.0

    # --- Overall Monk Worthiness ---
    candidate.monk_worthiness = (
        0.25 * candidate.structural_score
        + 0.30 * candidate.tradability_score
        + 0.25 * candidate.repeatability_score
        + 0.20 * candidate.distinctness_score
    )

    # --- Decision ---
    if candidate.distinctness_score == 0:
        candidate.decision = MonkCandidateDecision.NO_MONK
        reasons.append("redundant")
    elif candidate.monk_worthiness >= 0.60:
        candidate.decision = MonkCandidateDecision.BUILD_CANDIDATE
    elif candidate.monk_worthiness >= 0.45:
        candidate.decision = MonkCandidateDecision.PROTOTYPE_CANDIDATE
    elif candidate.monk_worthiness >= 0.30:
        candidate.decision = MonkCandidateDecision.WATCH_LONGER
    else:
        candidate.decision = MonkCandidateDecision.NO_MONK
        reasons.append("below_threshold")

    # --- Archetype suggestion ---
    if candidate.decision in (
        MonkCandidateDecision.BUILD_CANDIDATE,
        MonkCandidateDecision.PROTOTYPE_CANDIDATE,
    ):
        if pattern.frequency in ("fifteen_min", "hourly"):
            candidate.archetype_suggestion = "high_frequency_direction"
        elif pattern.frequency in ("daily", "weekly"):
            candidate.archetype_suggestion = "recurring_event"
        elif pattern.frequency == "monthly":
            candidate.archetype_suggestion = "calendar_event"
        else:
            candidate.archetype_suggestion = "custom_pattern"

    candidate.reason_codes = reasons
    return candidate
