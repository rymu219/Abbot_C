"""Phase 11: Approval Workflow.

Human-gated deployment control. The system suggests, the operator decides.

Workflow:
  1. Monk config is generated (Phase 9)
  2. Config is tested (Phase 10)
  3. Test report is presented to operator
  4. Operator reviews and approves/rejects
  5. If approved, Monk is promoted to next lifecycle stage
  6. Deployment mode is set (paper → live small → live scaled)

Nothing deploys without explicit operator approval.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from abbot.monk.testing import TestReport
from abbot.types import (
    ApprovalStatus,
    DeploymentMode,
    LifecycleStatus,
    MonkConfig,
    is_valid_lifecycle_transition,
)

logger = logging.getLogger(__name__)


def present_for_approval(config: MonkConfig, report: TestReport) -> dict:
    """Package a Monk config and test report for operator review.

    Returns a summary dict the CLI can display.
    """
    return {
        "monk_name": config.identity.name,
        "family": config.identity.family_id,
        "domain": str(config.identity.domain) if config.identity.domain else "?",
        "archetype": config.identity.archetype.value,
        "current_status": config.deployment.lifecycle_status.value,
        "current_mode": config.deployment.mode.value,
        "approval_status": config.deployment.approval_status.value,
        "test_verdict": report.verdict.value,
        "test_confidence": report.confidence,
        "trade_count": report.trade_count,
        "total_pnl": report.total_pnl,
        "win_rate": report.win_rate,
        "max_drawdown": report.max_drawdown,
        "profit_factor": report.profit_factor,
        "verdict_reasons": report.verdict_reasons,
        "risk_limits": {
            "max_exposure": config.risk.max_exposure,
            "max_position_size": config.risk.max_position_size,
            "max_daily_loss": config.risk.max_daily_loss,
        },
    }


def approve_config(config: MonkConfig, target_mode: DeploymentMode) -> MonkConfig:
    """Approve a Monk config for deployment at the specified mode.

    Validates the lifecycle transition and updates the config.
    Returns the updated config.
    """
    # Determine target lifecycle from mode
    mode_to_lifecycle = {
        DeploymentMode.ANALYSIS_ONLY: LifecycleStatus.CANDIDATE,
        DeploymentMode.PAPER_ONLY: LifecycleStatus.PAPER,
        DeploymentMode.LIVE_SMALL: LifecycleStatus.PROBATION,
        DeploymentMode.LIVE_SCALED: LifecycleStatus.LIVE,
    }

    target_lifecycle = mode_to_lifecycle.get(target_mode, LifecycleStatus.CANDIDATE)
    current_lifecycle = config.deployment.lifecycle_status

    # Validate transition
    if not is_valid_lifecycle_transition(current_lifecycle, target_lifecycle):
        raise ValueError(
            f"Invalid lifecycle transition: {current_lifecycle.value} → {target_lifecycle.value}. "
            f"Check VALID_LIFECYCLE_TRANSITIONS for allowed paths."
        )

    # Update config
    config.deployment.approval_status = ApprovalStatus.APPROVED
    config.deployment.mode = target_mode
    config.deployment.lifecycle_status = target_lifecycle
    config.metadata.updated_at = datetime.now(timezone.utc)

    logger.info(
        "Approved %s: %s → %s (mode: %s)",
        config.identity.name,
        current_lifecycle.value,
        target_lifecycle.value,
        target_mode.value,
    )

    return config


def reject_config(config: MonkConfig, reason: str = "") -> MonkConfig:
    """Reject a Monk config."""
    config.deployment.approval_status = ApprovalStatus.REJECTED
    config.metadata.updated_at = datetime.now(timezone.utc)
    if reason:
        config.metadata.rationale += f" REJECTED: {reason}"

    logger.info("Rejected %s: %s", config.identity.name, reason)
    return config


def pause_monk(config: MonkConfig) -> MonkConfig:
    """Pause a running Monk."""
    current = config.deployment.lifecycle_status
    if not is_valid_lifecycle_transition(current, LifecycleStatus.PAUSED):
        raise ValueError(f"Cannot pause from {current.value}")

    config.deployment.lifecycle_status = LifecycleStatus.PAUSED
    config.metadata.updated_at = datetime.now(timezone.utc)
    logger.info("Paused %s", config.identity.name)
    return config


def kill_monk(config: MonkConfig) -> MonkConfig:
    """Kill (retire) a Monk permanently."""
    config.deployment.lifecycle_status = LifecycleStatus.RETIRED
    config.deployment.approval_status = ApprovalStatus.REVOKED
    config.metadata.updated_at = datetime.now(timezone.utc)
    logger.info("Killed %s", config.identity.name)
    return config


def return_to_paper(config: MonkConfig) -> MonkConfig:
    """Return a live Monk to paper mode for re-evaluation."""
    current = config.deployment.lifecycle_status
    if not is_valid_lifecycle_transition(current, LifecycleStatus.PAPER):
        raise ValueError(f"Cannot return to paper from {current.value}")

    config.deployment.lifecycle_status = LifecycleStatus.PAPER
    config.deployment.mode = DeploymentMode.PAPER_ONLY
    config.metadata.updated_at = datetime.now(timezone.utc)
    logger.info("Returned %s to paper", config.identity.name)
    return config
