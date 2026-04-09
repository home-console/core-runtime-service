"""
Test suite for SecurityDecisionOrchestrator (flow).

Covers unified authorization decision engine coordinating all 5 security layers:
- Layer 1: RBAC enforcement
- Layer 2: MFA elevation
- Layer 3: Abuse detection
- Layer 4: Risk scoring
- Layer 5: Trust restoration

Tests verify no bypass paths and deterministic decisions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from modules.credentials.security_orchestrator import (
    CredentialSecurityOrchestrator,
    SecurityDecision,
    SecurityDecisionReason,
)
from modules.security.trust.trust_state import TrustLevel, TrustAction


class TestSecurityDecisionModel:
    """SecurityDecision immutable model."""
    
    def test_decision_creation_allowed(self):
        """Create allowed decision."""
        decision = SecurityDecision(
            allowed=True,
            reason=SecurityDecisionReason.ALLOWED_LOW_RISK,
            risk_score=10.0,
        )
        assert decision.allowed is True
        assert decision.requires_mfa is False
        assert decision.blocked is False
        assert decision.frozen is False
    
    def test_decision_creation_mfa_required(self):
        """Create MFA-required decision."""
        decision = SecurityDecision(
            allowed=False,
            requires_mfa=True,
            reason=SecurityDecisionReason.REQUIRES_MFA_ELEVATED_RISK,
            risk_score=50.0,
        )
        assert decision.allowed is False
        assert decision.requires_mfa is True
    
    def test_decision_creation_blocked(self):
        """Create temporarily blocked decision."""
        decision = SecurityDecision(
            allowed=False,
            blocked=True,
            reason=SecurityDecisionReason.TEMPORARY_BLOCK_HIGH_RISK,
            risk_score=75.0,
        )
        assert decision.allowed is False
        assert decision.blocked is True
    
    def test_decision_creation_frozen(self):
        """Create frozen account decision."""
        decision = SecurityDecision(
            allowed=False,
            frozen=True,
            reason=SecurityDecisionReason.FROZEN_CRITICAL_RISK,
            risk_score=90.0,
        )
        assert decision.allowed is False
        assert decision.frozen is True
    
    def test_decision_immutability(self):
        """Decision is immutable after creation."""
        decision = SecurityDecision(allowed=True)
        with pytest.raises((AttributeError, TypeError)):
            decision.allowed = False
    
    def test_decision_conflict_allowed_and_mfa(self):
        """Cannot have allowed=True and requires_mfa=True."""
        with pytest.raises(ValueError):
            SecurityDecision(
                allowed=True,
                requires_mfa=True,
            )
    
    def test_decision_conflict_allowed_and_blocked(self):
        """Cannot have allowed=True and blocked=True."""
        with pytest.raises(ValueError):
            SecurityDecision(
                allowed=True,
                blocked=True,
            )
    
    def test_decision_must_have_outcome(self):
        """Decision must have at least one outcome."""
        with pytest.raises(ValueError):
            SecurityDecision(
                allowed=False,
                requires_mfa=False,
                blocked=False,
                frozen=False,
            )


class TestOrchestratorFrozenCheck:
    """Test frozen account detection (Layer 5 check)."""
    
    @pytest.mark.asyncio
    async def test_frozen_user_denied(self):
        """Frozen user is denied access regardless of other factors."""
        orchestrator = CredentialSecurityOrchestrator()
        
        # Mock trust engine that returns frozen state
        trust_state = MagicMock()
        trust_state.level = TrustLevel.FROZEN
        trust_state.risk_score = 0.0
        
        trust_engine = AsyncMock()
        trust_engine.get_state = AsyncMock(return_value=trust_state)
        orchestrator.trust = trust_engine
        
        decision = await orchestrator.authorize_secret_access(
            user_id="frozen_user",
            credential_id="cred123",
        )
        
        assert decision.frozen is True
        assert decision.allowed is False
        assert decision.reason == SecurityDecisionReason.DENIED_TRUST_FROZEN


class TestOrchestratorRBACCheck:
    """Test RBAC enforcement (Layer 1 check)."""
    
    @pytest.mark.asyncio
    async def test_rbac_approved(self):
        """RBAC approved allows to proceed."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()  # Success
        orchestrator.rbac = rbac
        
        # Will stop at abuse check (not mocked), but we know RBAC passed
        orchestrator.abuse = AsyncMock()
        orchestrator.abuse.validate_secret_read = AsyncMock()  # Success
        
        # Audit mock
        orchestrator.audit = AsyncMock()
        orchestrator.audit.append = AsyncMock()
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user123",
            credential_id="cred456",
            user_roles=[],
        )
        
        # Should pass RBAC check
        rbac.enforce_or_raise_elevated.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_rbac_denied(self):
        """RBAC denied stops authorization."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock(
            side_effect=Exception("Insufficient privilege")
        )
        orchestrator.rbac = rbac
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user123",
            credential_id="cred456",
            user_roles=[],
        )
        
        assert decision.allowed is False
        assert decision.reason == SecurityDecisionReason.DENIED_RBAC_INSUFFICIENT_PRIVILEGE


class TestOrchestratorAbuseDetection:
    """Test abuse detection (Layer 3 check)."""
    
    @pytest.mark.asyncio
    async def test_abuse_detected_blocks(self):
        """Abuse detection blocks access."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock(
            side_effect=Exception("Abuse pattern detected")
        )
        orchestrator.abuse = abuse
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="abusive_user",
            credential_id="cred789",
            user_roles=[],
        )
        
        assert decision.allowed is False
        assert decision.blocked is True
        assert decision.reason == SecurityDecisionReason.DENIED_ABUSE_DETECTED


class TestOrchestratorRiskAndTrust:
    """Test risk assessment + trust engine coordination (Layers 4-5)."""
    
    @pytest.mark.asyncio
    async def test_low_risk_allows(self):
        """Low risk score allows access."""
        orchestrator = CredentialSecurityOrchestrator()
        
        # Mock all layers to pass
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 10.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision_state = MagicMock()
        trust_decision_state.level = TrustLevel.NORMAL
        trust_decision.action = TrustAction.ALLOW
        trust_decision.new_state = trust_decision_state
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user123",
            credential_id="cred123",
            user_roles=[],
        )
        
        assert decision.allowed is True
        assert decision.reason == SecurityDecisionReason.ALLOWED_LOW_RISK
        assert decision.risk_score == 10.0
    
    @pytest.mark.asyncio
    async def test_high_risk_triggers_freeze(self):
        """High risk (>= 80) triggers account freeze."""
        orchestrator = CredentialSecurityOrchestrator()
        
        # Mock layers to pass until risk/trust
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 90.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision_state = MagicMock()
        trust_decision_state.level = TrustLevel.FROZEN
        trust_decision_state.risk_score = 90.0
        trust_decision.action = TrustAction.FREEZE
        trust_decision.new_state = trust_decision_state
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user456",
            credential_id="cred456",
            user_roles=[],
        )
        
        assert decision.allowed is False
        assert decision.frozen is True
        assert decision.reason == SecurityDecisionReason.FROZEN_CRITICAL_RISK
    
    @pytest.mark.asyncio
    async def test_medium_risk_triggers_mfa(self):
        """Medium risk triggers MFA requirement."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 50.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision_state = MagicMock()
        trust_decision_state.level = TrustLevel.ELEVATED_RISK
        trust_decision_state.risk_score = 50.0
        trust_decision.action = TrustAction.REQUIRE_MFA
        trust_decision.new_state = trust_decision_state
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        mfa = AsyncMock()
        elevation_manager = AsyncMock()
        elevation_manager.has_active_session = AsyncMock(return_value=False)
        mfa.elevation_session_manager = elevation_manager
        orchestrator.mfa = mfa
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user789",
            credential_id="cred789",
            user_roles=[],
        )
        
        assert decision.allowed is False
        assert decision.requires_mfa is True
        assert decision.reason == SecurityDecisionReason.REQUIRES_MFA_ELEVATED_RISK


class TestOrchestratorMFAElevation:
    """Test MFA elevation session validation."""
    
    @pytest.mark.asyncio
    async def test_mfa_elevation_required_no_session(self):
        """MFA required but no active elevation session → denied."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 50.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision.action = TrustAction.REQUIRE_MFA
        trust_decision.new_state = MagicMock(level=TrustLevel.ELEVATED_RISK, risk_score=50.0)
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        mfa = AsyncMock()
        elevation_manager = AsyncMock()
        elevation_manager.has_active_session = AsyncMock(return_value=False)
        mfa.elevation_session_manager = elevation_manager
        orchestrator.mfa = mfa
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user_no_elevation",
            credential_id="cred123",
            user_roles=[],
        )
        
        assert decision.requires_mfa is True
        assert decision.allowed is False
    
    @pytest.mark.asyncio
    async def test_mfa_elevation_present_allows(self):
        """MFA required but elevation session active → allowed."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 50.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision.action = TrustAction.REQUIRE_MFA
        trust_decision.new_state = MagicMock(level=TrustLevel.ELEVATED_RISK, risk_score=50.0)
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        mfa = AsyncMock()
        elevation_manager = AsyncMock()
        elevation_manager.has_active_session = AsyncMock(return_value=True)  # Has elevation
        mfa.elevation_session_manager = elevation_manager
        orchestrator.mfa = mfa
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="user_with_elevation",
            credential_id="cred456",
            user_roles=[],
        )
        
        # Should proceed past MFA check, reach ALLOW
        assert decision.allowed is True


class TestOrchestratorAuditIntegration:
    """Test audit logging of decisions."""
    
    @pytest.mark.asyncio
    async def test_audit_allowed_access(self):
        """Successful access is logged."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 10.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision.action = TrustAction.ALLOW
        trust_decision.new_state = MagicMock(level=TrustLevel.NORMAL, risk_score=10.0)
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="audit_user",
            credential_id="audit_cred",
            user_roles=[],
        )
        
        # Verify audit was called
        assert audit.append.called
    
    @pytest.mark.asyncio
    async def test_audit_denied_access(self):
        """Failed access is logged."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock(
            side_effect=Exception("Denied")
        )
        orchestrator.rbac = rbac
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="denied_user",
            credential_id="denied_cred",
            user_roles=[],
        )
        
        assert not decision.allowed
        assert audit.append.called


class TestOrchestratorConcurrency:
    """Test concurrent authorization requests."""
    
    @pytest.mark.asyncio
    async def test_concurrent_different_users(self):
        """Multiple users can be authorized concurrently."""
        import asyncio
        
        orchestrator = CredentialSecurityOrchestrator()
        
        # Setup mocks
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 10.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision.action = TrustAction.ALLOW
        trust_decision.new_state = MagicMock(level=TrustLevel.NORMAL, risk_score=10.0)
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        # Concurrent requests
        decisions = await asyncio.gather(
            orchestrator.authorize_secret_access("user1", "cred1", []),
            orchestrator.authorize_secret_access("user2", "cred2", []),
            orchestrator.authorize_secret_access("user3", "cred3", []),
        )
        
        # All should succeed
        assert all(d.allowed for d in decisions)
        assert len(decisions) == 3


class TestOrchestratorEventTracking:
    """Test audit event generation."""
    
    @pytest.mark.asyncio
    async def test_events_in_decision(self):
        """Security decision includes audit events."""
        orchestrator = CredentialSecurityOrchestrator()
        
        rbac = AsyncMock()
        rbac.enforce_or_raise_elevated = AsyncMock()
        orchestrator.rbac = rbac
        
        abuse = AsyncMock()
        abuse.validate_secret_read = AsyncMock()
        orchestrator.abuse = abuse
        
        risk = AsyncMock()
        assessment = MagicMock()
        assessment.score = 10.0
        risk.assess = AsyncMock(return_value=assessment)
        orchestrator.risk = risk
        
        trust = AsyncMock()
        trust_decision = MagicMock()
        trust_decision.action = TrustAction.ALLOW
        trust_decision.new_state = MagicMock(level=TrustLevel.NORMAL, risk_score=10.0)
        trust.evaluate = AsyncMock(return_value=trust_decision)
        trust.get_state = AsyncMock(return_value=None)
        orchestrator.trust = trust
        
        audit = AsyncMock()
        audit.append = AsyncMock()
        orchestrator.audit = audit
        
        decision = await orchestrator.authorize_secret_access(
            user_id="event_user",
            credential_id="event_cred",
            user_roles=[],
        )
        
        # Decision should have audit events
        assert decision.audit_events is not None
        assert len(decision.audit_events) > 0
        assert "AUTHORIZATION:ALLOWED" in decision.audit_events


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
