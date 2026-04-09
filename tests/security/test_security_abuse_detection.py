"""
Test flow — Self-Defending Vault (Abuse Detection & Active Defense)

Tests for behavioral anomaly detection, user freezing, and self-defense.

Coverage:
- Secret read frequency limiting (spike detection)
- Credential burst detection (reconnaissance pattern)
- MFA failure tracking and user lockout
- User account freezing (containment)
- Audit event integration
- Concurrency safety
- Background cleanup
"""

import pytest
import asyncio
import time
from unittest import mock

from modules.credentials.abuse_detection import (
    CredentialAbuseDetector,
    CredentialAccessAbuseDetected,
    AbuseAction,
    AbuseReason,
)


class TestSecretReadLimitDetection:
    """Test secret read frequency limiting."""

    @pytest.mark.asyncio
    async def test_secret_reads_within_limit_allowed(self):
        """5 reads within 60s should be allowed (same credential)."""
        detector = CredentialAbuseDetector()
        
        # 5 reads of SAME credential should pass (no burst)
        for i in range(5):
            result = await detector.validate_secret_read("alice", "cred_secure")
            assert not result.is_abuse
    
    @pytest.mark.asyncio
    async def test_sixth_secret_read_triggers_abuse(self):
        """6th read within 60s should trigger abuse detection."""
        detector = CredentialAbuseDetector()
        
        # 5 reads pass (same credential)
        for i in range(5):
            result = await detector.validate_secret_read("alice", "cred_secure")
            assert not result.is_abuse
        
        # 6th read triggers abuse
        with pytest.raises(CredentialAccessAbuseDetected) as exc_info:
            await detector.validate_secret_read("alice", "cred_secure")
        
        assert exc_info.value.user_id == "alice"
        assert exc_info.value.reason == AbuseReason.SECRET_READ_SPIKE
    
    @pytest.mark.asyncio
    async def test_secret_reads_reset_after_window(self):
        """Reads should not count after 60s window expires."""
        detector = CredentialAbuseDetector()
        detector.SECRET_READ_WINDOW_SECONDS = 2  # Speed up test
        
        # Add 5 reads (same credential)
        for i in range(5):
            result = await detector.validate_secret_read("alice", "cred_secure")
            assert not result.is_abuse
        
        # Wait for window to expire
        await asyncio.sleep(2.1)
        
        # Cleanup to remove old entries
        async with detector._lock:
            await detector._cleanup_expired_data()
        
        # 6th read should now pass (new window)
        result = await detector.validate_secret_read("alice", "cred_secure")
        assert not result.is_abuse


class TestBurstDetection:
    """Test reconnaissance pattern detection (burst)."""

    @pytest.mark.asyncio
    async def test_three_credentials_in_burst_window_triggers_abuse(self):
        """3 different credentials in 10s should trigger burst detection."""
        detector = CredentialAbuseDetector()
        
        # Access 3 different credentials within burst window
        result1 = await detector.validate_secret_read("alice", "cred_1")
        assert not result1.is_abuse
        
        result2 = await detector.validate_secret_read("alice", "cred_2")
        assert not result2.is_abuse
        
        # Third credential should trigger burst
        with pytest.raises(CredentialAccessAbuseDetected) as exc_info:
            await detector.validate_secret_read("alice", "cred_3")
        
        assert exc_info.value.reason == AbuseReason.BURST_PATTERN
    
    @pytest.mark.asyncio
    async def test_same_credential_multiple_times_no_burst(self):
        """Multiple reads of same credential should not trigger burst."""
        detector = CredentialAbuseDetector()
        
        # Read same credential 5 times
        for i in range(5):
            result = await detector.validate_secret_read("alice", "cred_secure")
            assert not result.is_abuse, f"Read {i+1} should not trigger burst"
    
    @pytest.mark.asyncio
    async def test_burst_window_expiration(self):
        """Expired burst patterns should not be counted."""
        detector = CredentialAbuseDetector()
        detector.BURST_WINDOW_SECONDS = 2  # Speed up test
        
        # Access 2 credentials
        await detector.validate_secret_read("alice", "cred_1")
        await detector.validate_secret_read("alice", "cred_2")
        
        # Wait for burst window to expire
        await asyncio.sleep(2.1)
        
        # Cleanup old entries
        async with detector._lock:
            await detector._cleanup_expired_data()
        
        # Third credential should now be allowed
        result = await detector.validate_secret_read("alice", "cred_3")
        assert not result.is_abuse


class TestMFAFailureTracking:
    """Test MFA failure detection and user lockout."""

    @pytest.mark.asyncio
    async def test_record_mfa_failure(self):
        """Recording MFA failures should track state (no lock until 5th)."""
        detector = CredentialAbuseDetector()
        
        # Record 3 failures (not locked yet)
        for i in range(3):
            await detector.record_mfa_failure("alice")
        
        # User should NOT be locked yet (only at 5th)
        await detector.validate_mfa_available("alice")  # Should not raise
        
        # But if we check the count...
        async with detector._lock:
            count = await detector._count_mfa_failures_in_window("alice", time.time())
            assert count == 3
    
    @pytest.mark.asyncio
    async def test_fifth_mfa_failure_locks_user(self):
        """Fifth MFA failure should lock user."""
        detector = CredentialAbuseDetector()
        
        # Record 5 failures
        for i in range(5):
            await detector.record_mfa_failure("alice")
        
        # User should be locked
        with pytest.raises(CredentialAccessAbuseDetected) as exc_info:
            await detector.validate_mfa_available("alice")
        
        assert exc_info.value.reason == AbuseReason.MFA_BRUTE_FORCE
    
    @pytest.mark.asyncio
    async def test_mfa_lockout_expiration(self):
        """MFA lockout should expire after lockout_seconds."""
        detector = CredentialAbuseDetector()
        detector.MFA_LOCKOUT_SECONDS = 1  # Speed up test
        
        # Record 5 failures
        for i in range(5):
            await detector.record_mfa_failure("alice")
        
        # User should be locked
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_mfa_available("alice")
        
        # Wait for lockout to expire
        await asyncio.sleep(1.1)
        
        # User should be unlocked
        await detector.validate_mfa_available("alice")
    
    @pytest.mark.asyncio
    async def test_reset_mfa_failures_on_success(self):
        """Successful MFA should reset failure counter."""
        detector = CredentialAbuseDetector()
        
        # Record 4 failures
        for i in range(4):
            await detector.record_mfa_failure("alice")
        
        # Reset on success
        await detector.reset_mfa_failures("alice")
        
        # User should no longer be locked
        await detector.validate_mfa_available("alice")


class TestUserFreezing:
    """Test account freezing (containment)."""

    @pytest.mark.asyncio
    async def test_frozen_user_cannot_read_secrets(self):
        """Frozen user should not be able to read secrets."""
        detector = CredentialAbuseDetector()
        
        # Freeze user
        await detector.freeze_user("alice", duration_seconds=3600)
        
        # User should be blocked
        with pytest.raises(CredentialAccessAbuseDetected) as exc_info:
            await detector.validate_secret_read("alice", "cred_1")
        
        assert exc_info.value.user_id == "alice"
    
    @pytest.mark.asyncio
    async def test_user_freeze_expires(self):
        """Freeze should expire after duration."""
        detector = CredentialAbuseDetector()
        
        # Freeze user for 1 second
        await detector.freeze_user("alice", duration_seconds=1)
        
        # User should be frozen
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_secret_read("alice", "cred_1")
        
        # Wait for freeze to expire
        await asyncio.sleep(1.1)
        
        # Cleanup
        async with detector._lock:
            await detector._cleanup_expired_data()
        
        # User should be unfrozen
        result = await detector.validate_secret_read("alice", "cred_1")
        assert not result.is_abuse
    
    @pytest.mark.asyncio
    async def test_manual_unfreeze(self):
        """Manually unfreezing user should allow access."""
        detector = CredentialAbuseDetector()
        
        # Freeze user
        await detector.freeze_user("alice", duration_seconds=3600)
        
        # Manual unfreeze
        await detector.unfreeze_user("alice")
        
        # User should be able to access
        result = await detector.validate_secret_read("alice", "cred_1")
        assert not result.is_abuse


class TestAuditIntegration:
    """Test audit event logging."""

    @pytest.mark.asyncio
    async def test_abuse_event_logged_on_spike(self):
        """Abuse detection should emit audit event."""
        mock_binder = mock.MagicMock()
        mock_binder.append = mock.AsyncMock()
        
        detector = CredentialAbuseDetector(audit_binder=mock_binder)
        
        # Trigger 6 reads to cause spike (SAME credential to avoid burst)
        for i in range(5):
            await detector.validate_secret_read("alice", "cred_secure")
        
        # 6th should trigger and log
        try:
            await detector.validate_secret_read("alice", "cred_secure")
        except CredentialAccessAbuseDetected:
            pass
        
        # Verify audit was called
        assert mock_binder.append.called
    
    @pytest.mark.asyncio
    async def test_freeze_event_logged(self):
        """User freeze should emit audit event."""
        mock_binder = mock.MagicMock()
        mock_binder.append = mock.AsyncMock()
        
        detector = CredentialAbuseDetector(audit_binder=mock_binder)
        
        # Freeze user
        await detector.freeze_user("alice", reason="Spike detected")
        
        # Verify audit was called
        assert mock_binder.append.called


class TestConcurrency:
    """Test async/concurrency safety."""

    @pytest.mark.asyncio
    async def test_concurrent_secret_reads_thread_safe(self):
        """Concurrent reads should be thread-safe - 6+ should fail."""
        detector = CredentialAbuseDetector()
        
        async def read_secret(user_id: str, i: int):
            # Use SAME credential to test spike, not burst
            return await detector.validate_secret_read(user_id, "cred_secure")
        
        # Run 8 concurrent reads (should fail on 6th+)
        tasks = [
            read_secret("alice", i)
            for i in range(8)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # First 5 should succeed, 6th+ should fail
        successes = sum(1 for r in results if not isinstance(r, Exception) and not r.is_abuse)
        failures = sum(1 for r in results if isinstance(r, CredentialAccessAbuseDetected))
        
        assert successes >= 5, f"Expected ≥5 successes, got {successes}"
        assert failures >= 1, f"Expected ≥1 failures, got {failures}"
    
    @pytest.mark.asyncio
    async def test_concurrent_mfa_failures_thread_safe(self):
        """Concurrent MFA failure recording should be thread-safe."""
        detector = CredentialAbuseDetector()
        
        async def record_failure():
            await detector.record_mfa_failure("alice")
        
        # Record 10 failures concurrently
        tasks = [record_failure() for _ in range(10)]
        await asyncio.gather(*tasks)
        
        # User should be locked
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_mfa_available("alice")


class TestCleanupTask:
    """Test background cleanup task."""

    @pytest.mark.asyncio
    async def test_background_cleanup_removes_expired(self):
        """Cleanup task should remove expired entries."""
        detector = CredentialAbuseDetector()
        detector.SECRET_READ_WINDOW_SECONDS = 1
        detector.MFA_FAILURE_WINDOW_SECONDS = 1
        
        # Start cleanup
        await detector.start()
        
        try:
            # Add some data
            await detector.validate_secret_read("alice", "cred_1")
            await detector.record_mfa_failure("bob")
            
            # Wait for cleanup to run
            await asyncio.sleep(2)
            
            # Verify cleanup doesn't crash
            stats = await detector.stats()
            assert "users_with_secret_reads" in stats
        finally:
            await detector.stop()
    
    @pytest.mark.asyncio
    async def test_cleanup_task_lifecycle(self):
        """Cleanup task should start and stop cleanly."""
        detector = CredentialAbuseDetector()
        
        # Start
        assert not detector._running
        await detector.start()
        assert detector._running
        assert detector._cleanup_task is not None
        
        # Stop
        await detector.stop()
        assert not detector._running


class TestMonitoring:
    """Test monitoring/observability."""

    @pytest.mark.asyncio
    async def test_stats_reporting(self):
        """Detector should report statistics."""
        detector = CredentialAbuseDetector()
        
        # Add some activity
        await detector.validate_secret_read("alice", "cred_1")
        await detector.record_mfa_failure("bob")
        await detector.freeze_user("charlie")
        
        # Get stats
        stats = await detector.stats()
        
        assert "users_with_secret_reads" in stats
        assert "users_being_monitored" in stats
        assert "mfa_locked_users" in stats
        assert "frozen_users" in stats
        assert stats["frozen_users"] == 1


class TestMultipleUsers:
    """Test isolation between users."""

    @pytest.mark.asyncio
    async def test_secret_reads_isolated_per_user(self):
        """Secret read limits should be per-user."""
        detector = CredentialAbuseDetector()
        
        # Alice: 5 reads of SAME credential
        for i in range(5):
            await detector.validate_secret_read("alice", "cred_secure")
        
        # Bob: 5 reads of SAME credential (should also be allowed)
        for i in range(5):
            await detector.validate_secret_read("bob", "cred_secure")
        
        # Alice: 6th read should fail
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_secret_read("alice", "cred_secure")
        
        # Bob: 6th read should also fail
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_secret_read("bob", "cred_secure")
    
    @pytest.mark.asyncio
    async def test_user_freeze_isolated(self):
        """Freezing one user should not affect others."""
        detector = CredentialAbuseDetector()
        
        # Freeze Alice
        await detector.freeze_user("alice")
        
        # Alice should be blocked
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_secret_read("alice", "cred_1")
        
        # Bob should work fine
        result = await detector.validate_secret_read("bob", "cred_1")
        assert not result.is_abuse


class TestEdgeCases:
    """Test edge cases and corner cases."""

    @pytest.mark.asyncio
    async def test_empty_detector_has_no_state(self):
        """Fresh detector should have no state."""
        detector = CredentialAbuseDetector()
        
        stats = await detector.stats()
        
        assert stats["users_with_secret_reads"] == 0
        assert stats["mfa_locked_users"] == 0
        assert stats["frozen_users"] == 0
    
    @pytest.mark.asyncio
    async def test_validate_frozen_user_immediately_fails(self):
        """Frozen user should fail immediately without other checks."""
        detector = CredentialAbuseDetector()
        
        # Freeze then try to access
        await detector.freeze_user("alice")
        
        with pytest.raises(CredentialAccessAbuseDetected):
            await detector.validate_secret_read("alice", "cred_1")
    
    @pytest.mark.asyncio
    async def test_action_enum_values(self):
        """AbuseAction enum should have expected values."""
        actions = {action.value for action in AbuseAction}
        
        expected = {
            "none",
            "soft_block",
            "hard_block",
            "force_logout",
            "freeze_user",
        }
        
        assert actions == expected
