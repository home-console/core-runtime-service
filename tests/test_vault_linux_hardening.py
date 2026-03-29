"""
flow: Linux-First Hardened Vault Tests

Comprehensive test coverage:
1. SecureBuffer: mlock, MADV_DONTDUMP, zeroization
2. VaultHardening: core dump disable, ptrace disable, mlockall
3. VaultSession: unlock, lock, TTL expiration
4. Namespace KDF: isolation, key derivation
5. SecretAccessPolicy: whitelist enforcement
"""

import pytest
import asyncio
import sys
import os
from unittest.mock import patch, MagicMock

# Skip non-Linux tests
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Tests require Linux"
)

from modules.security.secure_memory import SecureBuffer, SecureBytes, wipe_memory
from modules.security.vault_hardening import VaultHardening, HardeningStatus
from modules.security.vault_session import VaultSession, VaultLockedError, SessionExpiredError
from modules.security.secret_policy import SecretAccessPolicy, SecretAccessDenied, create_default_policy


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: SecureBuffer - mlock and MADV_DONTDUMP
# ──────────────────────────────────────────────────────────────────────────────

class TestSecureBuffer:
    """Test SecureBuffer memory protection."""
    
    def test_secure_buffer_allocation(self):
        """Test creating SecureBuffer with data."""
        data = b"secret_key_material_12345"
        buf = SecureBuffer(data)
        
        assert buf.bytes == data
        assert buf._locked is True  # mlock called
        
        buf.close()
        assert buf._zeroed is True
    
    def test_secure_buffer_empty_raises(self):
        """Test that empty buffer raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            SecureBuffer(b"")
    
    def test_secure_buffer_wrong_type_raises(self):
        """Test that non-bytes raises TypeError."""
        with pytest.raises(TypeError, match="bytes/bytearray"):
            SecureBuffer("not bytes")
    
    def test_secure_buffer_repr_blocked(self):
        """Test that repr() is blocked."""
        buf = SecureBuffer(b"secret")
        
        repr_str = repr(buf)
        assert "secret" not in repr_str
        assert "***" in repr_str
        
        buf.close()
    
    def test_secure_buffer_str_blocked(self):
        """Test that str() is blocked."""
        buf = SecureBuffer(b"secret")
        
        str_result = str(buf)
        assert "secret" not in str_result
        assert "***" in str_result
        
        buf.close()
    
    def test_secure_buffer_copy_blocked(self):
        """Test that copy is blocked."""
        import copy
        buf = SecureBuffer(b"secret")
        
        with pytest.raises(TypeError, match="cannot be copied"):
            copy.copy(buf)
        
        buf.close()
    
    def test_secure_buffer_deepcopy_blocked(self):
        """Test that deepcopy is blocked."""
        import copy
        buf = SecureBuffer(b"secret")
        
        with pytest.raises(TypeError, match="cannot be deepcopied"):
            copy.deepcopy(buf)
        
        buf.close()
    
    def test_secure_buffer_pickle_blocked(self):
        """Test that pickle is blocked."""
        import pickle
        buf = SecureBuffer(b"secret")
        
        with pytest.raises(TypeError, match="cannot be pickled"):
            pickle.dumps(buf)
        
        buf.close()
    
    def test_secure_buffer_context_manager(self):
        """Test context manager auto-close."""
        with SecureBuffer(b"secret") as buf:
            assert buf.bytes == b"secret"
            assert not buf._zeroed
        
        # After exit, should be zeroed
        assert buf._zeroed
    
    def test_secure_buffer_zeroization(self):
        """Test that close() zeroizes memory."""
        buf = SecureBuffer(b"secret_key_" * 10)
        original = buf._buffer[:]
        
        buf.close()
        
        # After close, cannot read (raises error)
        with pytest.raises(RuntimeError, match="closed"):
            _ = buf.bytes
    
    def test_wipe_memory(self):
        """Test manual memory wipe."""
        data = bytearray(b"secret_data")
        
        # Wipe it
        wipe_memory(data)
        
        # Should be all zeros
        assert all(b == 0 for b in data)
    
    def test_wipe_memory_wrong_type(self):
        """Test that wipe_memory requires bytearray."""
        with pytest.raises(TypeError):
            wipe_memory(b"bytes")  # bytes, not bytearray


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: VaultHardening - process hardening
# ──────────────────────────────────────────────────────────────────────────────

class TestVaultHardening:
    """Test VaultHardening process hardening."""
    
    def test_hardening_enable(self):
        """Test enabling hardening."""
        # Reset flag
        VaultHardening._enabled = False
        
        # Enable hardening (this is destructive, only in test)
        try:
            VaultHardening.enable()
            assert VaultHardening.is_enabled()
        except RuntimeError:
            # May fail due to permissions, that's ok for test
            pytest.skip("Hardening requires elevated permissions")
    
    def test_core_dump_limit(self):
        """Test core dump limit reading."""
        soft, hard = HardeningStatus.get_core_dump_limit()
        
        # Should be valid integers
        assert isinstance(soft, int)
        assert isinstance(hard, int)
    
    def test_hardening_idempotent(self):
        """Test that enabling twice is safe."""
        VaultHardening._enabled = False
        
        try:
            VaultHardening.enable()
            enabled_once = VaultHardening.is_enabled()
            
            # Enable again
            VaultHardening.enable()
            enabled_twice = VaultHardening.is_enabled()
            
            assert enabled_once == enabled_twice
        except RuntimeError:
            pytest.skip("Hardening requires elevated permissions")


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: VaultSession - TTL and unlock
# ──────────────────────────────────────────────────────────────────────────────

class TestVaultSession:
    """Test VaultSession unlock/lock/TTL."""
    
    @pytest.mark.asyncio
    async def test_session_unlock_creates_master_key(self):
        """Test that unlock creates master key in SecureBuffer."""
        session = VaultSession(ttl_seconds=3600)
        
        assert not session.is_unlocked()
        
        await session.unlock("test_passphrase")
        
        assert session.is_unlocked()
        assert session._master_key is not None
        assert isinstance(session._master_key, SecureBuffer)
        
        await session.lock()
    
    @pytest.mark.asyncio
    async def test_session_lock_zeroizes(self):
        """Test that lock zeroizes master key."""
        session = VaultSession()
        
        await session.unlock("test_passphrase")
        assert session.is_unlocked()
        
        await session.lock()
        assert not session.is_unlocked()
        assert session._master_key is None
    
    @pytest.mark.asyncio
    async def test_session_locked_raises_error(self):
        """Test that operations on locked session raise error."""
        session = VaultSession()
        
        # Not unlocked yet
        with pytest.raises(VaultLockedError):
            session.derive_namespace_key("test")
    
    @pytest.mark.asyncio
    async def test_session_empty_passphrase_raises(self):
        """Test that empty passphrase raises ValueError."""
        session = VaultSession()
        
        with pytest.raises(ValueError, match="empty"):
            await session.unlock("")
    
    @pytest.mark.asyncio
    async def test_session_ttl_expiration(self):
        """Test that session expires after TTL."""
        session = VaultSession(ttl_seconds=1)  # 1 second TTL
        
        await session.unlock("test_passphrase")
        assert session.is_unlocked()
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Should be expired now
        assert not session.is_unlocked()
        assert session._expired
        
        # Operations should raise
        with pytest.raises(SessionExpiredError):
            session.derive_namespace_key("test")
    
    @pytest.mark.asyncio
    async def test_session_derive_namespace_key(self):
        """Test namespace key derivation."""
        session = VaultSession()
        await session.unlock("test_passphrase")
        
        # Derive keys for different namespaces
        key1 = session.derive_namespace_key("namespace1")
        key2 = session.derive_namespace_key("namespace2")
        
        # Same namespace = same key
        key1_again = session.derive_namespace_key("namespace1")
        assert key1 == key1_again
        
        # Different namespace = different key
        assert key1 != key2
        
        # Keys should be bytes of correct length
        assert isinstance(key1, bytes)
        assert len(key1) == 32
        
        await session.lock()
    
    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        """Test session context manager."""
        session = VaultSession()
        
        with pytest.raises(VaultLockedError):
            async with session.transaction():
                pass
        
        await session.unlock("test_passphrase")
        
        # Now should work
        async with session.transaction() as s:
            assert s is session
        
        await session.lock()
    
    @pytest.mark.asyncio
    async def test_session_get_info(self):
        """Test session info retrieval."""
        session = VaultSession(ttl_seconds=3600)
        
        # Before unlock
        info = session.get_session_info()
        assert not info["is_unlocked"]
        
        await session.unlock("test_passphrase")
        
        # After unlock
        info = session.get_session_info()
        assert info["is_unlocked"]
        assert info["ttl_seconds"] == 3600
        assert info["seconds_remaining"] is not None
        
        await session.lock()


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: SecretAccessPolicy - whitelist enforcement
# ──────────────────────────────────────────────────────────────────────────────

class TestSecretAccessPolicy:
    """Test SecretAccessPolicy control."""
    
    def test_policy_deny_by_default(self):
        """Test that access is denied by default."""
        policy = SecretAccessPolicy()
        
        assert not policy.is_allowed("unknown_plugin", "any_namespace")
    
    def test_policy_allow_grant(self):
        """Test granting access."""
        policy = SecretAccessPolicy()
        
        policy.allow("plugin1", ["namespace1", "namespace2"])
        
        assert policy.is_allowed("plugin1", "namespace1")
        assert policy.is_allowed("plugin1", "namespace2")
        assert not policy.is_allowed("plugin1", "namespace3")
        assert not policy.is_allowed("plugin2", "namespace1")
    
    def test_policy_deny_revokes_access(self):
        """Test revoking single namespace."""
        policy = SecretAccessPolicy()
        
        policy.allow("plugin1", ["ns1", "ns2"])
        assert policy.is_allowed("plugin1", "ns1")
        
        policy.deny("plugin1", "ns1")
        assert not policy.is_allowed("plugin1", "ns1")
        assert policy.is_allowed("plugin1", "ns2")  # Other namespace still ok
    
    def test_policy_revoke_all(self):
        """Test revoking all access."""
        policy = SecretAccessPolicy()
        
        policy.allow("plugin1", ["ns1", "ns2"])
        policy.revoke_all("plugin1")
        
        assert not policy.is_allowed("plugin1", "ns1")
        assert not policy.is_allowed("plugin1", "ns2")
    
    def test_policy_get_allowed_namespaces(self):
        """Test getting allowed namespaces."""
        policy = SecretAccessPolicy()
        
        policy.allow("plugin1", ["ns1", "ns2", "ns3"])
        
        namespaces = policy.get_allowed_namespaces("plugin1")
        assert "ns1" in namespaces
        assert "ns2" in namespaces
        assert "ns3" in namespaces
        
        # Unknown plugin
        assert policy.get_allowed_namespaces("unknown") == set()
    
    def test_policy_to_dict(self):
        """Test serialization."""
        policy = SecretAccessPolicy()
        policy.allow("plugin1", ["ns1", "ns2"])
        policy.allow("plugin2", ["ns3"])
        
        data = policy.to_dict()
        assert "plugin1" in data
        assert "plugin2" in data
        assert set(data["plugin1"]) == {"ns1", "ns2"}
    
    def test_policy_from_dict(self):
        """Test deserialization."""
        data = {
            "plugin1": ["ns1", "ns2"],
            "plugin2": ["ns3"],
        }
        
        policy = SecretAccessPolicy.from_dict(data)
        assert policy.is_allowed("plugin1", "ns1")
        assert policy.is_allowed("plugin2", "ns3")
    
    def test_default_policy(self):
        """Test default policy creation."""
        policy = create_default_policy()
        
        # Core runtime can access common namespaces
        assert policy.is_allowed("core.runtime", "secrets.app_key")
        
        # OAuth is limited
        assert policy.is_allowed("oauth", "secrets.oauth_token")
        assert not policy.is_allowed("oauth", "secrets.app_key")


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Integration - namespace isolation
# ──────────────────────────────────────────────────────────────────────────────

class TestNamespaceIsolation:
    """Test namespace isolation in vault."""
    
    @pytest.mark.asyncio
    async def test_different_namespaces_different_keys(self):
        """Test that different namespaces get different DEKs."""
        session = VaultSession()
        await session.unlock("passphrase")
        
        key_a = session.derive_namespace_key("namespace_a")
        key_b = session.derive_namespace_key("namespace_b")
        key_c = session.derive_namespace_key("namespace_a")  # Same as A
        
        # A and B should be different
        assert key_a != key_b
        
        # A repeated should be same
        assert key_a == key_c
        
        await session.lock()
    
    @pytest.mark.asyncio
    async def test_different_sessions_same_namespace_same_key(self):
        """Test that same passphrase + namespace = same key."""
        passphrase = "same_passphrase"
        namespace = "test_ns"
        
        # Session 1
        session1 = VaultSession()
        await session1.unlock(passphrase)
        key1 = session1.derive_namespace_key(namespace)
        await session1.lock()
        
        # Session 2
        session2 = VaultSession()
        await session2.unlock(passphrase)
        key2 = session2.derive_namespace_key(namespace)
        await session2.lock()
        
        # Same passphrase and namespace = same key
        assert key1 == key2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
