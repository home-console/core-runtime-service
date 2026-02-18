"""
Credential RBAC Enforcer

Enforcement layer that evaluates and enforces access decisions.
Raises CredentialAccessDenied on policy violation.
Binds to audit system for tamper-evident violation logging.
"""

from typing import Optional, TYPE_CHECKING

from core.security.rbac_models import Role, CredentialAccessLevel
from core.security.policy_engine import CredentialPolicyEngine
from core.credentials.errors import CredentialAccessDenied

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder


class CredentialRBACEnforcer:
    """
    RBAC enforcement layer for credential operations.
    
    Evaluates policies and enforces access decisions.
    Raises on denial, returns on allow.
    
    All access violations logged through audit binding to P0 storage.
    """
    
    def __init__(
        self,
        policy_engine: CredentialPolicyEngine,
        audit_binder: Optional["AuditBinder"] = None,
    ):
        self.policy_engine = policy_engine
        self.audit_binder = audit_binder
    
    async def enforce_or_raise(
        self,
        user_id: str,
        user_roles: list[Role],
        credential_id: str,
        access_level: CredentialAccessLevel,
        audit_callback=None,  # Optional: legacy callback support
    ) -> None:
        """
        Enforce access policy with tamper-evident audit logging.
        
        Raises CredentialAccessDenied if access denied.
        Logs denial to P0 storage via AuditBinder (if available).
        
        Args:
            user_id: User identifier
            user_roles: User's roles
            credential_id: Credential being accessed
            access_level: Type of access being requested
            audit_callback: Optional async callback for legacy audit logging
        
        Raises:
            CredentialAccessDenied: If policy denies access
        """
        
        # Evaluate access decision
        decision = await self.policy_engine.evaluate(
            user_id=user_id,
            user_roles=user_roles,
            credential_id=credential_id,
            access_level=access_level,
        )
        
        # If denied, audit and raise
        if not decision.allowed:
            # Log to P0 protected audit storage (Step 17.5)
            if self.audit_binder:
                from core.audit.events import credential_access_denied_event
                
                event = credential_access_denied_event(
                    user_id=user_id,
                    credential_id=credential_id,
                    reason=decision.reason,
                    access_level=access_level.value,
                    required_roles=decision.required_roles,
                )
                try:
                    await self.audit_binder.append(event)
                except Exception as audit_err:
                    # Log but don't fail the request if audit fails
                    # (audit failures are handled separately)
                    print(f"[WARNING] Failed to append audit event: {audit_err}")
            
            # Optional legacy callback
            if audit_callback:
                await audit_callback(
                    user_id=user_id,
                    credential_id=credential_id,
                    access_level=access_level,
                    denied_reason=decision.reason,
                )
            
            # Raise denial
            raise CredentialAccessDenied(
                user_id=user_id,
                credential_id=credential_id,
                access_level=access_level.value,
                reason=decision.reason,
            )
    
    async def is_allowed(
        self,
        user_id: str,
        user_roles: list[Role],
        credential_id: str,
        access_level: CredentialAccessLevel,
    ) -> bool:
        """
        Check if access is allowed (convenience method).
        
        Returns bool, does not raise.
        """
        try:
            await self.enforce_or_raise(
                user_id=user_id,
                user_roles=user_roles,
                credential_id=credential_id,
                access_level=access_level,
            )
            return True
        except CredentialAccessDenied:
            return False
    
    async def enforce_or_raise_elevated(
        self,
        user_id: str,
        user_roles: list[Role],
        credential_id: str,
        mfa_verified: bool = False,
    ) -> None:
        """
        Enforce elevated access (READ_SECRET).
        
        Future: Can require MFA verification.
        
        Raises:
            CredentialAccessDenied: If access denied or MFA not verified
        """
        
        # Evaluate for secret read
        await self.enforce_or_raise(
            user_id=user_id,
            user_roles=user_roles,
            credential_id=credential_id,
            access_level=CredentialAccessLevel.READ_SECRET,
        )
        
        # Future: MFA gate
        # if requires_mfa and not mfa_verified:
        #     raise CredentialAccessDenied(
        #         user_id=user_id,
        #         credential_id=credential_id,
        #         access_level=CredentialAccessLevel.READ_SECRET.value,
        #         reason="MFA verification required for secret access"
        #     )
