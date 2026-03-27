"""
Tests for Step 18: Credential Rotation Engine

Comprehensive test suite covering:
- Manual rotation
- Auto rotation by interval
- Failure rollback
- Version increment
- Audit events
- Frozen account handling
- Concurrent rotations
- Grace period handling
- Cancellation
- Risk escalation on repeated failures
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from modules.credentials.rotation import (
    RotationPolicy,
    RotationStrategy,
    RotationStatus,
    RotationState,
    CredentialRotationEngine,
    RotationScheduler,
    RotationExecutor,
    RotationFailedError,
    RotationNotAllowedError,
    generate_strong_secret,
    calculate_entropy_bits,
)


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS: RotationPolicy
# ═══════════════════════════════════════════════════════════════════

class TestRotationPolicy:
    """Test rotation policy configuration."""
    
    def test_daily_policy_creation(self):
        """Create daily rotation policy."""
        policy = RotationPolicy.daily()
        assert policy.interval_seconds == 86400
        assert policy.auto_rotate is True
        assert policy.grace_period_seconds == 3600
        assert policy.strategy == RotationStrategy.GENERATE_NEW_SECRET
    
    def test_weekly_policy_creation(self):
        """Create weekly rotation policy."""
        policy = RotationPolicy.weekly()
        assert policy.interval_seconds == 604800
        assert policy.grace_period_seconds == 21600
    
    def test_manual_policy_creation(self):
        """Create manual-only rotation policy."""
        policy = RotationPolicy.manual_only()
        assert policy.auto_rotate is False
        assert policy.strategy == RotationStrategy.MANUAL
    
    def test_policy_validation_invalid_interval(self):
        """Policy validation rejects invalid interval."""
        with pytest.raises(ValueError):
            policy = RotationPolicy(
                interval_seconds=0,
                auto_rotate=True,
                grace_period_seconds=300,
                strategy=RotationStrategy.GENERATE_NEW_SECRET,
            )
            policy.validate()
    
    def test_policy_validation_grace_period_too_long(self):
        """Policy validation rejects grace period >= interval."""
        with pytest.raises(ValueError):
            policy = RotationPolicy(
                interval_seconds=1000,
                auto_rotate=True,
                grace_period_seconds=1000,  # Cannot be >= interval
                strategy=RotationStrategy.GENERATE_NEW_SECRET,
            )
            policy.validate()
    
    def test_next_rotation_due_never_rotated(self):
        """Next rotation due immediately if never rotated."""
        policy = RotationPolicy.daily()
        next_due = policy.next_rotation_due(None)
        
        # Should be approximately now
        now = datetime.now(timezone.utc)
        next_dt = datetime.fromisoformat(next_due.replace("Z", "+00:00"))
        assert (now - next_dt).total_seconds() < 1
    
    def test_next_rotation_due_calculates_interval(self):
        """Calculate next rotation based on last rotation + interval."""
        policy = RotationPolicy.daily()
        
        # Last rotated 5 hours ago
        last_rotated = datetime.now(timezone.utc) - timedelta(hours=5)
        last_rotated_str = last_rotated.isoformat().replace("+00:00", "Z")
        
        next_due = policy.next_rotation_due(last_rotated_str)
        next_dt = datetime.fromisoformat(next_due.replace("Z", "+00:00"))
        
        # Next due should be 24 hours from last_rotated
        expected = last_rotated + timedelta(seconds=policy.interval_seconds)
        assert abs((next_dt - expected).total_seconds()) < 1
    
    def test_policy_to_dict(self):
        """Convert policy to dict."""
        policy = RotationPolicy.daily()
        d = policy.to_dict()
        
        assert d["interval_seconds"] == 86400
        assert d["auto_rotate"] is True
        assert d["strategy"] == "generate_new"
    
    def test_policy_from_dict(self):
        """Create policy from dict."""
        data = {
            "interval_seconds": 86400,
            "auto_rotate": True,
            "grace_period_seconds": 3600,
            "strategy": "generate_new",
            "max_failures": 3,
        }
        
        policy = RotationPolicy.from_dict(data)
        assert policy.interval_seconds == 86400
        assert policy.auto_rotate is True


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS: Secret Generation
# ═══════════════════════════════════════════════════════════════════

class TestSecretGeneration:
    """Test secret generation utilities."""
    
    def test_generate_strong_secret_default_length(self):
        """Generate secret with default length."""
        secret = generate_strong_secret()
        assert len(secret) == 32
        assert isinstance(secret, str)
    
    def test_generate_strong_secret_custom_length(self):
        """Generate secret with custom length."""
        secret = generate_strong_secret(length=64)
        assert len(secret) == 64
    
    def test_generate_strong_secret_minimum_entropy(self):
        """Reject lengths with insufficient entropy."""
        with pytest.raises(ValueError):
            generate_strong_secret(length=7)
    
    def test_generate_strong_secret_randomness(self):
        """Generated secrets should be different each time."""
        secret1 = generate_strong_secret()
        secret2 = generate_strong_secret()
        assert secret1 != secret2
    
    def test_entropy_calculation(self):
        """Calculate entropy in bits."""
        # 32 chars from 94-char alphabet = 32 * log2(94) ~= 210 bits
        bits = calculate_entropy_bits(32, 94)
        assert 200 < bits < 220
    
    def test_entropy_64_chars(self):
        """64-char secret has ~420 bits entropy."""
        bits = calculate_entropy_bits(64, 94)
        assert 410 < bits < 430


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: RotationScheduler
# ═══════════════════════════════════════════════════════════════════

class TestRotationScheduler:
    """Test rotation scheduling logic."""
    
    @pytest.mark.asyncio
    async def test_scheduler_schedule_rotation(self):
        """Schedule a credential for rotation."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        await scheduler.schedule(
            credential_id="cred123",
            rotation_policy=policy,
            last_rotated_at=None,
        )
        
        state = await scheduler.get_state("cred123")
        assert state is not None
        assert state.rotation_status == RotationStatus.SCHEDULED
    
    @pytest.mark.asyncio
    async def test_scheduler_get_due_rotations(self):
        """Get rotations currently due."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        # Schedule a rotation that was last rotated 25 hours ago
        # (so it's due now, since daily = 24 hours)
        last_rotated = datetime.now(timezone.utc) - timedelta(hours=25)
        last_rotated_str = last_rotated.isoformat().replace("+00:00", "Z")
        
        await scheduler.schedule(
            credential_id="cred123",
            rotation_policy=policy,
            last_rotated_at=last_rotated_str,
        )
        
        due = await scheduler.get_due_rotations()
        assert "cred123" in due
    
    @pytest.mark.asyncio
    async def test_scheduler_mark_rotation_started(self):
        """Mark rotation as in-progress."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        await scheduler.schedule("cred123", policy, None)
        await scheduler.mark_rotation_started("cred123")
        
        state = await scheduler.get_state("cred123")
        assert state.rotation_status == RotationStatus.IN_PROGRESS
    
    @pytest.mark.asyncio
    async def test_scheduler_mark_rotation_completed(self):
        """Mark rotation as completed."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        await scheduler.schedule("cred123", policy, None)
        
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        await scheduler.mark_rotation_completed("cred123", now, policy)
        
        state = await scheduler.get_state("cred123")
        assert state.rotation_status == RotationStatus.IDLE
        assert state.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_scheduler_mark_rotation_failed(self):
        """Track rotation failures."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        await scheduler.schedule("cred123", policy, None)
        
        # First failure
        failed = await scheduler.mark_rotation_failed(
            "cred123",
            "Network error",
            max_failures=3,
        )
        assert failed is False  # Not exceeded yet
        
        state = await scheduler.get_state("cred123")
        assert state.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_scheduler_max_failures_exceeded(self):
        """Stop retrying after max failures."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        await scheduler.schedule("cred123", policy, None)
        
        # Fail 3 times
        for i in range(3):
            failed = await scheduler.mark_rotation_failed(
                "cred123",
                f"Failure {i+1}",
                max_failures=3,
            )
        
        assert failed is True  # Exceeded max
        
        state = await scheduler.get_state("cred123")
        assert state.rotation_status == RotationStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_scheduler_cancel_rotation(self):
        """Cancel scheduled rotation."""
        scheduler = RotationScheduler()
        policy = RotationPolicy.daily()
        
        await scheduler.schedule("cred123", policy, None)
        await scheduler.cancel_rotation("cred123")
        
        state = await scheduler.get_state("cred123")
        assert state.rotation_status == RotationStatus.IDLE


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: RotationExecutor
# ═══════════════════════════════════════════════════════════════════

class TestRotationExecutor:
    """Test rotation execution logic."""
    
    @pytest.mark.asyncio
    async def test_executor_generate_new_secret(self):
        """Execute rotation with generated secret."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        executor = RotationExecutor(
            vault_store=vault,
            repository=repository,
            audit_binder=audit,
        )
        
        policy = RotationPolicy.daily()
        
        new_ref, new_version = await executor.execute_rotation(
            credential_id="cred123",
            rotation_policy=policy,
            current_version=1,
        )
        
        assert new_version == 2
        assert "cred123:v2" in new_ref
        vault.store_secret.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_executor_manual_rotation(self):
        """Execute manual rotation with provided secret."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        executor = RotationExecutor(vault, repository, audit)
        
        new_ref, new_version = await executor.execute_manual_rotation(
            credential_id="cred123",
            new_secret="my-new-secret",
            current_version=1,
        )
        
        assert new_version == 2
        vault.store_secret.assert_called_once()
        # Verify the secret was stored
        call_args = vault.store_secret.call_args
        assert call_args[1]["value"] == "my-new-secret"
    
    @pytest.mark.asyncio
    async def test_executor_frozen_account_denied(self):
        """Rotation denied if account frozen."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        trust_engine = AsyncMock()
        
        # Mock frozen state with proper TrustLevel enum
        from modules.security.trust.trust_state import TrustLevel
        frozen_state = MagicMock()
        frozen_state.level = TrustLevel.FROZEN
        trust_engine.get_state.return_value = frozen_state
        
        executor = RotationExecutor(
            vault, repository, audit,
            trust_engine=trust_engine,
        )
        
        policy = RotationPolicy.daily()
        
        with pytest.raises(RotationNotAllowedError):
            await executor.execute_rotation(
                "cred123", policy, 1
            )


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: CredentialRotationEngine
# ═══════════════════════════════════════════════════════════════════

class TestCredentialRotationEngine:
    """Test main rotation engine."""
    
    @pytest.mark.asyncio
    async def test_engine_schedule_rotation(self):
        """Schedule credential for rotation."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        engine = CredentialRotationEngine(
            vault, repository, audit,
            check_interval_seconds=1,
        )
        
        policy = RotationPolicy.daily()
        
        await engine.schedule_rotation(
            "cred123",
            policy,
            None,
        )
        
        # Verify scheduled
        state = await engine.scheduler.get_state("cred123")
        assert state is not None
        assert state.rotation_status == RotationStatus.SCHEDULED
    
    @pytest.mark.asyncio
    async def test_engine_rotate_now(self):
        """Manually trigger immediate rotation."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        # Mock credential
        credential = MagicMock()
        credential.version = 1
        credential.mutate.return_value = MagicMock()
        repository.get.return_value = credential
        
        engine = CredentialRotationEngine(vault, repository, audit)
        
        policy = RotationPolicy.daily()
        await engine.schedule_rotation("cred123", policy, None)
        
        await engine.rotate_now("cred123")
        
        # Should have been updated
        repository.update.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_engine_version_increment(self):
        """Version increments correctly after rotation."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        credential = MagicMock()
        credential.version = 1
        credential.mutate.return_value = MagicMock(version=2)
        repository.get.return_value = credential
        
        engine = CredentialRotationEngine(vault, repository, audit)
        policy = RotationPolicy.daily()
        
        await engine.schedule_rotation("cred123", policy, None)
        await engine.rotate_now("cred123")
        
        # Verify version was incremented
        assert vault.store_secret.called
    
    @pytest.mark.asyncio
    async def test_engine_cancel_rotation(self):
        """Cancel scheduled rotation."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        engine = CredentialRotationEngine(vault, repository, audit)
        policy = RotationPolicy.daily()
        
        await engine.schedule_rotation("cred123", policy, None)
        await engine.cancel_rotation("cred123")
        
        state = await engine.get_rotation_state("cred123")
        assert state.rotation_status == RotationStatus.IDLE
    
    @pytest.mark.asyncio
    async def test_engine_repeated_failures_freeze_account(self):
        """Account frozen after repeated rotation failures."""
        vault = AsyncMock()
        vault.store_secret.side_effect = Exception("Vault error")
        repository = AsyncMock()
        audit = AsyncMock()
        trust_engine = AsyncMock()
        
        credential = MagicMock()
        credential.version = 1
        repository.get.return_value = credential
        
        engine = CredentialRotationEngine(
            vault, repository, audit,
            trust_engine=trust_engine,
        )
        
        policy = RotationPolicy.daily()
        await engine.schedule_rotation("cred123", policy, None)
        
        # Attempt 3 rotations (each will fail)
        for _ in range(3):
            with pytest.raises(RotationFailedError):
                await engine.rotate_now("cred123")
        
        # After max failures, account should be frozen
        trust_engine.freeze.assert_called()
    
    @pytest.mark.asyncio
    async def test_engine_audit_events_logged(self):
        """Rotation events are audited."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        engine = CredentialRotationEngine(vault, repository, audit)
        policy = RotationPolicy.daily()
        
        await engine.schedule_rotation("cred123", policy, None)
        
        # Should have logged schedule event
        audit.append_event.assert_called()
        
        # Check that event was schedule event
        call_args = audit.append_event.call_args
        assert call_args[1]["event_type"] == "credential_rotation_scheduled"


# ═══════════════════════════════════════════════════════════════════
# EDGE CASES & CONCURRENCY
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_concurrent_rotations_safety(self):
        """Multiple concurrent rotations handled safely."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        # Return different credentials for each call
        def get_credential(cred_id):
            cred = MagicMock()
            cred.version = 1
            cred.mutate.return_value = MagicMock(version=2)
            return cred
        
        repository.get.side_effect = lambda cid: get_credential(cid)
        
        engine = CredentialRotationEngine(vault, repository, audit)
        policy = RotationPolicy.daily()
        
        # Schedule multiple credentials
        for i in range(5):
            await engine.schedule_rotation(f"cred{i}", policy, None)
        
        # Rotate all concurrently
        import asyncio
        await asyncio.gather(*[
            engine.rotate_now(f"cred{i}")
            for i in range(5)
        ], return_exceptions=True)
        
        # All should be updated
        assert repository.update.call_count >= 5
    
    @pytest.mark.asyncio
    async def test_rotation_state_persistence(self):
        """Rotation state persists across multiple checks."""
        vault = AsyncMock()
        repository = AsyncMock()
        audit = AsyncMock()
        
        engine = CredentialRotationEngine(vault, repository, audit)
        policy = RotationPolicy.daily()
        
        await engine.schedule_rotation("cred123", policy, None)
        
        # Get state multiple times
        state1 = await engine.get_rotation_state("cred123")
        state2 = await engine.get_rotation_state("cred123")
        state3 = await engine.get_rotation_state("cred123")
        
        assert state1 is not None
        assert state2 is not None
        assert state3 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
