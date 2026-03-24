"""
MFAService — Orchestrates MFA verification, session creation, and audit logging.

Responsibilities:
1. Verify MFA proof (TOTP code, WebAuthn response, etc.)
2. Create elevation session on success
3. Emit audit events (MFA_FAILED, MFA_ELEVATED)
4. Handle rate limiting
5. No direct HTTP logic
"""

from typing import Optional, TYPE_CHECKING
import time

from core.security.mfa.methods import MFAMethod, TOTPMethod
from core.security.mfa.elevation_session import ElevationSessionManager
from core.security.mfa.exceptions import (
    MFARequired,
    MFAFailed,
    MFANotConfigured,
    RateLimitExceeded,
)

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder
    from core.security.secret_store import SecretStore
    from modules.credentials.abuse_detection import CredentialAbuseDetector


class MFAService:
    """
    MFA orchestration service.
    
    Coordinates MFA methods, elevation sessions, and audit logging.
    
    No HTTP coupling — works with pure data structures.
    """
    
    def __init__(
        self,
        secret_store: "SecretStore",
        audit_binder: Optional["AuditBinder"] = None,
        elevation_session_manager: Optional[ElevationSessionManager] = None,
        abuse_detector: Optional["CredentialAbuseDetector"] = None,
        elevation_ttl_seconds: int = 90,
        max_failed_attempts: int = 5,
        lockout_seconds: int = 300,
    ):
        """
        Initialize MFA service.
        
        Args:
            secret_store: SecretStore for retrieving MFA secrets
            audit_binder: Optional AuditBinder for tamper-evident logging
            elevation_session_manager: Optional pre-initialized manager (for testing)
            abuse_detector: Optional CredentialAbuseDetector for self-defense (Step 17.7)
            elevation_ttl_seconds: Session TTL in seconds (default 90)
            max_failed_attempts: Max failed attempts before lockout (default 5)
            lockout_seconds: Lockout duration (default 300s = 5 minutes)
        """
        self.secret_store = secret_store
        self.audit_binder = audit_binder
        self.elevation_session_manager = (
            elevation_session_manager or ElevationSessionManager()
        )
        self.abuse_detector = abuse_detector
        self.elevation_ttl_seconds = elevation_ttl_seconds
        self.max_failed_attempts = max_failed_attempts
        self.lockout_seconds = lockout_seconds
        
        # Rate limiting (user_id → (attempt_count, last_attempt_time, lockout_until))
        self._rate_limit_state: dict[str, tuple[int, float, float]] = {}
        
        # Supported MFA methods
        self._methods: dict[str, MFAMethod] = {
            "totp": TOTPMethod(),
            # Future: "webauthn": WebAuthnMethod(), etc.
        }
    
    async def start(self) -> None:
        """Start background cleanup tasks."""
        await self.elevation_session_manager.start_cleanup()
    
    async def stop(self) -> None:
        """Stop background cleanup tasks."""
        await self.elevation_session_manager.stop_cleanup()
    
    async def verify_and_elevate(
        self,
        user_id: str,
        mfa_method: str,
        proof: dict,
        credential_id: str = "",
    ) -> dict:
        """
        Verify MFA proof and create elevation session on success.
        
        Args:
            user_id: User identifier
            mfa_method: Method to use (e.g., "totp")
            proof: Method-specific proof (e.g., {"code": "123456"})
            credential_id: Credential being accessed (for audit)
        
        Returns:
            {
                "success": bool,
                "elevation_token": str (if success),
                "reason": str (if failed),
                "remaining_seconds": int (if success),
            }
        
        Raises:
            RateLimitExceeded: If user has too many failed attempts
            MFANotConfigured: If MFA method not configured for user
            CredentialAccessAbuseDetected: If abuse behavior detected (Step 17.7)
        """
        # Abuse detection: check if MFA is available (not locked)
        if self.abuse_detector:
            try:
                await self.abuse_detector.validate_mfa_available(user_id)
            except Exception as e:
                # Record failure for abuse detector
                await self.abuse_detector.record_mfa_failure(user_id)
                if self.audit_binder:
                    from core.audit.events import credential_mfa_failed_event
                    event = credential_mfa_failed_event(
                        user_id=user_id,
                        credential_id=credential_id,
                        reason="mfa_locked_abuse_detection",
                        mfa_method=mfa_method,
                    )
                    await self.audit_binder.append(event)
                raise
        
        # Check rate limiting
        await self._check_rate_limit(user_id)
        
        # Get MFA method
        method = self._methods.get(mfa_method)
        if not method:
            # Record failure
            if self.abuse_detector:
                await self.abuse_detector.record_mfa_failure(user_id)
            return {
                "success": False,
                "reason": f"mfa_method_not_supported: {mfa_method}",
            }
        
        # Check if MFA is configured
        is_configured = await method.is_configured(user_id, self.secret_store)
        if not is_configured:
            # Record failure
            if self.abuse_detector:
                await self.abuse_detector.record_mfa_failure(user_id)
            
            # Log missing configuration
            if self.audit_binder:
                from core.audit.events import (
                    credential_mfa_failed_event,
                )
                event = credential_mfa_failed_event(
                    user_id=user_id,
                    credential_id=credential_id,
                    reason="mfa_not_configured",
                    mfa_method=mfa_method,
                )
                await self.audit_binder.append(event)
            
            return {
                "success": False,
                "reason": "mfa_not_configured",
            }
        
        # Verify proof
        result = await method.verify(user_id, proof, self.secret_store)
        
        if not result.success:
            # Record failed attempt (local + abuse detector)
            await self._record_failed_attempt(user_id)
            if self.abuse_detector:
                await self.abuse_detector.record_mfa_failure(user_id)
            
            # Log failure
            if self.audit_binder:
                from core.audit.events import (
                    credential_mfa_failed_event,
                )
                event = credential_mfa_failed_event(
                    user_id=user_id,
                    credential_id=credential_id,
                    reason=result.reason or "verification_failed",
                    mfa_method=mfa_method,
                )
                await self.audit_binder.append(event)
            
            return {
                "success": False,
                "reason": result.reason,
            }
        
        # Success! Create elevation session
        session = await self.elevation_session_manager.create_session(
            user_id=user_id,
            elevation_level="secret_read",
            mfa_method_used=mfa_method,
            ttl_seconds=self.elevation_ttl_seconds,
        )
        
        # Clear rate limit state on success
        if user_id in self._rate_limit_state:
            del self._rate_limit_state[user_id]
        
        # Reset abuse detector failures on success
        if self.abuse_detector:
            await self.abuse_detector.reset_mfa_failures(user_id)
        
        # Log elevation
        if self.audit_binder:
            from core.audit.events import (
                credential_mfa_elevated_event,
            )
            event = credential_mfa_elevated_event(
                user_id=user_id,
                credential_id=credential_id,
                mfa_method=mfa_method,
                elevation_level="secret_read",
                ttl_seconds=self.elevation_ttl_seconds,
            )
            await self.audit_binder.append(event)
        
        return {
            "success": True,
            "elevation_level": "secret_read",
            "remaining_seconds": int(session.remaining_seconds),
        }
    
    async def validate_elevation(
        self,
        user_id: str,
        elevation_level: str = "secret_read",
    ) -> bool:
        """
        Check if user has valid elevation session for requested level.
        
        Returns:
            True if valid session exists and not expired
        """
        return await self.elevation_session_manager.validate_session(
            user_id,
            elevation_level,
        )
    
    async def revoke_elevation(
        self,
        user_id: str,
        elevation_level: str = None,
    ) -> bool:
        """
        Manually revoke elevation session (e.g., on logout or privilege change).
        """
        return await self.elevation_session_manager.revoke_session(
            user_id,
            elevation_level,
        )
    
    async def _check_rate_limit(self, user_id: str) -> None:
        """
        Check if user is rate limited.
        
        Raises:
            RateLimitExceeded: If user has too many failed attempts
        """
        now = time.time()
        
        if user_id in self._rate_limit_state:
            attempts, last_attempt, lockout_until = self._rate_limit_state[user_id]
            
            # Check if still in lockout period
            if lockout_until > now:
                remaining = int(lockout_until - now)
                raise RateLimitExceeded(user_id, remaining)
            
            # Check if attempt window expired (reset counter)
            if now - last_attempt > 60:  # 60-second window
                del self._rate_limit_state[user_id]
    
    async def _record_failed_attempt(self, user_id: str) -> None:
        """Record failed MFA attempt and lock if needed."""
        now = time.time()
        
        if user_id not in self._rate_limit_state:
            self._rate_limit_state[user_id] = (1, now, 0)
        else:
            attempts, last_attempt, lockout_until = self._rate_limit_state[user_id]
            attempts += 1
            
            # Check for lockout
            if attempts >= self.max_failed_attempts:
                lockout_until = now + self.lockout_seconds
            
            self._rate_limit_state[user_id] = (attempts, now, lockout_until)
    
    async def get_elevation_session(self, user_id: str):
        """Get current elevation session for user (for testing/debugging)."""
        return await self.elevation_session_manager.get_session(
            user_id, "secret_read"
        )
    
    async def stats(self) -> dict:
        """Get MFA service statistics."""
        return {
            "elevation_sessions": await self.elevation_session_manager.stats(),
            "rate_limited_users": len(self._rate_limit_state),
        }
