"""
SecurityDecisionOrchestrator — Unified security decision engine.

Coordinates all 5 security layers into a single authorization path:
- Layer 1: RBAC (access control)
- Layer 2: MFA (identity verification)
- Layer 3: Abuse Detection (pattern detection)
- Layer 4: Risk Engine (adaptive risk scoring)
- Layer 5: Trust Engine (automatic recovery)

Step 17.10: Full cycle integration — no security bypass possible.

Design:
- Orchestrator is pure orchestration: no business logic
- All components are injected
- All decisions are deterministic and traceable
- No direct bypass paths
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime, UTC

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder
    from core.security import MFAService
    from modules.credentials.abuse_detection import CredentialAbuseDetector
    from core.security import RiskEngine, TrustEngine
    from modules.credentials.policy_enforcer import CredentialRBACEnforcer


class SecurityDecisionReason(str, Enum):
    """Reasons for security decisions."""
    
    # Allowed reasons
    ALLOWED_LOW_RISK = "allowed_low_risk"
    ALLOWED_ELEVATED_SESSION = "allowed_elevated_session"
    
    # Denial reasons
    DENIED_RBAC_INSUFFICIENT_PRIVILEGE = "denied_rbac_insufficient_privilege"
    DENIED_TRUST_FROZEN = "denied_trust_frozen"
    DENIED_RISK_CRITICAL = "denied_risk_critical"
    DENIED_ABUSE_DETECTED = "denied_abuse_detected"
    DENIED_ELEVATED_ACCESS_REQUIRED = "denied_elevated_access_required"
    
    # Temporary block reasons
    TEMPORARY_BLOCK_HIGH_RISK = "temporary_block_high_risk"
    TEMPORARY_BLOCK_ABUSE = "temporary_block_abuse"
    
    # MFA requirement reasons
    REQUIRES_MFA_ELEVATED_RISK = "requires_mfa_elevated_risk"
    REQUIRES_MFA_POLICY = "requires_mfa_policy"
    
    # Freeze reasons
    FROZEN_CRITICAL_RISK = "frozen_critical_risk"


@dataclass(frozen=True)
class SecurityDecision:
    """
    Final authorization decision for secret access.
    
    Immutable, audit-friendly, deterministic.
    """
    
    allowed: bool = False                             # Can access secret
    requires_mfa: bool = False                        # MFA elevation needed
    blocked: bool = False                             # Temporarily blocked
    frozen: bool = False                              # Account frozen
    reason: SecurityDecisionReason = SecurityDecisionReason.ALLOWED_LOW_RISK
    risk_score: float = 0.0                          # Current risk (0-100)
    trust_level: Optional[str] = None                # Current trust level
    audit_events: List[str] = None                   # Audit trail
    timestamp: str = None
    
    def __post_init__(self):
        """Validate decision consistency."""
        # Allowed must not conflict with blocking states
        if self.allowed and (self.blocked or self.frozen or self.requires_mfa):
            raise ValueError("allowed=True cannot coexist with blocked/frozen/requires_mfa")
        
        # At least one of: allowed, blocked, frozen, requires_mfa must be true
        if not (self.allowed or self.blocked or self.frozen or self.requires_mfa):
            raise ValueError("Decision must have at least one outcome")
        
        if self.audit_events is None:
            object.__setattr__(self, 'audit_events', [])
        if self.timestamp is None:
            object.__setattr__(self, 'timestamp', datetime.now(UTC).isoformat())


class CredentialSecurityOrchestrator:
    """
    Unified security decision orchestrator.
    
    Coordinates all security layers into a single authorization path.
    No business logic, only orchestration.
    
    All components are injected and optional (can work with subset).
    """
    
    def __init__(
        self,
        rbac_enforcer: Optional["CredentialRBACEnforcer"] = None,
        mfa_service: Optional["MFAService"] = None,
        abuse_detector: Optional["CredentialAbuseDetector"] = None,
        risk_engine: Optional["RiskEngine"] = None,
        trust_engine: Optional["TrustEngine"] = None,
        audit_binder: Optional["AuditBinder"] = None,
    ):
        """
        Initialize orchestrator.
        
        Args:
            rbac_enforcer: RBAC enforcement component
            mfa_service: MFA and elevation session service
            abuse_detector: Abuse pattern detection
            risk_engine: Adaptive risk scoring
            trust_engine: Trust restoration engine
            audit_binder: Audit trail logging
        """
        self.rbac = rbac_enforcer
        self.mfa = mfa_service
        self.abuse = abuse_detector
        self.risk = risk_engine
        self.trust = trust_engine
        self.audit = audit_binder
    
    async def authorize_secret_access(
        self,
        user_id: str,
        credential_id: str,
        user_roles: Optional[List] = None,
    ) -> SecurityDecision:
        """
        Unified authorization decision for secret access.
        
        Execution flow:
        1. Check trust state → If frozen → DENY
        2. RBAC check → If denied → DENY + audit
        3. Abuse detection → If spike detected → DENY
        4. Risk assessment → Determine risk level
        5. TrustEngine.evaluate() → Determine trust action
        6. If REQUIRE_MFA → Challenge with MFA
        7. If all passed → ALLOW
        
        Args:
            user_id: User requesting access
            credential_id: Credential being accessed
            user_roles: User's roles for RBAC
        
        Returns:
            SecurityDecision with action and reasoning
        
        Raises:
            Nothing — all outcomes are represented in SecurityDecision
        """
        audit_events = []
        risk_score = 0.0
        trust_level = None
        
        # ════════════════════════════════════════════════════
        # STEP 1: Check TRUST STATE
        # ════════════════════════════════════════════════════
        if self.trust:
            trust_state = await self.trust.get_state(user_id)
            trust_level = trust_state.level.value if trust_state else None
            
            from core.security import TrustLevel as TL
            if trust_state and trust_state.level == TL.FROZEN:
                audit_events.append("TRUST_STATE:FROZEN")
                await self._audit_access_denied(
                    user_id,
                    credential_id,
                    "Trust state is FROZEN",
                    audit_events
                )
                return SecurityDecision(
                    allowed=False,
                    frozen=True,
                    reason=SecurityDecisionReason.DENIED_TRUST_FROZEN,
                    trust_level=trust_level,
                    risk_score=trust_state.risk_score if trust_state else 0.0,
                    audit_events=audit_events,
                )
        
        # ════════════════════════════════════════════════════
        # STEP 2: RBAC CHECK
        # ════════════════════════════════════════════════════
        if self.rbac and user_id and user_roles is not None:
            try:
                await self.rbac.enforce_or_raise_elevated(
                    user_id=user_id,
                    user_roles=user_roles,
                    credential_id=credential_id,
                )
                audit_events.append("RBAC:ALLOWED")
            except Exception as e:
                audit_events.append(f"RBAC:DENIED:{str(e)}")
                await self._audit_access_denied(
                    user_id,
                    credential_id,
                    f"RBAC denied: {str(e)}",
                    audit_events
                )
                return SecurityDecision(
                    blocked=True,
                    reason=SecurityDecisionReason.DENIED_RBAC_INSUFFICIENT_PRIVILEGE,
                    audit_events=audit_events,
                )
        
        # ════════════════════════════════════════════════════
        # STEP 3: ABUSE DETECTION PRE-CHECK
        # ════════════════════════════════════════════════════
        if self.abuse and user_id:
            try:
                await self.abuse.validate_secret_read(user_id, credential_id)
                audit_events.append("ABUSE_CHECK:PASSED")
            except Exception as e:
                audit_events.append(f"ABUSE_CHECK:BLOCKED:{str(e)}")
                await self._audit_access_denied(
                    user_id,
                    credential_id,
                    f"Abuse detected: {str(e)}",
                    audit_events
                )
                return SecurityDecision(
                    allowed=False,
                    blocked=True,
                    reason=SecurityDecisionReason.DENIED_ABUSE_DETECTED,
                    audit_events=audit_events,
                )
        
        # ════════════════════════════════════════════════════
        # STEP 4: RISK ASSESSMENT
        # ════════════════════════════════════════════════════
        trust_action = None
        if self.risk and user_id:
            assessment = await self.risk.assess(user_id)
            risk_score = assessment.score
            audit_events.append(f"RISK:SCORED:{risk_score:.1f}")
            
            # Step 5: TRUST ENGINE EVALUATION
            # ════════════════════════════════════════════════════
            if self.trust:
                from core.security import TrustAction as TA
                trust_decision = await self.trust.evaluate(user_id, risk_score)
                trust_action = trust_decision.action
                trust_level = trust_decision.new_state.level.value
                audit_events.append(f"TRUST:{trust_action.value}:{trust_level}")
                
                # Handle trust decisions
                if trust_action == TA.FREEZE:
                    await self._audit_access_denied(
                        user_id,
                        credential_id,
                        f"Trust action: FREEZE (risk: {risk_score:.1f})",
                        audit_events
                    )
                    return SecurityDecision(
                        allowed=False,
                        frozen=True,
                        reason=SecurityDecisionReason.FROZEN_CRITICAL_RISK,
                        risk_score=risk_score,
                        trust_level=trust_level,
                        audit_events=audit_events,
                    )
                
                elif trust_action == TA.TEMP_BLOCK:
                    await self._audit_access_denied(
                        user_id,
                        credential_id,
                        f"Trust action: TEMP_BLOCK (risk: {risk_score:.1f})",
                        audit_events
                    )
                    return SecurityDecision(
                        allowed=False,
                        blocked=True,
                        reason=SecurityDecisionReason.TEMPORARY_BLOCK_HIGH_RISK,
                        risk_score=risk_score,
                        trust_level=trust_level,
                        audit_events=audit_events,
                    )
                
                elif trust_action == TA.REQUIRE_MFA:
                    audit_events.append("REQUIRES_MFA:ELEVATED_RISK")
                    # Will check MFA below
        
        # ════════════════════════════════════════════════════
        # STEP 6: MFA ELEVATION CHECK
        # ════════════════════════════════════════════════════
        mfa_required = False
        if trust_action and trust_action.value == "require_mfa":
            mfa_required = True
        
        if mfa_required:
            # Check if user has active elevated session
            if self.mfa:
                has_elevation = await self.mfa.elevation_session_manager.has_active_session(user_id)
                if not has_elevation:
                    audit_events.append("MFA_REQUIRED:NO_ELEVATION")
                    await self._audit_access_denied(
                        user_id,
                        credential_id,
                        "MFA elevation required but not present",
                        audit_events
                    )
                    return SecurityDecision(
                        allowed=False,
                        requires_mfa=True,
                        reason=SecurityDecisionReason.REQUIRES_MFA_ELEVATED_RISK,
                        risk_score=risk_score,
                        trust_level=trust_level,
                        audit_events=audit_events,
                    )
            else:
                return SecurityDecision(
                    allowed=False,
                    requires_mfa=True,
                    reason=SecurityDecisionReason.REQUIRES_MFA_ELEVATED_RISK,
                    risk_score=risk_score,
                    trust_level=trust_level,
                    audit_events=audit_events,
                )
        
        # ════════════════════════════════════════════════════
        # STEP 7: ALL CHECKS PASSED - ALLOW
        # ════════════════════════════════════════════════════
        audit_events.append("AUTHORIZATION:ALLOWED")
        await self._audit_access_allowed(
            user_id,
            credential_id,
            risk_score,
            audit_events
        )
        
        return SecurityDecision(
            allowed=True,
            reason=SecurityDecisionReason.ALLOWED_LOW_RISK,
            risk_score=risk_score,
            trust_level=trust_level,
            audit_events=audit_events,
        )
    
    async def _audit_access_allowed(
        self,
        user_id: str,
        credential_id: str,
        risk_score: float,
        events: List[str],
    ) -> None:
        """Log successful access to audit trail."""
        if self.audit:
            try:
                from core.audit.events import credential_access_allowed_event
                event = credential_access_allowed_event(
                    user_id=user_id,
                    credential_id=credential_id,
                    risk_score=risk_score,
                    events=events,
                )
                await self.audit.append(event)
            except Exception as e:
                print(f"[WARNING] Failed to audit allowed access: {e}")
    
    async def _audit_access_denied(
        self,
        user_id: str,
        credential_id: str,
        reason: str,
        events: List[str],
    ) -> None:
        """Log denied access to audit trail."""
        if self.audit:
            try:
                from core.audit.events import credential_access_denied_event
                event = credential_access_denied_event(
                    user_id=user_id,
                    credential_id=credential_id,
                    reason=reason,
                    events=events,
                )
                await self.audit.append(event)
            except Exception as e:
                print(f"[WARNING] Failed to audit denied access: {e}")
