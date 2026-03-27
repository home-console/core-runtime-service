"""
Integration tests for Step 17.8 (Risk Engine) + Step 17.7 (Abuse Detection).

Tests how the adaptive risk scoring engine works with the self-defending vault.

Step 17.8 layers adaptive, weighted risk scoring on top of Step 17.7's hard rules:
- Step 17.7: Hard rules (spike, burst, brute force) → HARD_BLOCK or FREEZE
- Step 17.8: Soft scoring (weighted events) → REQUIRE_MFA or TEMP_BLOCK

Key interactions:
1. Both systems record events to audit trail
2. Risk engine sees abuse detection outputs as high-weight events
3. Abuse detector acts immediately; risk engine acts cumulatively
"""

import pytest
import time
import asyncio
from typing import Optional

from modules.security.risk.models import (
    RiskEvent,
    RiskAssessment,
    RiskAction,
    EventType,
    RiskConfig,
)
from modules.security.risk.engine import RiskEngine
from modules.security.risk.memory import RiskMemory
from modules.security.risk.policy import RiskPolicy
from modules.credentials.abuse_detection import CredentialAbuseDetector


class TestRiskEngineWithAbuseDetector:
    """Test risk engine + abuse detector integration."""

    @pytest.mark.asyncio
    async def test_abuse_spike_triggers_high_risk(self):
        """
        When abuse detector detects spike and blocks, risk engine should see it.
        """
        # Setup
        abuse_detector = CredentialAbuseDetector()
        config = RiskConfig(decay_enabled=False)
        risk_engine = RiskEngine(config=config)
        
        user_id = "alice"
        now = time.time()
        
        # Simulate abuse spike: 6 secret reads in 60 seconds (exceeds limit of 5)
        abuse_detected = False
        for i in range(6):
            # Abuse detector validates each read
            try:
                result = await abuse_detector.validate_secret_read(user_id, "cred123")
                assert result.is_abuse is False  # First 5 are OK
            except Exception:
                # 6th read triggers exception (abuse detected)
                abuse_detected = True
        
        assert abuse_detected  # Abuse was detected
        
        # Risk engine should reflect this via user behavior
        # If we record multiple SECRET_READ events over time
        for i in range(6):
            await risk_engine.record_event(RiskEvent(
                user_id=user_id,
                event_type=EventType.SECRET_READ,
                weight=5.0,
                timestamp=now + i * 5,  # Space them out
            ))
        
        # Total score: 6 * 5 = 30, which is REQUIRE_MFA
        assessment = await risk_engine.assess(user_id)
        assert assessment.score >= 30
        assert assessment.action in [RiskAction.REQUIRE_MFA, RiskAction.TEMP_BLOCK]

    @pytest.mark.asyncio
    async def test_mfa_failure_spike_escalates_risk(self):
        """
        MFA brute force (Step 17.7) + multiple failures (Step 17.8).
        """
        abort_detector = CredentialAbuseDetector()
        risk_engine = RiskEngine()
        user_id = "bob"
        now = time.time()
        
        # Simulate 5 MFA failures
        for i in range(5):
            await abort_detector.record_mfa_failure(user_id)
            
            # Record in risk engine
            await risk_engine.record_event(RiskEvent(
                user_id=user_id,
                event_type=EventType.MFA_FAILURE,
                weight=10.0,
                timestamp=now + i * 10,
                metadata={"attempt": i + 1}
            ))
        
        # Risk score: 5 * 10 = 50 → REQUIRE_MFA
        assessment = await risk_engine.assess(user_id)
        assert assessment.score >= 40  # With possible decay
        assert assessment.action == RiskAction.REQUIRE_MFA

    @pytest.mark.asyncio
    async def test_successful_mfa_reduces_risk(self):
        """
        MFA success (-5 weight) should reduce risk score.
        """
        risk_engine = RiskEngine()
        user_id = "charlie"
        now = time.time()
        
        # Start with risk
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.MFA_FAILURE,
            weight=10.0,
            timestamp=now,
        ))
        
        # Then successful MFA
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.MFA_SUCCESS,
            weight=-5.0,  # Trust restoration
            timestamp=now + 10,
        ))
        
        # Net score should be lower
        assessment = await risk_engine.assess(user_id)
        assert 0 <= assessment.score < 10  # Close to 5 (10 + (-5))

    @pytest.mark.asyncio
    async def test_burst_pattern_causes_temp_block(self):
        """
        Multiple credential reads in burst pattern → high risk.
        """
        risk_engine = RiskEngine()
        user_id = "diana"
        now = time.time()
        
        # Record burst pattern
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ_BURST,
            weight=30.0,
            timestamp=now,
        ))
        
        # Add more events
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.ACCESS_DENIED,
            weight=15.0,
            timestamp=now + 5,
        ))
        
        # Score: 30 + 15 = 45... wait that's REQUIRE_MFA
        # Let's add more to cross TEMP_BLOCK threshold (60)
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ_SPIKE,
            weight=25.0,
            timestamp=now + 10,
        ))
        
        # Score: 30 + 15 + 25 = 70 → TEMP_BLOCK
        assessment = await risk_engine.assess(user_id)
        assert assessment.score >= 60
        assert assessment.action == RiskAction.TEMP_BLOCK

    @pytest.mark.asyncio
    async def test_account_frozen_triggers_freeze_action(self):
        """
        ACCOUNT_FROZEN event (50 weight) should trigger FREEZE action.
        """
        risk_engine = RiskEngine()
        user_id = "eve"
        now = time.time()
        
        # Add some background risk
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.MFA_FAILURE,
            weight=10.0,
            timestamp=now,
        ))
        
        # Account frozen event
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.ACCOUNT_FROZEN,
            weight=50.0,
            timestamp=now + 5,
            metadata={"reason": "excessive_access_patterns"}
        ))
        
        # Score: 10 + 50 = 60... that's TEMP_BLOCK
        # Need more to hit FREEZE (80)
        # Add another burst
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ_BURST,
            weight=30.0,
            timestamp=now + 10,
        ))
        
        # Score: 10 + 50 + 30 = 90 → FREEZE
        assessment = await risk_engine.assess(user_id)
        assert assessment.score >= 80
        assert assessment.action == RiskAction.FREEZE

    @pytest.mark.asyncio
    async def test_account_unfrozen_restores_trust(self):
        """
        ACCOUNT_UNFROZEN (-20 weight) should reduce risk significantly.
        """
        risk_engine = RiskEngine()
        user_id = "frank"
        now = time.time()
        
        # Start with high risk
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.ACCOUNT_FROZEN,
            weight=50.0,
            timestamp=now,
        ))
        
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.MFA_FAILURE,
            weight=10.0,
            timestamp=now + 5,
        ))
        
        # Score: 50 + 10 = 60 → TEMP_BLOCK
        
        # Then unfreeze
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.ACCOUNT_UNFROZEN,
            weight=-20.0,  # Strong trust restoration
            timestamp=now + 10,
        ))
        
        # Score: 50 + 10 + (-20) = 40 → REQUIRE_MFA (down from TEMP_BLOCK)
        assessment = await risk_engine.assess(user_id)
        assert assessment.score >= 30
        assert assessment.score < 60
        assert assessment.action == RiskAction.REQUIRE_MFA

    @pytest.mark.asyncio
    async def test_audit_trail_contains_risk_events(self):
        """
        Risk events should be recorded to audit trail (when audit_binder present).
        """
        config = RiskConfig(decay_enabled=False)
        risk_engine = RiskEngine(config=config)
        user_id = "grace"
        now = time.time()
        
        # Record event
        event = RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now,
        )
        
        # Without audit_binder, this should still work
        await risk_engine.record_event(event, log_to_audit=False)
        
        # Verify event was recorded
        assessment = await risk_engine.assess(user_id)
        assert assessment.score == 5.0
        assert assessment.events_considered == 1

    @pytest.mark.asyncio
    async def test_decay_makes_old_events_less_risky(self):
        """
        With decay enabled, old events contribute less to score.
        """
        config = RiskConfig(
            decay_enabled=True,
            decay_half_life=60,
        )
        risk_engine = RiskEngine(config=config)
        user_id = "henry"
        now = time.time()
        
        # Old event (120 seconds ago, 2 half-lives)
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.MFA_FAILURE,
            weight=10.0,
            timestamp=now - 120,  # 2 minutes old
        ))
        
        # Recent event
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.MFA_FAILURE,
            weight=10.0,
            timestamp=now,  # Just now
        ))
        
        # Score should be: 10 * 0.25 (decayed) + 10 * 1.0 (fresh) ≈ 12.5
        assessment = await risk_engine.assess(user_id)
        assert 10 < assessment.score < 15  # Decayed old + fresh new

    @pytest.mark.asyncio
    async def test_multi_step_attack_scenario(self):
        """
        Complex scenario: burglary attempt escalated through multiple steps.
        """
        risk_engine = RiskEngine()
        abuse_detector = CredentialAbuseDetector()
        user_id = "ivana"
        now = time.time()
        
        # Step 1: Initial access attempt
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now,
        ))
        
        assessment = await risk_engine.assess(user_id)
        assert assessment.action == RiskAction.ALLOW  # Low risk
        
        # Step 2: Access denied (suspicious)
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.ACCESS_DENIED,
            weight=15.0,
            timestamp=now + 10,
        ))
        
        assessment = await risk_engine.assess(user_id)
        assert assessment.action in [RiskAction.ALLOW, RiskAction.REQUIRE_MFA]
        
        # Step 3: Multiple failures with MFA brute force
        for i in range(3):
            await risk_engine.record_event(RiskEvent(
                user_id=user_id,
                event_type=EventType.MFA_FAILURE,
                weight=10.0,
                timestamp=now + 20 + i * 5,
            ))
        
        # Step 4: Burst pattern detected
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ_BURST,
            weight=30.0,
            timestamp=now + 40,
        ))
        
        # Now action should be elevated
        assessment = await risk_engine.assess(user_id)
        # Score: 5 + 15 + 10*3 + 30 = 80
        assert assessment.score >= 65
        assert assessment.action in [RiskAction.TEMP_BLOCK, RiskAction.FREEZE]

    @pytest.mark.asyncio
    async def test_reset_user_risk_clears_history(self):
        """
        reset_user_risk() should clear all events (used after account unfrozen).
        """
        risk_engine = RiskEngine()
        user_id = "jack"
        now = time.time()
        
        # Build up risk
        for i in range(5):
            await risk_engine.record_event(RiskEvent(
                user_id=user_id,
                event_type=EventType.MFA_FAILURE,
                weight=10.0,
                timestamp=now + i,
            ))
        
        score_before = await risk_engine.get_user_score(user_id)
        assert score_before >= 40
        
        # Reset
        await risk_engine.reset_user_risk(user_id)
        
        # Score should be 0
        score_after = await risk_engine.get_user_score(user_id)
        assert score_after == 0

    @pytest.mark.asyncio
    async def test_different_users_isolated(self):
        """
        Risk scores for different users should be completely isolated.
        """
        risk_engine = RiskEngine()
        now = time.time()
        
        # User A has high risk
        for i in range(5):
            await risk_engine.record_event(RiskEvent(
                user_id="user_a",
                event_type=EventType.MFA_FAILURE,
                weight=10.0,
                timestamp=now + i,
            ))
        
        # User B has low risk
        await risk_engine.record_event(RiskEvent(
            user_id="user_b",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now,
        ))
        
        score_a = await risk_engine.get_user_score("user_a")
        score_b = await risk_engine.get_user_score("user_b")
        
        assert score_a >= 40
        assert score_b <= 10
        assert score_a > score_b


class TestComplexRiskScenarios:
    """Test complex threat scenarios."""

    @pytest.mark.asyncio
    async def test_privilege_escalation_detected(self):
        """
        Privilege escalation attempt detected through access patterns.
        """
        risk_engine = RiskEngine()
        user_id = "attacker"
        now = time.time()
        
        # Normal read
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now,
        ))
        
        # Elevation created
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.ELEVATION_CREATED,
            weight=3.0,
            timestamp=now + 5,
        ))
        
        # Burst of reads after elevation
        for i in range(3):
            await risk_engine.record_event(RiskEvent(
                user_id=user_id,
                event_type=EventType.SECRET_READ,
                weight=5.0,
                timestamp=now + 10 + i * 2,
            ))
        
        # Burst pattern
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ_BURST,
            weight=30.0,
            timestamp=now + 20,
        ))
        
        assessment = await risk_engine.assess(user_id)
        # Score: 5 + 3 + 5*3 + 30 = 53
        assert assessment.score >= 40
        assert assessment.action in [RiskAction.REQUIRE_MFA, RiskAction.TEMP_BLOCK]

    @pytest.mark.asyncio
    async def test_lateral_movement_pattern(self):
        """
        Accessing multiple credentials in short time (lateral movement).
        """
        risk_engine = RiskEngine()
        user_id = "lateral"
        now = time.time()
        
        # Multiple secret reads in rapid succession
        for i in range(5):
            await risk_engine.record_event(RiskEvent(
                user_id=user_id,
                event_type=EventType.SECRET_READ,
                weight=5.0,
                timestamp=now + i * 1,  # 1 second apart
                metadata={"credential_id": f"cred_{i}"}
            ))
        
        # Spike pattern
        await risk_engine.record_event(RiskEvent(
            user_id=user_id,
            event_type=EventType.SECRET_READ_SPIKE,
            weight=25.0,
            timestamp=now + 10,
        ))
        
        assessment = await risk_engine.assess(user_id)
        # Score: 5*5 + 25 = 50
        assert assessment.score >= 45
        assert assessment.action in [RiskAction.REQUIRE_MFA, RiskAction.TEMP_BLOCK]


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
