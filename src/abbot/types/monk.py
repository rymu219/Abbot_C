"""Monk configuration schema mapped from Requirements Document Section 4.

A Monk is an explicit, versioned rule system. MonkConfig is the complete
specification of a Monk's identity, entry/exit rules, risk controls,
deployment state, and metadata.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from abbot.types.deployment import DeploymentMode, LifecycleStatus
from abbot.types.taxonomy import Domain, Platform


class MonkArchetype(StrEnum):
    """Known Monk behavioral patterns. Expanded as new patterns are discovered."""

    UPSTREAM_SCOUT = "upstream_scout"  # Monk-01's archetype


class ApprovalStatus(StrEnum):
    """Whether a Monk config has been approved for deployment."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


# --- Nested config components ---


class MonkIdentity(BaseModel):
    """Who this Monk is."""

    name: str
    archetype: MonkArchetype
    platform: Platform = Platform.KALSHI
    domain: Domain | None = None
    family_id: str | None = None


class EntryRules(BaseModel):
    """When and how a Monk enters a position.

    Fields are loosely typed at this stage — the specific structure of
    triggers and thresholds depends on the archetype and will be refined
    as archetypes are developed.
    """

    trigger: dict | None = None  # state/transition trigger definition
    thresholds: dict | None = None
    liquidity_rules: dict | None = None
    spread_rules: dict | None = None
    timing: dict | None = None


class ExitRules(BaseModel):
    """When and how a Monk exits a position."""

    exit_logic: dict | None = None
    invalidation: dict | None = None
    kill_conditions: list[str] = []


class RiskRules(BaseModel):
    """Risk constraints for this Monk."""

    max_exposure: float | None = None
    max_position_size: float | None = None
    max_daily_loss: float | None = None
    cooldown_seconds: int | None = None
    additional_limits: dict | None = None


class DeploymentInfo(BaseModel):
    """Current deployment state."""

    mode: DeploymentMode = DeploymentMode.ANALYSIS_ONLY
    lifecycle_status: LifecycleStatus = LifecycleStatus.IDEA
    approval_status: ApprovalStatus = ApprovalStatus.PENDING


class MonkMetadata(BaseModel):
    """Version tracking and lineage."""

    version: int = 1
    parent_version: int | None = None
    rationale: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- Top-level config ---


class MonkConfig(BaseModel):
    """Complete Monk specification. Maps to Requirements Document Section 4."""

    identity: MonkIdentity
    entry: EntryRules = EntryRules()
    exit: ExitRules = ExitRules()
    risk: RiskRules = RiskRules()
    deployment: DeploymentInfo = DeploymentInfo()
    metadata: MonkMetadata = MonkMetadata()
