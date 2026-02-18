"""
CredentialAbuseDetector — Behavioral anomaly detection for vault self-defense.

Detects and blocks suspicious access patterns:
- Secret read frequency spikes
- Burst/reconnaissance patterns
- MFA brute force attempts
- User behavior anomalies

Storage: In-memory only (runtime telemetry, not persistent).
Integration: RBAC + MFA + Audit (seamless, non-invasive).
Safety: Async-safe, auto-cleanup, no memory leaks.

Design principle: Stop abuse before it happens.
"""

from typing import Dict, Optional, List, TYPE_CHECKING
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import time
import asyncio

from core.credentials.errors import CredentialAccessDenied

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder


class AbuseAction(Enum):
    """Response action for detected abuse."""
    NONE = "none"  # No action
    SOFT_BLOCK = "soft_block"  # Warn, monitor
    HARD_BLOCK = "hard_block"  # Deny access temporarily
    FORCE_LOGOUT = "force_logout"  # Revoke all sessions
    FREEZE_USER = "freeze_user"  # Freeze account (manual intervention needed)


class AbuseReason(Enum):
    """Root cause of abuse detection."""
    SECRET_READ_SPIKE = "secret_read_spike"
    BURST_PATTERN = "burst_pattern"
    MFA_BRUTE_FORCE = "mfa_brute_force"
    UNKNOWN = "unknown"


@dataclass
class AbuseDetectionResult:
    """Result of abuse validation."""
    is_abuse: bool
    reason: AbuseReason = AbuseReason.UNKNOWN
    action: AbuseAction = AbuseAction.NONE
    message: str = ""
    threshold_value: float = 0.0


class CredentialAccessAbuseDetected(CredentialAccessDenied):
    """Abuse detection exception (user behavior anomaly)."""
    
    def __init__(
        self,
        user_id: str,
        reason: AbuseReason = AbuseReason.UNKNOWN,
        message: str = "",
    ):
        super().__init__(
            user_id=user_id,
            credential_id="",
            access_level="secret_read",
            reason=f"abuse_detected: {reason.value}",
        )
        # Override reason field to store enum (after super().__init__)
        self.reason = reason
        if message:
            self.args = (message,)


@dataclass
class _TimestampedAccess:
    """Internal: Track single credential access."""
    timestamp: float
    credential_id: str
    action: str = "secret_read"


class CredentialAbuseDetector:
    """
    Behavioral anomaly detector for vault self-defense.
    
    Policies:
    1. Secret read rate limiting (per user)
    2. Credential burst detection (reconnaissance pattern)
    3. MFA failure rate limiting (brute force prevention)
    4. User account freezing (containment)
    
    Storage: In-memory only (deque + dict, async-safe).
    Cleanup: Background task (30-second interval).
    """
    
    # Configurable thresholds
    MAX_SECRET_READS_PER_MINUTE = 5
    SECRET_READ_WINDOW_SECONDS = 60
    
    BURST_CREDENTIALS_THRESHOLD = 3
    BURST_WINDOW_SECONDS = 10
    
    MAX_MFA_FAILURES = 5
    MFA_FAILURE_WINDOW_SECONDS = 300
    MFA_LOCKOUT_SECONDS = 300  # 5 minutes
    
    def __init__(self, audit_binder: Optional["AuditBinder"] = None):
        """
        Initialize abuse detector.
        
        Args:
            audit_binder: Optional AuditBinder for tamper-evident logging
        """
        self.audit_binder = audit_binder
        
        # Secret read tracking: user_id → deque of timestamps
        self._secret_reads: Dict[str, deque] = {}
        
        # Burst pattern tracking: user_id → deque of (timestamp, credential_id)
        self._credential_accesses: Dict[str, deque] = {}
        
        # MFA failure tracking: user_id → deque of timestamps
        self._mfa_failures: Dict[str, deque] = {}
        
        # MFA lockout: user_id → (locked_until_timestamp, retry_count)
        self._mfa_lockouts: Dict[str, tuple[float, int]] = {}
        
        # Account freezing: user_id → frozen_until_timestamp
        self._frozen_users: Dict[str, float] = {}
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """Start background cleanup task."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self) -> None:
        """Stop background cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def validate_secret_read(
        self,
        user_id: str,
        credential_id: str,
    ) -> AbuseDetectionResult:
        """
        Validate credential secret read (called before get_with_secret).
        
        Checks:
        1. User not frozen
        2. Secret read rate not exceeded
        3. No burst/reconnaissance pattern
        
        Args:
            user_id: User identifier
            credential_id: Credential being accessed
        
        Returns:
            AbuseDetectionResult with action if abuse detected
        
        Raises:
            CredentialAccessAbuseDetected: If abuse detected and action=HARD_BLOCK
        """
        async with self._lock:
            # Check if user frozen
            if await self._is_user_frozen(user_id):
                result = AbuseDetectionResult(
                    is_abuse=True,
                    reason=AbuseReason.UNKNOWN,
                    action=AbuseAction.HARD_BLOCK,
                    message=f"User {user_id} is frozen due to prior abuse",
                )
                raise CredentialAccessAbuseDetected(
                    user_id=user_id,
                    reason=result.reason,
                    message=result.message,
                )
            
            now = time.time()
            
            # Record this access
            if user_id not in self._credential_accesses:
                self._credential_accesses[user_id] = deque()
            
            self._credential_accesses[user_id].append((now, credential_id))
            
            # Check secret read frequency
            freq_result = await self._check_secret_read_frequency(user_id, now)
            if freq_result.is_abuse and freq_result.action == AbuseAction.HARD_BLOCK:
                await self._log_abuse_event(user_id, credential_id, freq_result)
                raise CredentialAccessAbuseDetected(
                    user_id=user_id,
                    reason=freq_result.reason,
                    message=freq_result.message,
                )
            
            # Check burst pattern
            burst_result = await self._check_burst_pattern(user_id, now)
            if burst_result.is_abuse and burst_result.action == AbuseAction.HARD_BLOCK:
                await self._log_abuse_event(user_id, credential_id, burst_result)
                raise CredentialAccessAbuseDetected(
                    user_id=user_id,
                    reason=burst_result.reason,
                    message=burst_result.message,
                )
            
            return AbuseDetectionResult(is_abuse=False)
    
    async def record_mfa_failure(self, user_id: str) -> None:
        """Record MFA verification failure."""
        async with self._lock:
            now = time.time()
            
            if user_id not in self._mfa_failures:
                self._mfa_failures[user_id] = deque()
            
            self._mfa_failures[user_id].append(now)
            
            # Check if threshold reached
            failure_count = await self._count_mfa_failures_in_window(user_id, now)
            
            if failure_count >= self.MAX_MFA_FAILURES:
                # Lock user account
                lockout_until = now + self.MFA_LOCKOUT_SECONDS
                self._mfa_lockouts[user_id] = (lockout_until, failure_count)
    
    async def reset_mfa_failures(self, user_id: str) -> None:
        """Reset MFA failure counter on successful verification."""
        async with self._lock:
            if user_id in self._mfa_failures:
                self._mfa_failures[user_id].clear()
            if user_id in self._mfa_lockouts:
                del self._mfa_lockouts[user_id]
    
    async def validate_mfa_available(self, user_id: str) -> None:
        """
        Check if MFA is available for user.
        
        Raises:
            CredentialAccessAbuseDetected: If user is MFA locked
        """
        async with self._lock:
            if user_id in self._mfa_lockouts:
                locked_until, retry_count = self._mfa_lockouts[user_id]
                if time.time() < locked_until:
                    remaining = int(locked_until - time.time())
                    raise CredentialAccessAbuseDetected(
                        user_id=user_id,
                        reason=AbuseReason.MFA_BRUTE_FORCE,
                        message=f"MFA locked for {remaining} more seconds",
                    )
                else:
                    # Lock expired
                    del self._mfa_lockouts[user_id]
    
    async def freeze_user(
        self,
        user_id: str,
        duration_seconds: int = 3600,  # 1 hour default
        reason: str = "Abuse detected",
    ) -> None:
        """
        Freeze user account (requires manual intervention to unfreeze).
        
        Args:
            user_id: User to freeze
            duration_seconds: Freeze duration (default 1 hour)
            reason: Reason for freeze
        """
        async with self._lock:
            frozen_until = time.time() + duration_seconds
            self._frozen_users[user_id] = frozen_until
            
            # Log freeze event
            if self.audit_binder:
                from core.audit.events import credential_user_frozen_event
                event = credential_user_frozen_event(
                    user_id=user_id,
                    reason=reason,
                    frozen_until=datetime.fromtimestamp(frozen_until).isoformat(),
                )
                try:
                    await self.audit_binder.append(event)
                except Exception as e:
                    print(f"[WARNING] Failed to audit user freeze: {e}")
    
    async def unfreeze_user(self, user_id: str) -> None:
        """Unfreeze user account (manual intervention)."""
        async with self._lock:
            if user_id in self._frozen_users:
                del self._frozen_users[user_id]
    
    # ─────────────────────────────────────────────────────────────
    # Private: Policy checks
    # ─────────────────────────────────────────────────────────────
    
    async def _check_secret_read_frequency(
        self,
        user_id: str,
        now: float,
    ) -> AbuseDetectionResult:
        """Check if secret read rate exceeds threshold."""
        if user_id not in self._secret_reads:
            self._secret_reads[user_id] = deque()
        
        # Add timestamp
        self._secret_reads[user_id].append(now)
        
        # Remove old entries outside window
        window_start = now - self.SECRET_READ_WINDOW_SECONDS
        while self._secret_reads[user_id] and self._secret_reads[user_id][0] < window_start:
            self._secret_reads[user_id].popleft()
        
        # Check count
        count = len(self._secret_reads[user_id])
        
        if count > self.MAX_SECRET_READS_PER_MINUTE:
            return AbuseDetectionResult(
                is_abuse=True,
                reason=AbuseReason.SECRET_READ_SPIKE,
                action=AbuseAction.HARD_BLOCK,
                message=f"{count} secret reads in {self.SECRET_READ_WINDOW_SECONDS}s (max {self.MAX_SECRET_READS_PER_MINUTE})",
                threshold_value=float(count),
            )
        
        return AbuseDetectionResult(is_abuse=False)
    
    async def _check_burst_pattern(
        self,
        user_id: str,
        now: float,
    ) -> AbuseDetectionResult:
        """Detect credential burst (reconnaissance pattern)."""
        if user_id not in self._credential_accesses:
            return AbuseDetectionResult(is_abuse=False)
        
        # Remove old entries
        window_start = now - self.BURST_WINDOW_SECONDS
        while self._credential_accesses[user_id] and self._credential_accesses[user_id][0][0] < window_start:
            self._credential_accesses[user_id].popleft()
        
        # Count unique credentials
        unique_creds = set(cred_id for _, cred_id in self._credential_accesses[user_id])
        unique_count = len(unique_creds)
        
        if unique_count >= self.BURST_CREDENTIALS_THRESHOLD:
            return AbuseDetectionResult(
                is_abuse=True,
                reason=AbuseReason.BURST_PATTERN,
                action=AbuseAction.HARD_BLOCK,
                message=f"{unique_count} unique credentials in {self.BURST_WINDOW_SECONDS}s (reconnaissance pattern)",
                threshold_value=float(unique_count),
            )
        
        return AbuseDetectionResult(is_abuse=False)
    
    async def _count_mfa_failures_in_window(
        self,
        user_id: str,
        now: float,
    ) -> int:
        """Count MFA failures in time window."""
        if user_id not in self._mfa_failures:
            return 0
        
        # Remove old
        window_start = now - self.MFA_FAILURE_WINDOW_SECONDS
        while self._mfa_failures[user_id] and self._mfa_failures[user_id][0] < window_start:
            self._mfa_failures[user_id].popleft()
        
        return len(self._mfa_failures[user_id])
    
    async def _is_user_frozen(self, user_id: str) -> bool:
        """Check if user is frozen (locked)."""
        if user_id not in self._frozen_users:
            return False
        
        frozen_until = self._frozen_users[user_id]
        if time.time() < frozen_until:
            return True
        else:
            # Freeze expired
            del self._frozen_users[user_id]
            return False
    
    async def _log_abuse_event(
        self,
        user_id: str,
        credential_id: str,
        result: AbuseDetectionResult,
    ) -> None:
        """Log abuse detection event."""
        if not self.audit_binder:
            return
        
        from core.audit.events import credential_abuse_detected_event
        
        event = credential_abuse_detected_event(
            user_id=user_id,
            credential_id=credential_id,
            reason=result.reason.value,
            action=result.action.value,
            threshold_value=result.threshold_value,
        )
        
        try:
            await self.audit_binder.append(event)
        except Exception as e:
            print(f"[WARNING] Failed to audit abuse event: {e}")
    
    # ─────────────────────────────────────────────────────────────
    # Background: Cleanup task
    # ─────────────────────────────────────────────────────────────
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup task (30s interval)."""
        while self._running:
            try:
                await asyncio.sleep(30)
                async with self._lock:
                    await self._cleanup_expired_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR] Cleanup loop failed: {e}")
    
    async def _cleanup_expired_data(self) -> None:
        """Remove expired entries from all tracking structures."""
        now = time.time()
        
        # Cleanup frozen users
        expired_users = [
            uid for uid, until in self._frozen_users.items()
            if now > until
        ]
        for uid in expired_users:
            del self._frozen_users[uid]
        
        # Cleanup MFA lockouts
        expired_lockouts = [
            uid for uid, (until, _) in self._mfa_lockouts.items()
            if now > until
        ]
        for uid in expired_lockouts:
            del self._mfa_lockouts[uid]
        
        # Cleanup old timestamps in all deques
        window_start = now - max(
            self.SECRET_READ_WINDOW_SECONDS,
            self.BURST_WINDOW_SECONDS,
            self.MFA_FAILURE_WINDOW_SECONDS,
        )
        
        for user_id in list(self._secret_reads.keys()):
            while self._secret_reads[user_id] and self._secret_reads[user_id][0] < window_start:
                self._secret_reads[user_id].popleft()
            if not self._secret_reads[user_id]:
                del self._secret_reads[user_id]
        
        for user_id in list(self._credential_accesses.keys()):
            while self._credential_accesses[user_id] and self._credential_accesses[user_id][0][0] < window_start:
                self._credential_accesses[user_id].popleft()
            if not self._credential_accesses[user_id]:
                del self._credential_accesses[user_id]
        
        for user_id in list(self._mfa_failures.keys()):
            while self._mfa_failures[user_id] and self._mfa_failures[user_id][0] < window_start:
                self._mfa_failures[user_id].popleft()
            if not self._mfa_failures[user_id]:
                del self._mfa_failures[user_id]
    
    # ─────────────────────────────────────────────────────────────
    # Monitoring
    # ─────────────────────────────────────────────────────────────
    
    async def stats(self) -> dict:
        """Get detector statistics (for monitoring)."""
        async with self._lock:
            return {
                "users_with_secret_reads": len(self._secret_reads),
                "users_being_monitored": len(self._credential_accesses),
                "mfa_locked_users": len(self._mfa_lockouts),
                "frozen_users": len(self._frozen_users),
            }
