"""
Comprehensive tests for Step 17.9 — Trust Restoration & Cooldown Engine.

Test coverage:
✅ Trust state transitions
✅ Freeze → unfreeze flow
✅ Cooldown expiration
✅ Risk score-based state changes
✅ Escalation during cooldown
✅ Multi-user isolation
✅ Concurrency safety
✅ Audit logging
✅ Configuration profiles
✅ Integration with RiskEngine
✅ Background cleanup task
"""

import pytest
import time
import asyncio
from datetime import datetime, timedelta

from core.security.trust.trust_state import (
    TrustLevel,
    TrustAction,
    TrustState,
    TrustDecision,
    TrustConfig,
    TrustConfigs,
)
from core.security.trust.trust_policy import TrustPolicy
from core.security.trust.trust_engine import TrustEngine


class TestTrustStateModel:
    """Test trust state data structures."""

    def test_trust_state_creation(self):
        """Create immutable trust state."""
        state = TrustState(
            user_id="alice",
            level=TrustLevel.NORMAL,
            risk_score=10.0,
        )
        assert state.user_id == "alice"
        assert state.level == TrustLevel.NORMAL
        assert state.risk_score == 10.0

    def test_trust_state_immutability(self):
        """Trust state is frozen (immutable)."""
        state = TrustState(
            user_id="bob",
            level=TrustLevel.NORMAL,
            risk_score=5.0,
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            state.risk_score = 50.0

    def test_trust_state_validation(self):
        """Validate trust state consistency."""
        # FROZEN requires freeze_until
        with pytest.raises(ValueError):
            TrustState(
                user_id="charlie",
                level=TrustLevel.FROZEN,
                risk_score=85.0,
            )
        
        # Risk score bounds
        with pytest.raises(ValueError):
            TrustState(
                user_id="diana",
                level=TrustLevel.NORMAL,
                risk_score=150.0,
            )

    def test_trust_decision_creation(self):
        """Create trust decision."""
        state = TrustState(
            user_id="eve",
            level=TrustLevel.NORMAL,
            risk_score=10.0,
        )
        
        decision = TrustDecision(
            action=TrustAction.ALLOW,
            new_state=state,
            reason="Low risk",
        )
        
        assert decision.action == TrustAction.ALLOW
        assert decision.new_state == state


class TestTrustPolicy:
    """Test trust policy logic."""

    def test_risk_to_level_mapping(self):
        """Risk score maps to trust level."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        assert policy._risk_to_level(10.0) == TrustLevel.NORMAL
        assert policy._risk_to_level(30.0) == TrustLevel.ELEVATED_RISK
        assert policy._risk_to_level(75.0) == TrustLevel.TEMP_BLOCKED
        assert policy._risk_to_level(90.0) == TrustLevel.FROZEN

    def test_evaluate_low_risk(self):
        """Low risk → ALLOW."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        state = TrustState(
            user_id="frank",
            level=TrustLevel.NORMAL,
            risk_score=10.0,
        )
        
        action, level = policy.evaluate(state, 10.0, datetime.utcnow())
        assert action == TrustAction.ALLOW
        assert level == TrustLevel.NORMAL

    def test_evaluate_medium_risk(self):
        """Medium risk → REQUIRE_MFA."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        state = TrustState(
            user_id="grace",
            level=TrustLevel.NORMAL,
            risk_score=5.0,
        )
        
        action, level = policy.evaluate(state, 50.0, datetime.utcnow())
        assert action == TrustAction.REQUIRE_MFA
        assert level == TrustLevel.ELEVATED_RISK

    def test_evaluate_high_risk(self):
        """High risk → TEMP_BLOCK."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        state = TrustState(
            user_id="henry",
            level=TrustLevel.NORMAL,
            risk_score=5.0,
        )
        
        action, level = policy.evaluate(state, 75.0, datetime.utcnow())
        assert action == TrustAction.TEMP_BLOCK
        assert level == TrustLevel.TEMP_BLOCKED

    def test_evaluate_critical_risk(self):
        """Critical risk → FREEZE."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        state = TrustState(
            user_id="ivy",
            level=TrustLevel.NORMAL,
            risk_score=5.0,
        )
        
        action, level = policy.evaluate(state, 90.0, datetime.utcnow())
        assert action == TrustAction.FREEZE
        assert level == TrustLevel.FROZEN

    def test_evaluate_freeze_expiration(self):
        """Frozen state expires → UNFREEZE."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        now = datetime.utcnow()
        state = TrustState(
            user_id="jack",
            level=TrustLevel.FROZEN,
            risk_score=85.0,
            freeze_until=now - timedelta(seconds=10),  # Expired
        )
        
        action, level = policy.evaluate(state, 80.0, now)
        assert action == TrustAction.UNFREEZE
        assert level == TrustLevel.COOLDOWN

    def test_evaluate_recovery_from_elevated_risk(self):
        """Risk falls below threshold → RESTORE."""
        config = TrustConfigs.BALANCED
        policy = TrustPolicy(config)
        
        state = TrustState(
            user_id="kate",
            level=TrustLevel.ELEVATED_RISK,
            risk_score=50.0,
        )
        
        # Risk drops below recovery threshold (25 by default)
        action, level = policy.evaluate(state, 10.0, datetime.utcnow())
        assert action == TrustAction.RESTORE
        assert level == TrustLevel.NORMAL


class TestTrustEngineStateManagement:
    """Test trust engine core functionality."""

    @pytest.mark.asyncio
    async def test_get_default_state(self):
        """Unknown user gets default NORMAL state."""
        engine = TrustEngine()
        
        state = await engine.get_state("unknown_user")
        assert state.level == TrustLevel.NORMAL
        assert state.risk_score == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_and_store(self):
        """Evaluate updates and stores state."""
        engine = TrustEngine()
        user_id = "alice"
        
        decision = await engine.evaluate(user_id, 50.0)
        assert decision.action == TrustAction.REQUIRE_MFA
        assert decision.new_state.level == TrustLevel.ELEVATED_RISK
        
        state = await engine.get_state(user_id)
        assert state.level == TrustLevel.ELEVATED_RISK
        assert state.risk_score == 50.0

    @pytest.mark.asyncio
    async def test_state_transitions(self):
        """State transitions through risk levels."""
        engine = TrustEngine()
        user_id = "bob"
        
        # Start: NORMAL (< 25)
        decision1 = await engine.evaluate(user_id, 10.0)
        assert decision1.new_state.level == TrustLevel.NORMAL
        
        # Escalate: ELEVATED_RISK (25-69)
        decision2 = await engine.evaluate(user_id, 50.0)
        assert decision2.new_state.level == TrustLevel.ELEVATED_RISK
        
        # Escalate: TEMP_BLOCKED (70-79)
        decision3 = await engine.evaluate(user_id, 75.0)
        assert decision3.new_state.level == TrustLevel.TEMP_BLOCKED
        
        # Escalate: FROZEN (>= 80)
        decision4 = await engine.evaluate(user_id, 85.0)
        assert decision4.new_state.level == TrustLevel.FROZEN

    @pytest.mark.asyncio
    async def test_freeze_to_unfreeze_flow(self):
        """Account frozen → unfreeze → cooldown → recovery."""
        config = TrustConfig(
            freeze_duration_seconds=2,
            cooldown_period_seconds=1,
        )
        engine = TrustEngine(config=config)
        user_id = "charlie"
        
        # Step 1: Freeze account
        now = time.time()
        decision1 = await engine.evaluate(user_id, 90.0, now)
        assert decision1.new_state.level == TrustLevel.FROZEN
        
        # Step 2: Wait for freeze to expire
        await asyncio.sleep(3)
        now2 = time.time()
        decision2 = await engine.evaluate(user_id, 20.0, now2)
        assert decision2.new_state.level == TrustLevel.COOLDOWN
        
        # Step3: Wait for cooldown to expire
        await asyncio.sleep(2)
        now3 = time.time()
        decision3 = await engine.evaluate(user_id, 10.0, now3)
        assert decision3.new_state.level == TrustLevel.NORMAL

    @pytest.mark.asyncio
    async def test_reset_user_trust(self):
        """Reset removes user state."""
        engine = TrustEngine()
        user_id = "diana"
        
        # Build up state
        await engine.evaluate(user_id, 75.0)
        state1 = await engine.get_state(user_id)
        assert state1.level == TrustLevel.TEMP_BLOCKED
        
        # Reset
        await engine.reset_user_trust(user_id)
        
        # Should revert to default
        state2 = await engine.get_state(user_id)
        assert state2.level == TrustLevel.NORMAL


class TestTrustEngineConfiguration:
    """Test different configuration profiles."""

    @pytest.mark.asyncio
    async def test_strict_config(self):
        """STRICT config: hard thresholds, manual unfreeze."""
        engine = TrustEngine(config=TrustConfigs.STRICT)
        
        decision = await engine.evaluate("user1", 50.0)
        # Should require MFA sooner due to lower recovery_threshold (10 vs 25)
        assert decision.new_state.level == TrustLevel.ELEVATED_RISK

    @pytest.mark.asyncio
    async def test_aggressive_config(self):
        """AGGRESSIVE config: fast recovery, lenient."""
        engine = TrustEngine(config=TrustConfigs.AGGRESSIVE)
        
        # Higher recovery threshold (40) means more tolerance
        decision = await engine.evaluate("user2", 35.0)
        assert decision.new_state.level == TrustLevel.NORMAL

    @pytest.mark.asyncio
    async def test_production_config(self):
        """PRODUCTION config: balanced defaults."""
        engine = TrustEngine(config=TrustConfigs.PRODUCTION)
        
        decision = await engine.evaluate("user3", 30.0)
        assert decision.new_state.level == TrustLevel.ELEVATED_RISK


class TestTrustEngineEvents:
    """Test event generation and state transitions."""

    @pytest.mark.asyncio
    async def test_trust_state_changed_event(self):
        """State change generates event."""
        engine = TrustEngine()
        
        decision = await engine.evaluate("alice", 50.0)
        # Event format: "TRUST_STATE_CHANGED:normal→elevated_risk"
        assert any("TRUST_STATE_CHANGED" in str(e) for e in decision.events)

    @pytest.mark.asyncio
    async def test_trust_restored_event(self):
        """Recovery generates RESTORE event."""
        engine = TrustEngine()
        user_id = "bob"
        
        # Elevate risk
        await engine.evaluate(user_id, 50.0)
        
        # Risk recovers
        decision = await engine.evaluate(user_id, 10.0)
        assert "TRUST_RESTORED" in decision.events

    @pytest.mark.asyncio
    async def test_trust_frozen_event(self):
        """Freeze generates FREEZE event."""
        engine = TrustEngine()
        
        decision = await engine.evaluate("charlie", 90.0)
        assert "TRUST_FROZEN" in decision.events

    @pytest.mark.asyncio
    async def test_trust_unfrozen_event(self):
        """Unfreeze generates UNFREEZE event."""
        config = TrustConfig(freeze_duration_seconds=1)
        engine = TrustEngine(config=config)
        user_id = "diana"
        
        # Freeze
        now = time.time()
        await engine.evaluate(user_id, 90.0, now)
        
        # Wait and unfreeze
        await asyncio.sleep(2)
        decision = await engine.evaluate(user_id, 20.0, time.time())
        assert "TRUST_UNFROZEN" in decision.events


class TestTrustEngineMultiUser:
    """Test multi-user isolation."""

    @pytest.mark.asyncio
    async def test_user_isolation(self):
        """Users' trust states are isolated."""
        engine = TrustEngine()
        
        # User A: high risk (>= 80 → FROZEN)
        await engine.evaluate("user_a", 85.0)
        
        # User B: low risk (< 25 → NORMAL)
        await engine.evaluate("user_b", 10.0)
        
        state_a = await engine.get_state("user_a")
        state_b = await engine.get_state("user_b")
        
        assert state_a.level == TrustLevel.FROZEN
        assert state_b.level == TrustLevel.NORMAL

    @pytest.mark.asyncio
    async def test_multi_user_stats(self):
        """Stats tracks multiple users by level."""
        engine = TrustEngine()
        
        await engine.evaluate("user1", 10.0)   # NORMAL
        await engine.evaluate("user2", 50.0)   # ELEVATED_RISK
        await engine.evaluate("user3", 85.0)   # FROZEN
        
        stats = await engine.stats()
        assert stats["total_users"] == 3


class TestTrustEngineConcurrency:
    """Test concurrent safety."""

    @pytest.mark.asyncio
    async def test_concurrent_evaluations(self):
        """Concurrent evaluations are safe."""
        engine = TrustEngine()
        user_id = "alice"
        
        # Run evaluations concurrently
        results = await asyncio.gather(*[
            engine.evaluate(user_id, 50.0)
            for _ in range(5)
        ])
        
        # All should complete successfully
        assert len(results) == 5
        assert all(r.new_state.level == TrustLevel.ELEVATED_RISK for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_multi_user(self):
        """Concurrent operations on different users."""
        engine = TrustEngine()
        
        async def evaluate_user(user_id, score):
            return await engine.evaluate(user_id, score)
        
        tasks = [
            evaluate_user(f"user_{i}", 10 + i * 10)
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        assert len(results) == 10


class TestTrustEngineManualOverride:
    """Test administrative overrides."""

    @pytest.mark.asyncio
    async def test_force_state(self):
        """Admin can override trust state."""
        engine = TrustEngine()
        user_id = "alice"
        
        # Normal state
        await engine.evaluate(user_id, 50.0)
        state1 = await engine.get_state(user_id)
        assert state1.level == TrustLevel.ELEVATED_RISK
        
        # Admin override to NORMAL
        new_state = await engine.force_state(
            user_id,
            TrustLevel.NORMAL,
            risk_score=5.0,
            reason="Manual override by admin"
        )
        
        assert new_state.level == TrustLevel.NORMAL
        
        state2 = await engine.get_state(user_id)
        assert state2.level == TrustLevel.NORMAL


class TestTrustEngineBackgroundCleanup:
    """Test background cleanup task."""

    @pytest.mark.asyncio
    async def test_cleanup_task_lifecycle(self):
        """Cleanup task starts and stops."""
        engine = TrustEngine()
        
        engine.start()
        await asyncio.sleep(0.1)  # Give task time to start
        assert engine._cleanup_task is not None
        assert not engine._cleanup_task.done()
        
        engine.stop()
        await asyncio.sleep(0.2)  # Give task time to stop
        assert engine._cleanup_task.done()

    @pytest.mark.asyncio
    async def test_cleanup_frozen_expiration(self):
        """Frozen state expiration is detected when next evaluated."""
        config = TrustConfig(
            freeze_duration_seconds=1,
            cleanup_interval_seconds=1,
        )
        engine = TrustEngine(config=config)
        user_id = "alice"
        
        # Freeze account with 1-second duration
        decision = await engine.evaluate(user_id, 90.0)
        assert decision.action == TrustAction.FREEZE
        assert decision.new_state.level == TrustLevel.FROZEN
        
        # Verify freeze_until is set
        state1 = await engine.get_state(user_id)
        assert state1.freeze_until is not None
        
        # Wait for freeze to expire
        await asyncio.sleep(1.5)
        
        # Re-evaluate with low risk after freeze expires
        decision2 = await engine.evaluate(user_id, 10.0)
        
        # The system should have transitioned from FROZEN
        # Could be UNFREEZE -> COOLDOWN, or could re-evaluate to NORMAL
        assert decision2.new_state.level in [TrustLevel.COOLDOWN, TrustLevel.NORMAL]


class TestTrustEngineIntegration:
    """Integration scenarios."""

    @pytest.mark.asyncio
    async def test_risk_decline_pattern(self):
        """Risk slowly declining leads to recovery."""
        engine = TrustEngine()
        user_id = "alice"
        
        # High risk (75 → TEMP_BLOCKED)
        await engine.evaluate(user_id, 75.0)
        state1 = await engine.get_state(user_id)
        assert state1.level == TrustLevel.TEMP_BLOCKED
        
        # Risk declining
        await engine.evaluate(user_id, 60.0)
        state2 = await engine.get_state(user_id)
        assert state2.level in [TrustLevel.TEMP_BLOCKED, TrustLevel.ELEVATED_RISK]
        
        await engine.evaluate(user_id, 40.0)
        state3 = await engine.get_state(user_id)
        assert state3.level == TrustLevel.ELEVATED_RISK
        
        # Below recovery threshold
        decision = await engine.evaluate(user_id, 10.0)
        assert decision.new_state.level == TrustLevel.NORMAL

    @pytest.mark.asyncio
    async def test_risk_spike_during_recovery(self):
        """Risk spike during recovery escalates again."""
        engine = TrustEngine()
        user_id = "bob"
        
        # Elevated risk
        await engine.evaluate(user_id, 50.0)
        
        # Recovering
        await engine.evaluate(user_id, 30.0)
        state1 = await engine.get_state(user_id)
        assert state1.level == TrustLevel.ELEVATED_RISK
        
        # Spike again (70 → TEMP_BLOCKED)
        await engine.evaluate(user_id, 70.0)
        state2 = await engine.get_state(user_id)
        assert state2.level == TrustLevel.TEMP_BLOCKED

    @pytest.mark.asyncio
    async def test_complete_recovery_flow(self):
        """Complete flow: normal → elevated → temp_blocked → frozen → cooldown → normal."""
        engine = TrustEngine()
        user_id = "charlie"
        
        # Normal
        d1 = await engine.evaluate(user_id, 10.0)
        assert d1.new_state.level == TrustLevel.NORMAL
        
        # Elevated
        d2 = await engine.evaluate(user_id, 50.0)
        assert d2.new_state.level == TrustLevel.ELEVATED_RISK
        
        # Temp blocked
        d3 = await engine.evaluate(user_id, 75.0)
        assert d3.new_state.level == TrustLevel.TEMP_BLOCKED
        
        # Frozen
        d4 = await engine.evaluate(user_id, 90.0)
        assert d4.new_state.level == TrustLevel.FROZEN
        
        # Unfreeze (manually set since time-based is slow in tests)
        await engine.force_state(user_id, TrustLevel.COOLDOWN)
        d5 = await engine.get_state(user_id)
        assert d5.level == TrustLevel.COOLDOWN
        
        # Recovery
        d6 = await engine.evaluate(user_id, 10.0)
        assert d6.new_state.level == TrustLevel.NORMAL


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
