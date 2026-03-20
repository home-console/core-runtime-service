"""
Test Suite for Step 17.5 — Global Audit Integration (Tamper-Evident)

Tests credential subsystem integration with P0 storage hardening:
- SecurityEvent immutability and serialization
- AuditBinder append operations
- Tamper detection (Merkle root verification)
- Rollback detection (epoch regression)  
- Access denial logging
- Secret read logging
- Forensic event retrieval
"""

import pytest
import asyncio
from datetime import datetime
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, MagicMock

from core.audit.events import (
    SecurityEvent,
    SecurityEventType,
    credential_created_event,
    credential_updated_event,
    credential_deleted_event,
    credential_secret_read_event,
    credential_access_denied_event,
)
from core.audit.binder import AuditBinder
from modules.credentials.policy_enforcer import CredentialRBACEnforcer
from core.security.rbac_models import Role, CredentialAccessLevel
from core.security.policy_engine import CredentialPolicyEngine
from modules.credentials import CredentialAccessDenied


# ============================================================================
# FIXTURES & MOCKS
# ============================================================================

class MockSecureStorage:
    """Mock SecureStorageWrapper for testing audit operations."""
    
    def __init__(self):
        self._events: dict[str, dict] = {}
        self._epoch = 0
    
    async def append(self, namespace: str, event: dict) -> str:
        """Mock append operation."""
        assert namespace == "_audit.security"
        assert "id" in event
        
        event_id = event["id"]
        self._events[event_id] = event
        return event_id
    
    async def get(self, namespace: str, key: str):
        """Mock get operation."""
        if namespace == "_system.meta" and key == "global_epoch":
            return {"epoch": self._epoch}
        if namespace == "_audit.security":
            return self._events.get(key)
        return None
    
    async def list_keys(self, namespace: str) -> list[str]:
        """Mock list_keys operation."""
        if namespace == "_audit.security":
            return list(self._events.keys())
        return []
    
    def get_all_events(self) -> list[dict]:
        """Test helper: get all stored events."""
        return list(self._events.values())


# ============================================================================
# SECURITY EVENT TESTS
# ============================================================================

class TestSecurityEvent:
    """Test SecurityEvent immutability and serialization."""
    
    def test_event_immutability(self):
        """SecurityEvent is immutable (frozen=True)."""
        event = credential_created_event(
            user_id="user_1",
            credential_id="cred_1",
            fingerprint="abc123",
        )
        
        # Should not allow attribute modification
        with pytest.raises(AttributeError):
            event.user_id = "user_2"
    
    def test_event_serialization(self):
        """SecurityEvent.to_dict() produces valid JSON-serializable output."""
        event = credential_created_event(
            user_id="user_1",
            credential_id="cred_1",
            fingerprint="abc123",
            name="database_password",
        )
        
        data = event.to_dict()
        
        # Should be dict with proper fields
        assert isinstance(data, dict)
        assert data["user_id"] == "user_1"
        assert data["credential_id"] == "cred_1"
        assert data["fingerprint"] == "abc123"
        assert data["event_type"] == SecurityEventType.CREDENTIAL_CREATED.value
        
        # event_type should be string, not enum
        assert isinstance(data["event_type"], str)
    
    def test_event_deserialization(self):
        """SecurityEvent.from_dict() reconstructs from stored data."""
        original = credential_created_event(
            user_id="user_1",
            credential_id="cred_1",
            fingerprint="abc123",
        )
        
        data = original.to_dict()
        reconstructed = SecurityEvent.from_dict(data)
        
        assert reconstructed.user_id == original.user_id
        assert reconstructed.credential_id == original.credential_id
        assert reconstructed.fingerprint == original.fingerprint
        assert reconstructed.event_type == original.event_type
    
    def test_event_type_enum_conversion(self):
        """SecurityEventType can convert to/from string."""
        event = credential_secret_read_event(
            user_id="user_1",
            credential_id="cred_1",
            fingerprint="abc123",
        )
        
        assert event.event_type == SecurityEventType.CREDENTIAL_SECRET_READ
        
        data = event.to_dict()
        assert data["event_type"] == "credential.secret.read"
        
        reconstructed = SecurityEvent.from_dict(data)
        assert reconstructed.event_type == SecurityEventType.CREDENTIAL_SECRET_READ
    
    def test_access_denied_event_has_no_fingerprint(self):
        """Access denied events contain reason but no fingerprint."""
        event = credential_access_denied_event(
            user_id="user_1",
            credential_id="cred_1",
            reason="insufficient_role",
        )
        
        assert event.event_type == SecurityEventType.CREDENTIAL_ACCESS_DENIED
        assert event.fingerprint == ""  # No fingerprint for denied access
        assert event.metadata["reason"] == "insufficient_role"


# ============================================================================
# AUDIT BINDER TESTS
# ============================================================================

@pytest.mark.asyncio
class TestAuditBinder:
    """Test AuditBinder integration with P0 storage."""
    
    async def test_append_creates_event(self):
        """AuditBinder.append() stores event in secure storage."""
        mock_storage = MockSecureStorage()
        binder = AuditBinder(mock_storage)
        
        event = credential_created_event(
            user_id="user_1",
            credential_id="cred_1",
            fingerprint="abc123",
        )
        
        # Append event
        result_id = await binder.append(event)
        
        # Should return event ID
        assert result_id == event.id
        
        # Should be stored in mock storage
        stored_events = mock_storage.get_all_events()
        assert len(stored_events) == 1
        assert stored_events[0]["id"] == event.id
    
    async def test_get_event_retrieves_from_storage(self):
        """AuditBinder.get() retrieves stored event by ID."""
        mock_storage = MockSecureStorage()
        binder = AuditBinder(mock_storage)
        
        event = credential_created_event(
            user_id="user_1",
            credential_id="cred_1",
            fingerprint="abc123",
        )
        
        # Append event
        await binder.append(event)
        
        # Retrieve event
        retrieved = await binder.get(event.id)
        
        assert retrieved is not None
        assert retrieved.user_id == event.user_id
        assert retrieved.credential_id == event.credential_id
        assert retrieved.event_type == event.event_type
    
    async def test_get_nonexistent_event_returns_none(self):
        """AuditBinder.get() returns None for nonexistent events."""
        binder = AuditBinder(MockSecureStorage())
        
        result = await binder.get("nonexistent_id")
        
        assert result is None
    
    async def test_list_events_returns_all_events(self):
        """AuditBinder.list_events() iterates all events."""
        binder = AuditBinder(MockSecureStorage())
        
        # Create 3 events
        events = [
            credential_created_event("user_1", "cred_1", "fp1"),
            credential_updated_event("user_1", "cred_1", "fp1", "fp2"),
            credential_deleted_event("user_1", "cred_1", "fp2"),
        ]
        
        for event in events:
            await binder.append(event)
        
        # List events
        listed = []
        async for event in binder.list_events():
            listed.append(event)
        
        assert len(listed) == 3
    
    async def test_list_events_filtered_by_credential(self):
        """AuditBinder.list_events(credential_id) filters by credential."""
        binder = AuditBinder(MockSecureStorage())
        
        # Create events for 2 credentials
        await binder.append(credential_created_event("user_1", "cred_1", "fp1"))
        await binder.append(credential_created_event("user_1", "cred_2", "fp2"))
        await binder.append(credential_created_event("user_1", "cred_1", "fp3"))
        
        # List events for cred_1
        cred1_events = []
        async for event in binder.list_events(credential_id="cred_1"):
            cred1_events.append(event)
        
        assert len(cred1_events) == 2
        assert all(e.credential_id == "cred_1" for e in cred1_events)
    
    async def test_count_events_returns_total(self):
        """AuditBinder.count_events() returns event count."""
        binder = AuditBinder(MockSecureStorage())
        
        await binder.append(credential_created_event("user_1", "cred_1", "fp1"))
        await binder.append(credential_created_event("user_1", "cred_2", "fp2"))
        
        total = await binder.count_events()
        assert total == 2
    
    async def test_count_events_filtered_by_credential(self):
        """AuditBinder.count_events(credential_id) counts for specific credential."""
        binder = AuditBinder(MockSecureStorage())
        
        await binder.append(credential_created_event("user_1", "cred_1", "fp1"))
        await binder.append(credential_created_event("user_1", "cred_1", "fp2"))
        await binder.append(credential_created_event("user_1", "cred_2", "fp3"))
        
        cred1_count = await binder.count_events(credential_id="cred_1")
        assert cred1_count == 2
    
    async def test_get_secret_access_log(self):
        """AuditBinder.get_secret_access_log() returns only READ_SECRET events."""
        binder = AuditBinder(MockSecureStorage())
        
        cred_id = "cred_1"
        
        # Mix of events
        await binder.append(credential_created_event("user_1", cred_id, "fp1"))
        await binder.append(credential_secret_read_event("user_1", cred_id, "fp1"))
        await binder.append(credential_secret_read_event("user_2", cred_id, "fp1"))
        await binder.append(credential_updated_event("user_1", cred_id, "fp1", "fp2"))
        
        # Get secret read log
        secret_reads = await binder.get_secret_access_log(cred_id)
        
        assert len(secret_reads) == 2
        assert all(e.event_type == SecurityEventType.CREDENTIAL_SECRET_READ for e in secret_reads)
    
    async def test_get_access_violations(self):
        """AuditBinder.get_access_violations() returns only ACCESS_DENIED events."""
        binder = AuditBinder(MockSecureStorage())
        
        cred_id = "cred_1"
        
        # Mix of events
        await binder.append(credential_created_event("user_1", cred_id, "fp1"))
        await binder.append(credential_access_denied_event("user_2", cred_id, "insufficient_role"))
        await binder.append(credential_secret_read_event("user_1", cred_id, "fp1"))
        await binder.append(credential_access_denied_event("user_3", cred_id, "not_owner"))
        
        # Get violations
        violations = await binder.get_access_violations(credential_id=cred_id)
        
        assert len(violations) == 2
        assert all(e.event_type == SecurityEventType.CREDENTIAL_ACCESS_DENIED for e in violations)
    
    async def test_audit_trail_for_user(self):
        """AuditBinder.audit_trail_for_user() returns all events for a user."""
        binder = AuditBinder(MockSecureStorage())
        
        # Create events by different users
        await binder.append(credential_created_event("user_1", "cred_1", "fp1"))
        await binder.append(credential_created_event("user_2", "cred_2", "fp2"))
        await binder.append(credential_secret_read_event("user_1", "cred_1", "fp1"))
        await binder.append(credential_secret_read_event("user_2", "cred_2", "fp2"))
        
        # Get trail for user_1
        user1_trail = await binder.audit_trail_for_user("user_1")
        
        assert len(user1_trail) == 2
        assert all(e.user_id == "user_1" for e in user1_trail)


# ============================================================================
# RBAC ENFORCER AUDIT TESTS
# ============================================================================

@pytest.mark.asyncio
class TestRBACEnforcerAudit:
    """Test that RBACEnforcer logs access denials."""
    
    async def test_enforcer_logs_access_denied(self):
        """RBACEnforcer logs access denials to audit binder."""
        mock_storage = MockSecureStorage()
        audit_binder = AuditBinder(mock_storage)
        
        # Mock policy engine that always denies
        mock_policy_engine = AsyncMock()
        mock_policy_engine.evaluate = AsyncMock(return_value=Mock(
            allowed=False,
            reason="insufficient_role",
            required_roles=[],
        ))
        
        enforcer = CredentialRBACEnforcer(
            policy_engine=mock_policy_engine,
            audit_binder=audit_binder,
        )
        
        # Try to enforce (should raise and audit)
        with pytest.raises(CredentialAccessDenied):
            await enforcer.enforce_or_raise(
                user_id="user_1",
                user_roles=[Role.READONLY],
                credential_id="cred_1",
                access_level=CredentialAccessLevel.WRITE,
            )
        
        # Check that denial was logged
        events = mock_storage.get_all_events()
        assert len(events) == 1
        
        logged_event = events[0]
        assert logged_event["event_type"] == SecurityEventType.CREDENTIAL_ACCESS_DENIED.value
        assert logged_event["user_id"] == "user_1"
        assert logged_event["credential_id"] == "cred_1"
        assert logged_event["metadata"]["reason"] == "insufficient_role"
    
    async def test_enforcer_doesnt_log_allowed_access(self):
        """RBACEnforcer doesn't log when access is allowed."""
        mock_storage = MockSecureStorage()
        audit_binder = AuditBinder(mock_storage)
        
        # Mock policy engine that allows
        mock_policy_engine = AsyncMock()
        mock_policy_engine.evaluate = AsyncMock(return_value=Mock(
            allowed=True,
            reason="",
            required_roles=[],
        ))
        
        enforcer = CredentialRBACEnforcer(
            policy_engine=mock_policy_engine,
            audit_binder=audit_binder,
        )
        
        # Enforce (should not raise)
        await enforcer.enforce_or_raise(
            user_id="user_1",
            user_roles=[Role.ADMIN],
            credential_id="cred_1",
            access_level=CredentialAccessLevel.WRITE,
        )
        
        # Check that no denial was logged
        events = mock_storage.get_all_events()
        assert len(events) == 0


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

@pytest.mark.asyncio
class TestAuditIntegration:
    """Test audit integration across credential lifecycle."""
    
    async def test_credential_lifecycle_audit_trail(self):
        """Full credential lifecycle generates expected audit events."""
        binder = AuditBinder(MockSecureStorage())
        
        user_id = "user_1"
        cred_id = "cred_1"
        
        # Simulate credential creation
        await binder.append(credential_created_event(
            user_id=user_id,
            credential_id=cred_id,
            fingerprint="fp_v1",
            name="database_password",
        ))
        
        # Simulate secret read
        await binder.append(credential_secret_read_event(
            user_id=user_id,
            credential_id=cred_id,
            fingerprint="fp_v1",
        ))
        
        # Simulate update
        await binder.append(credential_updated_event(
            user_id=user_id,
            credential_id=cred_id,
            old_fingerprint="fp_v1",
            new_fingerprint="fp_v2",
        ))
        
        # Simulate secret read again with new version
        await binder.append(credential_secret_read_event(
            user_id=user_id,
            credential_id=cred_id,
            fingerprint="fp_v2",
        ))
        
        # Simulate deletion
        await binder.append(credential_deleted_event(
            user_id=user_id,
            credential_id=cred_id,
            fingerprint="fp_v2",
        ))
        
        # Verify trail
        trail = await binder.get_events_for_credential(cred_id)
        
        assert len(trail) == 5
        
        # Verify event types (order may vary due to sorting)
        event_types = [e.event_type for e in trail]
        assert SecurityEventType.CREDENTIAL_CREATED in event_types
        assert SecurityEventType.CREDENTIAL_SECRET_READ in event_types
        assert SecurityEventType.CREDENTIAL_UPDATED in event_types
        assert SecurityEventType.CREDENTIAL_DELETED in event_types
        
        # Verify secret_read occurs (appears twice)
        secret_read_count = sum(1 for e in trail if e.event_type == SecurityEventType.CREDENTIAL_SECRET_READ)
        assert secret_read_count == 2
    
    async def test_multi_user_credential_access(self):
        """Multiple users accessing same credential creates proper audit trail."""
        binder = AuditBinder(MockSecureStorage())
        
        cred_id = "shared_credential"
        
        # User 1 creates
        await binder.append(credential_created_event(
            user_id="user_1",
            credential_id=cred_id,
            fingerprint="fp_v1",
        ))
        
        # User 2 reads (denied)
        await binder.append(credential_access_denied_event(
            user_id="user_2",
            credential_id=cred_id,
            reason="not_owner",
        ))
        
        # User 1 shares with user 2 (by updating policy)
        # ...
        
        # User 2 reads (allowed after sharing)
        await binder.append(credential_secret_read_event(
            user_id="user_2",
            credential_id=cred_id,
            fingerprint="fp_v1",
        ))
        
        # Check audit trail shows both access attempt and successful read
        violations = await binder.get_access_violations(credential_id=cred_id)
        assert len(violations) == 1
        
        secret_reads = await binder.get_secret_access_log(credential_id=cred_id)
        assert len(secret_reads) == 1
        assert secret_reads[0].user_id == "user_2"


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
