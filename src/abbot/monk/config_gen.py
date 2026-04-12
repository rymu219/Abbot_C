"""Phase 9: Monk Configuration Generation.

Turns Monk candidates into first-pass MonkConfig objects with:
- Identity (name, archetype, domain, family)
- Entry rules (trigger conditions, thresholds)
- Exit rules (exit logic, kill conditions)
- Risk rules (exposure limits, cooldown)
- Deployment info (starts in ANALYSIS_ONLY mode)
- Metadata (version 1, rationale from candidate evaluation)

Generated configs are starting points — designed to be tested (Phase 10)
and refined by the operator before deployment.
"""

import logging
from datetime import datetime, timezone

from abbot.pipeline.candidates import MonkCandidate
from abbot.types import (
    ApprovalStatus,
    DeploymentInfo,
    DeploymentMode,
    Domain,
    EntryRules,
    ExitRules,
    LifecycleStatus,
    MonkArchetype,
    MonkConfig,
    MonkIdentity,
    MonkMetadata,
    Platform,
    RiskRules,
)

logger = logging.getLogger(__name__)


def generate_config(candidate: MonkCandidate) -> MonkConfig:
    """Generate a first-pass MonkConfig from a Monk candidate.

    The generated config is conservative by default:
    - Starts in ANALYSIS_ONLY mode
    - Requires operator approval before any deployment
    - Risk limits are tight
    - Entry thresholds are based on the candidate's pattern

    Args:
        candidate: A MonkCandidate from Phase 8.

    Returns:
        A MonkConfig ready for testing (Phase 10).
    """
    # Map frequency to archetype
    archetype = _suggest_archetype(candidate)

    # Map domain string back to enum
    try:
        domain = Domain(candidate.domain)
    except ValueError:
        domain = Domain.OTHER

    identity = MonkIdentity(
        name=_generate_name(candidate),
        archetype=archetype,
        platform=Platform.KALSHI,
        domain=domain,
        family_id=candidate.series_ticker,
    )

    entry = _generate_entry_rules(candidate)
    exit_rules = _generate_exit_rules(candidate)
    risk = _generate_risk_rules(candidate)

    deployment = DeploymentInfo(
        mode=DeploymentMode.ANALYSIS_ONLY,
        lifecycle_status=LifecycleStatus.CANDIDATE,
        approval_status=ApprovalStatus.PENDING,
    )

    metadata = MonkMetadata(
        version=1,
        parent_version=None,
        rationale=_generate_rationale(candidate),
        created_at=datetime.now(timezone.utc),
    )

    config = MonkConfig(
        identity=identity,
        entry=entry,
        exit=exit_rules,
        risk=risk,
        deployment=deployment,
        metadata=metadata,
    )

    logger.info(
        "Generated config: %s (archetype=%s, family=%s)",
        identity.name, archetype.value, candidate.series_ticker,
    )

    return config


def generate_configs(candidates: list[MonkCandidate]) -> list[tuple[MonkCandidate, MonkConfig]]:
    """Generate configs for all BUILD_CANDIDATE and PROTOTYPE_CANDIDATE candidates.

    Returns list of (candidate, config) tuples.
    """
    eligible = [
        c for c in candidates
        if c.decision.value in ("build_candidate", "prototype_candidate")
    ]

    results = []
    for candidate in eligible:
        config = generate_config(candidate)
        results.append((candidate, config))

    logger.info("Generated %d Monk configs from %d candidates", len(results), len(candidates))
    return results


# --- Helpers ---


def _generate_name(candidate: MonkCandidate) -> str:
    """Generate a human-readable Monk name."""
    # Clean the title for naming
    title = candidate.title[:30].replace(" ", "-").lower()
    title = "".join(c for c in title if c.isalnum() or c == "-")
    return f"monk-{title}"


def _suggest_archetype(candidate: MonkCandidate) -> MonkArchetype:
    """Map candidate pattern to a Monk archetype.

    For MVP, everything is UPSTREAM_SCOUT since we're in the
    scanning/discovery phase. Future archetypes (direction_trader,
    spread_trader, etc.) will be added as downstream Monks are built.
    """
    return MonkArchetype.UPSTREAM_SCOUT


def _generate_entry_rules(candidate: MonkCandidate) -> EntryRules:
    """Generate entry rules based on the candidate's pattern."""
    p = candidate.pattern

    # Base trigger: enter when market transitions to FORMING or ACTIONABLE
    trigger = {
        "type": "state_transition",
        "target_states": ["forming", "actionable"],
        "min_confidence": 0.5,
    }

    # Thresholds calibrated to the family's observed activity
    thresholds = {
        "min_volume": max(10, p.total_volume * 0.01),  # 1% of observed family volume
        "min_open_interest": 5,
        "max_life_elapsed_pct": 0.85,  # Don't enter markets near expiry
    }

    # Liquidity rules
    liquidity_rules = {
        "min_volume_for_entry": 10,
        "min_bid_exists": True,
    }

    # Spread rules
    spread_rules = {
        "max_spread_pct": 0.30,  # Don't trade if spread > 30% of midpoint
        "prefer_tight": True,
    }

    # Timing
    timing = {
        "min_hours_to_expiry": 2,
        "preferred_entry_window": "early_to_mid_life",
    }

    return EntryRules(
        trigger=trigger,
        thresholds=thresholds,
        liquidity_rules=liquidity_rules,
        spread_rules=spread_rules,
        timing=timing,
    )


def _generate_exit_rules(candidate: MonkCandidate) -> ExitRules:
    """Generate exit rules."""
    exit_logic = {
        "type": "state_based",
        "exit_on_states": ["exhausted"],
        "exit_on_profit_pct": 0.15,  # Take profit at 15%
        "exit_on_loss_pct": -0.10,   # Stop loss at 10%
    }

    invalidation = {
        "volume_drops_below": 5,
        "spread_exceeds": 0.50,
        "state_reverts_to": ["ignore"],
    }

    kill_conditions = [
        "market_settled",
        "market_closed",
        "api_failure_sustained",
        "risk_limit_breach",
    ]

    return ExitRules(
        exit_logic=exit_logic,
        invalidation=invalidation,
        kill_conditions=kill_conditions,
    )


def _generate_risk_rules(candidate: MonkCandidate) -> RiskRules:
    """Generate conservative risk rules."""
    return RiskRules(
        max_exposure=100.0,         # $100 max per market
        max_position_size=50.0,     # $50 max per position
        max_daily_loss=25.0,        # $25 max daily loss
        cooldown_seconds=300,       # 5 min cooldown between trades
        additional_limits={
            "max_concurrent_positions": 3,
            "max_trades_per_day": 10,
            "paper_mode_first": True,
        },
    )


def _generate_rationale(candidate: MonkCandidate) -> str:
    """Generate a human-readable rationale for the config."""
    parts = [
        f"Auto-generated from candidate {candidate.series_ticker}.",
        f"Family: {candidate.title}.",
        f"Domain: {candidate.domain}, Frequency: {candidate.frequency}.",
        f"Monk worthiness: {candidate.monk_worthiness:.2f}.",
        f"Decision: {candidate.decision.value}.",
    ]
    if candidate.reason_codes:
        parts.append(f"Signals: {', '.join(candidate.reason_codes[:5])}.")
    return " ".join(parts)
