"""
RBAC Policy Engine and Enforcer Tests

Comprehensive test suite for credential access control.
"""

import pytest
from datetime import datetime, UTC

from core.security.rbac_models import (
    Role,
    CredentialAccessLevel,
    CredentialPolicy,
    AccessDecision,
)
from core.security.policy_engine import CredentialPolicyEngine
from modules.credentials.policy_enforcer import CredentialRBACEnforcer
from modules.credentials import CredentialAccessDenied


class MockPolicyStore:
    """Mock policy store for testing."""
    
    def __init__(self, policies: dict = None):
        self.policies = policies or {}
    
    async def get_policy(self, credential_id: str):
        return self.policies.get(credential_id)
    
    def add_policy(self, policy: CredentialPolicy):
        self.policies[policy.credential_id] = policy


class TestPolicyEngine:
    """Test CredentialPolicyEngine evaluation logic."""
    
    @pytest.fixture
    def store(self):
        """Create mock policy store."""
        return MockPolicyStore()
    
    @pytest.fixture
    def engine(self, store):
        """Create policy engine."""
        return CredentialPolicyEngine(policy_store=store)
    
    @pytest.fixture
    def owner_policy(self):
        """Create owner policy."""
        return CredentialPolicy(
            credential_id="cred-1",
            owner_user_id="user-owner",
            allowed_roles=[Role.ADMIN, Role.OPERATOR],
            secret_read_roles=[Role.ADMIN],
            allowed_users=["user-owner"],
            version=1,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
    
    @pytest.mark.asyncio
    async def test_admin_role_bypass_all_access(self, engine, store, owner_policy):
        """ADMIN role should bypass all checks."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="admin-user",
            user_roles=[Role.ADMIN],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is True
        assert "admin" in decision.reason.lower()
    
    @pytest.mark.asyncio
    async def test_admin_role_bypass_delete(self, engine, store, owner_policy):
        """ADMIN role should be able to delete any credential."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="admin-user",
            user_roles=[Role.ADMIN],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.DELETE,
        )
        
        assert decision.allowed is True
    
    @pytest.mark.asyncio
    async def test_owner_read_metadata(self, engine, store, owner_policy):
        """Owner should be able to read credential metadata."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="user-owner",
            user_roles=[Role.OPERATOR],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is True
        assert "owner" in decision.reason.lower()
    
    @pytest.mark.asyncio
    async def test_owner_cannot_delete(self, engine, store, owner_policy):
        """Owner should NOT be able to delete (only ADMIN)."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="user-owner",
            user_roles=[Role.OPERATOR],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.DELETE,
        )
        
        assert decision.allowed is False
        assert "only admin" in decision.reason.lower()
    
    @pytest.mark.asyncio
    async def test_owner_denied_secret_read_without_role(self, engine, store, owner_policy):
        """Owner without secret_read_role should be denied secret access."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="user-owner",
            user_roles=[Role.OPERATOR],  # Not ADMIN, not in secret_read_roles
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_SECRET,
        )
        
        assert decision.allowed is False
        assert "secret_read_roles" in decision.reason
    
    @pytest.mark.asyncio
    async def test_non_owner_denied_by_default(self, engine, store, owner_policy):
        """Non-owner without explicit grant should be denied."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="other-user",
            user_roles=[Role.DEVELOPER],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is False
    
    @pytest.mark.asyncio
    async def test_role_based_access_allowed(self, engine, store):
        """User with matching role should be granted access."""
        policy = CredentialPolicy(
            credential_id="cred-2",
            owner_user_id="user-owner",
            allowed_roles=[Role.DEVELOPER],
            secret_read_roles=[Role.ADMIN],
            allowed_users=[],
            version=1,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        store.add_policy(policy)
        
        decision = await engine.evaluate(
            user_id="dev-user",
            user_roles=[Role.DEVELOPER],
            credential_id="cred-2",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is True
        assert "role" in decision.reason.lower()
    
    @pytest.mark.asyncio
    async def test_role_based_access_denied(self, engine, store, owner_policy):
        """User without matching role should be denied."""
        store.add_policy(owner_policy)
        
        decision = await engine.evaluate(
            user_id="readonly-user",
            user_roles=[Role.READONLY],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is False
    
    @pytest.mark.asyncio
    async def test_user_list_explicit_grant(self, engine, store):
        """User in allowed_users list should be granted access."""
        policy = CredentialPolicy(
            credential_id="cred-3",
            owner_user_id="user-owner",
            allowed_roles=[],  # No role-based access
            secret_read_roles=[Role.ADMIN],
            allowed_users=["explicit-user"],
            version=1,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        store.add_policy(policy)
        
        decision = await engine.evaluate(
            user_id="explicit-user",
            user_roles=[Role.READONLY],
            credential_id="cred-3",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is True
        assert "allowed_users" in decision.reason
    
    @pytest.mark.asyncio
    async def test_secret_read_requires_elevated_role(self, engine, store):
        """READ_SECRET requires secret_read_roles."""
        policy = CredentialPolicy(
            credential_id="cred-4",
            owner_user_id="user-owner",
            allowed_roles=[Role.OPERATOR],
            secret_read_roles=[Role.ADMIN],
            allowed_users=[],
            version=1,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        store.add_policy(policy)
        
        # Operator can read metadata but not secret
        metadata_decision = await engine.evaluate(
            user_id="op-user",
            user_roles=[Role.OPERATOR],
            credential_id="cred-4",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        assert metadata_decision.allowed is True
        
        # Operator cannot read secret
        secret_decision = await engine.evaluate(
            user_id="op-user",
            user_roles=[Role.OPERATOR],
            credential_id="cred-4",
            access_level=CredentialAccessLevel.READ_SECRET,
        )
        assert secret_decision.allowed is False
    
    @pytest.mark.asyncio
    async def test_secure_default_deny(self, engine, store):
        """Missing policy should default to deny."""
        decision = await engine.evaluate(
            user_id="user",
            user_roles=[Role.ADMIN],
            credential_id="nonexistent-cred",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert decision.allowed is False
        assert "no policy" in decision.reason.lower()


class TestRBACEnforcer:
    """Test CredentialRBACEnforcer enforcement."""
    
    @pytest.fixture
    def store(self):
        """Create mock policy store."""
        return MockPolicyStore()
    
    @pytest.fixture
    def enforcer(self, store):
        """Create RBAC enforcer."""
        engine = CredentialPolicyEngine(policy_store=store)
        return CredentialRBACEnforcer(policy_engine=engine)
    
    @pytest.fixture
    def owner_policy(self):
        """Create owner policy."""
        return CredentialPolicy(
            credential_id="cred-1",
            owner_user_id="user-owner",
            allowed_roles=[Role.ADMIN],
            secret_read_roles=[Role.ADMIN],
            allowed_users=["user-owner"],
            version=1,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
    
    @pytest.mark.asyncio
    async def test_enforce_or_raise_allow(self, enforcer, store, owner_policy):
        """enforce_or_raise should succeed on allow."""
        store.add_policy(owner_policy)
        
        # Should not raise
        await enforcer.enforce_or_raise(
            user_id="user-owner",
            user_roles=[Role.ADMIN],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
    
    @pytest.mark.asyncio
    async def test_enforce_or_raise_deny(self, enforcer, store, owner_policy):
        """enforce_or_raise should raise on deny."""
        store.add_policy(owner_policy)
        
        with pytest.raises(CredentialAccessDenied) as exc_info:
            await enforcer.enforce_or_raise(
                user_id="other-user",
                user_roles=[Role.DEVELOPER],
                credential_id="cred-1",
                access_level=CredentialAccessLevel.READ_METADATA,
            )
        
        assert "cred-1" in str(exc_info.value)
        assert "other-user" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_is_allowed_true(self, enforcer, store, owner_policy):
        """is_allowed should return True on allow."""
        store.add_policy(owner_policy)
        
        result = await enforcer.is_allowed(
            user_id="user-owner",
            user_roles=[Role.ADMIN],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_is_allowed_false(self, enforcer, store, owner_policy):
        """is_allowed should return False on deny."""
        store.add_policy(owner_policy)
        
        result = await enforcer.is_allowed(
            user_id="other-user",
            user_roles=[Role.DEVELOPER],
            credential_id="cred-1",
            access_level=CredentialAccessLevel.READ_METADATA,
        )
        
        assert result is False


class TestAccessDecision:
    """Test AccessDecision immutability and serialization."""
    
    def test_decision_immutable(self):
        """AccessDecision should be immutable."""
        decision = AccessDecision(allowed=True, reason="Test")
        
        with pytest.raises(AttributeError):
            decision.allowed = False
    
    def test_decision_to_dict(self):
        """AccessDecision should serialize to dict."""
        decision = AccessDecision(
            allowed=True,
            reason="Allowed for testing",
            required_roles=[Role.ADMIN],
        )
        
        d = decision.to_dict()
        assert d["allowed"] is True
        assert "Allowed" in d["reason"]
        assert "admin" in d["required_roles"][0]


class TestCredentialPolicy:
    """Test CredentialPolicy immutability and serialization."""
    
    def test_policy_immutable(self):
        """CredentialPolicy should be immutable."""
        policy = CredentialPolicy(
            credential_id="cred-1",
            owner_user_id="user-1",
        )
        
        with pytest.raises(AttributeError):
            policy.owner_user_id = "user-2"
    
    def test_policy_to_dict(self):
        """CredentialPolicy should serialize to dict."""
        policy = CredentialPolicy(
            credential_id="cred-1",
            owner_user_id="user-1",
            allowed_roles=[Role.ADMIN, Role.OPERATOR],
            version=1,
        )
        
        d = policy.to_dict()
        assert d["credential_id"] == "cred-1"
        assert d["owner_user_id"] == "user-1"
        assert len(d["allowed_roles"]) == 2
        assert "admin" in d["allowed_roles"]
    
    def test_policy_from_dict(self):
        """CredentialPolicy should deserialize from dict."""
        data = {
            "credential_id": "cred-1",
            "owner_user_id": "user-1",
            "allowed_roles": ["admin", "operator"],
            "secret_read_roles": ["admin"],
            "allowed_users": ["user-1", "user-2"],
            "version": 1,
            "created_at": "2026-02-17T12:00:00",
            "updated_at": "2026-02-17T12:00:00",
        }
        
        policy = CredentialPolicy.from_dict(data)
        assert policy.credential_id == "cred-1"
        assert policy.owner_user_id == "user-1"
        assert Role.ADMIN in policy.allowed_roles
        assert "user-2" in policy.allowed_users


class TestRoleEnum:
    """Test Role enum."""
    
    def test_role_values(self):
        """All roles should have correct values."""
        assert Role.ADMIN.value == "admin"
        assert Role.OPERATOR.value == "operator"
        assert Role.DEVELOPER.value == "developer"
        assert Role.READONLY.value == "readonly"
        assert Role.SERVICE.value == "service"
    
    def test_role_from_string(self):
        """Role should be constructible from string."""
        role = Role("admin")
        assert role == Role.ADMIN


class TestAccessLevel:
    """Test CredentialAccessLevel enum."""
    
    def test_access_level_values(self):
        """All access levels should have correct values."""
        assert CredentialAccessLevel.READ_METADATA.value == "read_metadata"
        assert CredentialAccessLevel.READ_SECRET.value == "read_secret"
        assert CredentialAccessLevel.WRITE.value == "write"
        assert CredentialAccessLevel.DELETE.value == "delete"
        assert CredentialAccessLevel.ROTATE.value == "rotate"
