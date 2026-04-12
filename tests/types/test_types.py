"""Tests for the core type system (Phase 2)."""

from datetime import datetime, timezone

from abbot.types import (
    ApprovalStatus,
    DeploymentMode,
    DiscoveryDecision,
    Domain,
    Family,
    FamilyDecision,
    Instrument,
    LifecycleStatus,
    MarketState,
    MonkArchetype,
    MonkCandidateDecision,
    MonkConfig,
    MonkIdentity,
    Platform,
    StateTransition,
    StopAction,
    StopConditionType,
    TestVerdict,
    VALID_LIFECYCLE_TRANSITIONS,
    VALID_TRANSITIONS,
    is_valid_lifecycle_transition,
)


# --- Taxonomy ---


class TestPlatform:
    def test_kalshi_is_only_platform(self):
        assert len(Platform) == 1
        assert Platform.KALSHI == "kalshi"

    def test_platform_is_string(self):
        assert isinstance(Platform.KALSHI, str)
        assert f"platform={Platform.KALSHI}" == "platform=kalshi"


class TestDomain:
    def test_has_expected_domains(self):
        assert Domain.ECONOMICS in Domain
        assert Domain.POLITICS in Domain
        assert Domain.OTHER in Domain

    def test_domain_is_string(self):
        assert Domain.ECONOMICS == "economics"


class TestFamily:
    def test_create_family(self):
        family = Family(
            family_id="cpi-monthly",
            name="Monthly CPI Prints",
            domain=Domain.ECONOMICS,
        )
        assert family.family_id == "cpi-monthly"
        assert family.platform == Platform.KALSHI  # default

    def test_family_optional_fields(self):
        family = Family(
            family_id="test",
            name="Test",
            domain=Domain.OTHER,
        )
        assert family.description == ""
        assert family.created_at is None


class TestInstrument:
    def test_create_instrument(self):
        inst = Instrument(ticker="CPI-25APR-5.0")
        assert inst.ticker == "CPI-25APR-5.0"
        assert inst.family_id is None  # unclassified by default
        assert inst.platform == Platform.KALSHI

    def test_instrument_with_full_context(self):
        inst = Instrument(
            ticker="CPI-25APR-5.0",
            event_ticker="CPI-25APR",
            series_ticker="CPI",
            title="CPI above 5.0% in April 2025",
            family_id="cpi-monthly",
        )
        assert inst.series_ticker == "CPI"


# --- States ---


class TestMarketState:
    def test_all_states_exist(self):
        assert len(MarketState) == 5
        states = {MarketState.IGNORE, MarketState.EARLY, MarketState.FORMING,
                  MarketState.ACTIONABLE, MarketState.EXHAUSTED}
        assert states == set(MarketState)

    def test_state_is_string(self):
        assert MarketState.ACTIONABLE == "actionable"


class TestStateTransition:
    def test_valid_forward_transition(self):
        t = StateTransition(
            from_state=MarketState.EARLY,
            to_state=MarketState.FORMING,
            instrument_ticker="TEST-01",
            detected_at=datetime.now(timezone.utc),
        )
        assert t.is_valid()
        assert t.is_progression

    def test_valid_decay_transition(self):
        t = StateTransition(
            from_state=MarketState.FORMING,
            to_state=MarketState.EARLY,
            instrument_ticker="TEST-01",
            detected_at=datetime.now(timezone.utc),
        )
        assert t.is_valid()
        assert not t.is_progression

    def test_invalid_transition(self):
        t = StateTransition(
            from_state=MarketState.IGNORE,
            to_state=MarketState.ACTIONABLE,
            instrument_ticker="TEST-01",
            detected_at=datetime.now(timezone.utc),
        )
        assert not t.is_valid()  # skips EARLY and FORMING

    def test_skip_level_decay_is_valid(self):
        t = StateTransition(
            from_state=MarketState.ACTIONABLE,
            to_state=MarketState.IGNORE,
            instrument_ticker="TEST-01",
            detected_at=datetime.now(timezone.utc),
        )
        assert t.is_valid()  # collapse is allowed

    def test_reason_codes(self):
        t = StateTransition(
            from_state=MarketState.EARLY,
            to_state=MarketState.FORMING,
            instrument_ticker="TEST-01",
            detected_at=datetime.now(timezone.utc),
            confidence=0.85,
            reason_codes=["volume_increase", "spread_narrowing"],
        )
        assert len(t.reason_codes) == 2


class TestValidTransitions:
    def test_forward_transitions_exist(self):
        assert (MarketState.IGNORE, MarketState.EARLY) in VALID_TRANSITIONS
        assert (MarketState.EARLY, MarketState.FORMING) in VALID_TRANSITIONS
        assert (MarketState.FORMING, MarketState.ACTIONABLE) in VALID_TRANSITIONS
        assert (MarketState.ACTIONABLE, MarketState.EXHAUSTED) in VALID_TRANSITIONS

    def test_no_skip_forward(self):
        assert (MarketState.IGNORE, MarketState.FORMING) not in VALID_TRANSITIONS
        assert (MarketState.IGNORE, MarketState.ACTIONABLE) not in VALID_TRANSITIONS
        assert (MarketState.EARLY, MarketState.ACTIONABLE) not in VALID_TRANSITIONS

    def test_self_transition_not_allowed(self):
        for state in MarketState:
            assert (state, state) not in VALID_TRANSITIONS


# --- Decisions ---


class TestDecisions:
    def test_family_decisions(self):
        assert len(FamilyDecision) == 3

    def test_discovery_decisions(self):
        assert len(DiscoveryDecision) == 4
        assert DiscoveryDecision.MONK_CANDIDATE == "monk_candidate"

    def test_monk_candidate_decisions(self):
        assert len(MonkCandidateDecision) == 4

    def test_test_verdicts(self):
        assert len(TestVerdict) == 4
        assert TestVerdict.ELIGIBLE_FOR_DEPLOY == "eligible_for_deploy"


# --- Deployment ---


class TestDeployment:
    def test_deployment_modes(self):
        assert len(DeploymentMode) == 4

    def test_lifecycle_statuses(self):
        assert len(LifecycleStatus) == 9

    def test_retired_is_terminal(self):
        assert len(VALID_LIFECYCLE_TRANSITIONS[LifecycleStatus.RETIRED]) == 0

    def test_idea_can_become_candidate(self):
        assert is_valid_lifecycle_transition(LifecycleStatus.IDEA, LifecycleStatus.CANDIDATE)

    def test_idea_cannot_skip_to_live(self):
        assert not is_valid_lifecycle_transition(LifecycleStatus.IDEA, LifecycleStatus.LIVE)

    def test_paused_can_return_to_multiple_states(self):
        paused_targets = VALID_LIFECYCLE_TRANSITIONS[LifecycleStatus.PAUSED]
        assert LifecycleStatus.LIVE in paused_targets
        assert LifecycleStatus.PAPER in paused_targets
        assert LifecycleStatus.RETIRED in paused_targets


# --- Risk ---


class TestRisk:
    def test_stop_condition_types(self):
        assert len(StopConditionType) == 11

    def test_stop_actions(self):
        assert len(StopAction) == 4
        assert StopAction.KILL == "kill"


# --- Monk Config ---


class TestMonkConfig:
    def test_create_minimal_config(self):
        config = MonkConfig(
            identity=MonkIdentity(
                name="Monk-01",
                archetype=MonkArchetype.UPSTREAM_SCOUT,
            )
        )
        assert config.identity.name == "Monk-01"
        assert config.deployment.mode == DeploymentMode.ANALYSIS_ONLY
        assert config.deployment.approval_status == ApprovalStatus.PENDING
        assert config.metadata.version == 1

    def test_create_full_config(self):
        config = MonkConfig(
            identity=MonkIdentity(
                name="Monk-01",
                archetype=MonkArchetype.UPSTREAM_SCOUT,
                platform=Platform.KALSHI,
                domain=Domain.ECONOMICS,
                family_id="cpi-monthly",
            ),
            metadata=MonkConfig.model_fields["metadata"].default.__class__(
                version=2,
                parent_version=1,
                rationale="Refined entry thresholds based on replay test",
                created_at=datetime.now(timezone.utc),
            ),
        )
        assert config.identity.family_id == "cpi-monthly"
        assert config.metadata.version == 2
        assert config.metadata.parent_version == 1

    def test_config_serialization(self):
        config = MonkConfig(
            identity=MonkIdentity(
                name="Monk-01",
                archetype=MonkArchetype.UPSTREAM_SCOUT,
            )
        )
        data = config.model_dump()
        assert data["identity"]["name"] == "Monk-01"
        assert data["identity"]["archetype"] == "upstream_scout"

        # Round-trip
        config2 = MonkConfig.model_validate(data)
        assert config2.identity.name == config.identity.name
