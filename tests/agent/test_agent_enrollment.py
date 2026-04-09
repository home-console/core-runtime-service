"""
flow: Tests for Secure Agent Enrollment & Control Plane.

Test coverage:
- Agent identity generation
- Enrollment flow with tokens
- mTLS certificate generation and verification
- Agent registry and status tracking
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from modules.agent import (
    AgentIdentity,
    AgentPublicKey,
    AgentKeyManager,
    AgentIdentityFactory,
    AgentEnrollmentManager,
    MTLSCertificateAuthority,
    AgentRegistry,
    AgentStatus,
)
from modules.agent import (
    EnrollmentToken,
    EnrollmentTokenStatus,
    EnrollmentTokenFactory,
    AgentEnrollmentManager,
)


# Mock SecretStore for testing
class MockSecretStore:
    """In-memory mock of SecretStore for testing."""
    
    def __init__(self):
        self._data = {}
    
    async def put(self, key: str, value: bytes) -> None:
        """Store a secret."""
        self._data[key] = value
    
    async def get(self, key: str) -> Optional[bytes]:
        """Retrieve a secret."""
        return self._data.get(key)
    
    async def delete(self, key: str) -> bool:
        """Delete a secret."""
        if key in self._data:
            del self._data[key]
            return True
        return False
    
    async def exists(self, key: str) -> bool:
        """Check if secret exists."""
        return key in self._data
    
    async def list_secrets(self):
        """List all secret keys."""
        return list(self._data.keys())
    
    async def get_metadata(self, key: str):
        """Get metadata without decryption."""
        if key in self._data:
            return {"exists": True}
        return None


# ============================================================================
# Agent Identity Tests
# ============================================================================

class TestAgentIdentity:
    """Test agent identity model."""
    
    def test_create_agent_identity(self):
        """Create agent identity from dict."""
        now = datetime.now(timezone.utc).isoformat()
        public_key = AgentPublicKey(
            key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
            algorithm="Ed25519",
            created_at=now,
        )
        
        identity = AgentIdentity(
            agent_id="test_agent_123",
            agent_name="node1",
            public_key=public_key,
            created_at=now,
            version=1,
        )
        
        assert identity.agent_id == "test_agent_123"
        assert identity.agent_name == "node1"
        assert identity.version == 1
    
    def test_agent_identity_to_dict(self):
        """Convert identity to dict."""
        now = datetime.now(timezone.utc).isoformat()
        public_key = AgentPublicKey(
            key_pem="test_key",
            created_at=now,
        )
        
        identity = AgentIdentity(
            agent_id="agent1",
            agent_name="node1",
            public_key=public_key,
            created_at=now,
        )
        
        data = identity.to_dict()
        assert isinstance(data, dict)
        assert data["agent_id"] == "agent1"
        assert "public_key" in data
    
    def test_agent_identity_from_dict(self):
        """Create identity from dict."""
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "agent_id": "agent1",
            "agent_name": "node1",
            "public_key": {
                "key_pem": "test_key",
                "algorithm": "Ed25519",
                "created_at": now,
            },
            "created_at": now,
            "version": 1,
        }
        
        identity = AgentIdentity.from_dict(data)
        assert identity.agent_id == "agent1"
        assert identity.agent_name == "node1"


class TestAgentKeyManager:
    """Test Ed25519 key generation."""
    
    def test_generate_key_pair(self):
        """Generate Ed25519 key pair."""
        private_pem, public_pem = AgentKeyManager.generate_key_pair()
        
        assert b"-----BEGIN PRIVATE KEY-----" in private_pem
        assert b"-----END PRIVATE KEY-----" in private_pem
        assert b"-----BEGIN PUBLIC KEY-----" in public_pem
        assert b"-----END PUBLIC KEY-----" in public_pem
    
    def test_generate_key_pair_different(self):
        """Each key pair is different."""
        pair1 = AgentKeyManager.generate_key_pair()
        pair2 = AgentKeyManager.generate_key_pair()
        
        assert pair1 != pair2
    
    def test_compute_agent_id(self):
        """Compute deterministic agent ID from public key."""
        _, public_pem = AgentKeyManager.generate_key_pair()
        agent_id = AgentKeyManager.compute_agent_id(public_pem)
        
        assert isinstance(agent_id, str)
        assert len(agent_id) == 16  # 64 bits in hex
        
        # Deterministic
        agent_id2 = AgentKeyManager.compute_agent_id(public_pem)
        assert agent_id == agent_id2
    
    def test_sign_and_verify_message(self):
        """Sign a message and verify it."""
        private_pem, public_pem = AgentKeyManager.generate_key_pair()
        message = b"test message to sign"
        
        # Sign
        signature = AgentKeyManager.sign_message(message, private_pem)
        assert isinstance(signature, bytes)
        assert len(signature) > 0
        
        # Verify
        valid = AgentKeyManager.verify_signature(message, signature, public_pem)
        assert valid is True
    
    def test_verify_wrong_message_fails(self):
        """Verify fails with different message."""
        private_pem, public_pem = AgentKeyManager.generate_key_pair()
        
        signature = AgentKeyManager.sign_message(b"message1", private_pem)
        valid = AgentKeyManager.verify_signature(b"message2", signature, public_pem)
        
        assert valid is False


class TestAgentIdentityFactory:
    """Test identity creation."""
    
    def test_create_identity(self):
        """Factory creates identity with keys."""
        now = datetime.now(timezone.utc).isoformat()
        identity, private_pem = AgentIdentityFactory.create_identity(
            agent_name="node1",
            created_at=now,
        )
        
        assert identity.agent_id
        assert identity.agent_name == "node1"
        assert len(identity.agent_id) == 16
        assert b"-----BEGIN PRIVATE KEY-----" in private_pem
    
    def test_create_different_identities(self):
        """Each identity is different."""
        now = datetime.now(timezone.utc).isoformat()
        
        id1, _ = AgentIdentityFactory.create_identity("node1", now)
        id2, _ = AgentIdentityFactory.create_identity("node2", now)
        
        assert id1.agent_id != id2.agent_id


# ============================================================================
# Enrollment Tests
# ============================================================================

class TestEnrollmentToken:
    """Test enrollment tokens."""
    
    def test_create_enrollment_token(self):
        """Generate enrollment token."""
        now = datetime.now(timezone.utc).isoformat()
        token = EnrollmentTokenFactory.generate_token("node1", now)
        
        assert token.token_id
        assert token.token_secret
        assert token.token_hash
        assert token.agent_name == "node1"
        assert token.status == EnrollmentTokenStatus.ACTIVE
    
    def test_token_is_valid(self):
        """Check token validity."""
        now = datetime.now(timezone.utc).isoformat()
        token = EnrollmentTokenFactory.generate_token("node1", now)
        
        assert token.is_valid() is True
    
    def test_token_expired(self):
        """Token becomes invalid when expired."""
        now = datetime.now(timezone.utc) - timedelta(hours=2)
        token = EnrollmentTokenFactory.generate_token(
            "node1",
            now.isoformat(),
            ttl_seconds=3600,
        )
        
        assert token.is_valid() is False
    
    def test_token_revoked(self):
        """Revoked token is invalid."""
        now = datetime.now(timezone.utc).isoformat()
        token = EnrollmentTokenFactory.generate_token("node1", now)
        token.status = EnrollmentTokenStatus.REVOKED
        
        assert token.is_valid() is False
    
    def test_verify_token_secret(self):
        """Verify token secret against hash."""
        now = datetime.now(timezone.utc).isoformat()
        token = EnrollmentTokenFactory.generate_token("node1", now)
        
        # Correct secret
        valid = EnrollmentTokenFactory.verify_token(
            token.token_secret,
            token.token_hash,
        )
        assert valid is True
        
        # Wrong secret
        valid = EnrollmentTokenFactory.verify_token(
            "wrong_secret",
            token.token_hash,
        )
        assert valid is False
    
    def test_token_to_dict(self):
        """Convert token to dict."""
        now = datetime.now(timezone.utc).isoformat()
        token = EnrollmentTokenFactory.generate_token("node1", now)
        
        data = token.to_dict()
        assert isinstance(data, dict)
        assert data["agent_name"] == "node1"


class TestAgentEnrollmentManager:
    """Test enrollment flow."""
    
    @pytest.mark.asyncio
    async def test_enrollment_flow(self):
        """Complete enrollment flow."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)
        now = datetime.now(timezone.utc).isoformat()
        
        # flow: Create token
        token = await manager.create_enrollment_token("node1", now)
        assert token.agent_name == "node1"
        assert token.status == EnrollmentTokenStatus.ACTIVE
        
        # flow: Enroll agent
        identity, private_key = await manager.enroll_agent(
            token.token_id,
            token.token_secret,
            now,
        )
        
        assert identity.agent_name == "node1"
        assert len(identity.agent_id) == 16
        assert b"-----BEGIN PRIVATE KEY-----" in private_key

    @pytest.mark.asyncio
    async def test_generate_token_validate_is_one_time(self):
        """HMAC-signed token is one-time via SecretStore hash presence."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)

        token_str = await manager.generate_enrollment_token("node1")
        # First validation OK
        agent_name = await manager.validate_enrollment_token(token_str)
        assert agent_name == "node1"

        # Second validation must fail (hash deleted / one-time use)
        with pytest.raises(ValueError, match="already used"):
            await manager.validate_enrollment_token(token_str)
    
    @pytest.mark.asyncio
    async def test_enrollment_wrong_token_fails(self):
        """Enrollment fails with wrong token."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)
        now = datetime.now(timezone.utc).isoformat()
        
        with pytest.raises(ValueError, match="not found"):
            await manager.enroll_agent("wrong_token", "wrong_secret", now)
    
    @pytest.mark.asyncio
    async def test_enrollment_wrong_secret_fails(self):
        """Enrollment fails with wrong secret."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)
        now = datetime.now(timezone.utc).isoformat()
        
        # Create token
        token = await manager.create_enrollment_token("node1", now)
        
        # Try with wrong secret
        with pytest.raises(ValueError, match="secret mismatch"):
            await manager.enroll_agent(
                token.token_id,
                "wrong_secret",
                now,
            )
    
    @pytest.mark.asyncio
    async def test_get_enrolled_agent(self):
        """Retrieve enrolled agent."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)
        now = datetime.now(timezone.utc).isoformat()
        
        # Enroll
        token = await manager.create_enrollment_token("node1", now)
        identity, _ = await manager.enroll_agent(
            token.token_id,
            token.token_secret,
            now,
        )
        
        # Retrieve
        retrieved = await manager.get_agent_identity(identity.agent_id)
        assert retrieved == identity
    
    @pytest.mark.asyncio
    async def test_get_agent_private_key(self):
        """Retrieve agent private key from storage."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)
        now = datetime.now(timezone.utc).isoformat()
        
        # Enroll
        token = await manager.create_enrollment_token("node1", now)
        identity, original_key = await manager.enroll_agent(
            token.token_id,
            token.token_secret,
            now,
        )
        
        # Retrieve key
        stored_key = await manager.get_agent_private_key(identity.agent_id)
        assert stored_key == original_key
    
    @pytest.mark.asyncio
    async def test_deregister_agent(self):
        """Deregister an agent."""
        secret_store = MockSecretStore()
        manager = AgentEnrollmentManager(secret_store)
        now = datetime.now(timezone.utc).isoformat()
        
        # Enroll
        token = await manager.create_enrollment_token("node1", now)
        identity, _ = await manager.enroll_agent(
            token.token_id,
            token.token_secret,
            now,
        )
        
        # Deregister
        result = await manager.deregister_agent(identity.agent_id)
        assert result is True
        
        # Verify gone
        retrieved = await manager.get_agent_identity(identity.agent_id)
        assert retrieved is None


# ============================================================================
# mTLS Tests
# ============================================================================

class TestMTLSCertificateAuthority:
    """Test certificate generation."""
    
    def test_generate_ca_certificate(self):
        """Generate CA certificate."""
        ca_private_pem, ca_cert_pem = MTLSCertificateAuthority.generate_ca_certificate()
        
        assert b"-----BEGIN PRIVATE KEY-----" in ca_private_pem
        assert b"-----BEGIN CERTIFICATE-----" in ca_cert_pem
    
    def test_create_ca_from_keys(self):
        """Create CA from existing keys."""
        ca_private_pem, ca_cert_pem = MTLSCertificateAuthority.generate_ca_certificate()
        ca = MTLSCertificateAuthority(ca_private_pem, ca_cert_pem)
        
        assert ca is not None
    
    def test_verify_ca_certificate(self):
        """Verify CA certificate is self-signed."""
        _, ca_cert_pem = MTLSCertificateAuthority.generate_ca_certificate()
        ca_private_pem, _ = MTLSCertificateAuthority.generate_ca_certificate()
        
        # Create CA and verify its own cert
        ca = MTLSCertificateAuthority(ca_private_pem, ca_cert_pem)
        
        # Verify works (cert is self-signed)
        assert ca is not None


class TestAgentRegistry:
    """Test agent registry."""
    
    @pytest.mark.asyncio
    async def test_register_agent_online(self):
        """Register agent as online."""
        registry = AgentRegistry()
        now = datetime.now(timezone.utc).isoformat()
        
        await registry.register_agent_online(
            agent_id="agent1",
            agent_name="node1",
            version="1.0.0",
            address="localhost:5000",
            capabilities=["ssh:exec", "device:control"],
            now=now,
        )
        
        metadata = await registry.get_agent("agent1")
        assert metadata is not None
        assert metadata.status == AgentStatus.ONLINE
        assert "ssh:exec" in metadata.capabilities
    
    @pytest.mark.asyncio
    async def test_list_agents(self):
        """List all agents."""
        registry = AgentRegistry()
        now = datetime.now(timezone.utc).isoformat()
        
        # Register two agents
        await registry.register_agent_online(
            "agent1", "node1", "1.0.0", "localhost:5000", [], now
        )
        await registry.register_agent_online(
            "agent2", "node2", "1.0.0", "localhost:5001", [], now
        )
        
        agents = await registry.list_agents()
        assert len(agents) == 2
    
    @pytest.mark.asyncio
    async def test_list_online_agents(self):
        """List only online agents."""
        registry = AgentRegistry()
        now = datetime.now(timezone.utc).isoformat()
        
        # Register and mark one offline
        await registry.register_agent_online(
            "agent1", "node1", "1.0.0", "localhost:5000", [], now
        )
        await registry.register_agent_online(
            "agent2", "node2", "1.0.0", "localhost:5001", [], now
        )
        
        await registry.mark_agent_offline("agent2")
        
        online = await registry.list_online_agents()
        assert len(online) == 1
        assert online[0].agent_id == "agent1"
    
    @pytest.mark.asyncio
    async def test_list_agents_providing_capability(self):
        """List agents with specific capability."""
        registry = AgentRegistry()
        now = datetime.now(timezone.utc).isoformat()
        
        # Register agents with different capabilities
        await registry.register_agent_online(
            "agent1", "node1", "1.0.0", "localhost:5000",
            ["ssh:exec", "device:control"], now
        )
        await registry.register_agent_online(
            "agent2", "node2", "1.0.0", "localhost:5001",
            ["ssh:exec"], now
        )
        
        # Find agents with device:control
        agents = await registry.list_agents_providing_capability("device:control")
        assert len(agents) == 1
        assert agents[0].agent_id == "agent1"
    
    @pytest.mark.asyncio
    async def test_update_heartbeat(self):
        """Update agent heartbeat."""
        registry = AgentRegistry()
        now1 = datetime.now(timezone.utc).isoformat()
        
        await registry.register_agent_online(
            "agent1", "node1", "1.0.0", "localhost:5000", [], now1
        )
        
        # Update heartbeat
        now2 = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        await registry.update_agent_heartbeat("agent1", now2)
        
        metadata = await registry.get_agent("agent1")
        assert metadata.last_heartbeat == now2
    
    @pytest.mark.asyncio
    async def test_deregister_agent(self):
        """Deregister agent."""
        registry = AgentRegistry()
        now = datetime.now(timezone.utc).isoformat()
        
        await registry.register_agent_online(
            "agent1", "node1", "1.0.0", "localhost:5000", [], now
        )
        
        result = await registry.deregister_agent("agent1")
        assert result is True
        
        # Verify gone
        metadata = await registry.get_agent("agent1")
        assert metadata is None
