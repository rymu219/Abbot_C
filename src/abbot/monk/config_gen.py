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


def generate_config(
    candidate: MonkCandidate,
    blueprint=None,
) -> MonkConfig:
    """Generate a MonkConfig from a candidate + optional StrategyBlueprint.

    When blueprint is provided: entry/exit/risk rules come from data mining.
    When blueprint is None: falls back to conservative template defaults.

    Args:
        candidate: A MonkCandidate from Phase 8.
        blueprint: Optional StrategyBlueprint from the mining engine.

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

    entry = _generate_entry_rules(candidate, blueprint)
    exit_rules = _generate_exit_rules(candidate, blueprint)
    risk = _generate_risk_rules(candidate, blueprint)

    deployment = DeploymentInfo(
        mode=DeploymentMode.ANALYSIS_ONLY,
        lifecycle_status=LifecycleStatus.CANDIDATE,
        approval_status=ApprovalStatus.PENDING,
    )

    metadata = MonkMetadata(
        version=1,
        parent_version=None,
        rationale=_generate_rationale(candidate, blueprint),
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


def _generate_entry_rules(candidate: MonkCandidate, blueprint=None) -> EntryRules:
    """Generate entry rules. Data-derived when blueprint is available."""
    p = candidate.pattern

    if blueprint and blueprint.viable:
        # DATA-DERIVED RULES from strategy mining
        trigger = {
            "type": "price_threshold",
            "target_states": ["forming", "actionable"],
            "min_confidence": 0.5,
        }
        thresholds = {
            "preferred_side": blueprint.recommended_side,
            "entry_price_max": blueprint.optimal_entry,
            "entry_price_min": blueprint.entry_price_min,
            "entry_price_range": [blueprint.entry_price_min, blueprint.entry_price_max],
            "min_volume": blueprint.min_volume_threshold,
            "max_life_elapsed_pct": blueprint.timing_pct_max,
        }
        spread_rules = {
            "max_spread_pct": 0.30,
            "prefer_tight": True,
        }
        timing = {
            "min_hours_to_expiry": 1,
            "preferred_entry_window": blueprint.preferred_timing,
            "timing_pct_min": blueprint.timing_pct_min,
            "timing_pct_max": blueprint.timing_pct_max,
        }
    else:
        # TEMPLATE DEFAULTS (fallback)
        trigger = {
            "type": "state_transition",
            "target_states": ["forming", "actionable"],
            "min_confidence": 0.5,
        }
        thresholds = {
            "preferred_side": "yes",
            "entry_price_max": 0.50,
            "min_volume": max(10, p.total_volume * 0.01),
            "max_life_elapsed_pct": 0.85,
        }
        spread_rules = {
            "max_spread_pct": 0.30,
            "prefer_tight": True,
        }
        timing = {
            "min_hours_to_expiry": 2,
            "preferred_entry_window": "early_to_mid_life",
        }

    liquidity_rules = {"min_volume_for_entry": 10, "min_bid_exists": True}

    return EntryRules(
        trigger=trigger,
        thresholds=thresholds,
        liquidity_rules=liquidity_rules,
        spread_rules=spread_rules,
        timing=timing,
    )


def _generate_exit_rules(candidate: MonkCandidate, blueprint=None) -> ExitRules:
    """Generate exit rules. Data-derived when blueprint is available."""
    if blueprint and blueprint.viable:
        exit_logic = {
            "type": "state_based",
            "exit_on_states": ["exhausted"],
            "exit_on_profit_pct": blueprint.take_profit_pct,
            "exit_on_loss_pct": -blueprint.stop_loss_pct,
        }
    else:
        exit_logic = {
            "type": "state_based",
            "exit_on_states": ["exhausted"],
            "exit_on_profit_pct": 0.15,
            "exit_on_loss_pct": -0.10,
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


def _generate_risk_rules(candidate: MonkCandidate, blueprint=None) -> RiskRules:
    """Generate risk rules. Sized by strategy quality when blueprint available."""
    if blueprint and blueprint.viable:
        return RiskRules(
            max_exposure=100.0,
            max_position_size=blueprint.suggested_position_size,
            max_daily_loss=blueprint.suggested_max_daily_loss,
            cooldown_seconds=300,
            additional_limits={
                "max_concurrent_positions": 3,
                "max_trades_per_day": 10,
                "paper_mode_first": True,
            },
        )
    return RiskRules(
        max_exposure=100.0,
        max_position_size=50.0,
        max_daily_loss=25.0,
        cooldown_seconds=300,
        additional_limits={
            "max_concurrent_positions": 3,
            "max_trades_per_day": 10,
            "paper_mode_first": True,
        },
    )


def _generate_rationale(candidate: MonkCandidate, blueprint=None) -> str:
    """Generate a human-readable rationale for the config."""
    parts = [
        f"Family: {candidate.title} ({candidate.series_ticker}).",
        f"Domain: {candidate.domain}, Frequency: {candidate.frequency}.",
    ]

    if blueprint and blueprint.viable:
        parts.append(
            f"STRATEGY MINED from {blueprint.total_settled} settled markets "
            f"(train={blueprint.train_count}, test={blueprint.test_count})."
        )
        parts.append(
            f"Entry: {blueprint.recommended_side.upper()} "
            f"{'below' if blueprint.recommended_side == 'yes' else 'above'} "
            f"${blueprint.optimal_entry:.2f}."
        )
        parts.append(
            f"Train WR: {blueprint.train_win_rate*100:.1f}%, "
            f"Test WR: {blueprint.test_win_rate*100:.1f}%, "
            f"p={blueprint.statistical_significance:.3f}."
        )
    else:
        parts.append("Template-based config (no strategy mined).")
        parts.append(f"Worthiness: {candidate.monk_worthiness:.2f}.")

    return " ".join(parts)
