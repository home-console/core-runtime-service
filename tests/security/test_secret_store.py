"""
flow: Tests for secure secret store.

Comprehensive security tests for:
- Encryption/decryption
- Key derivation
- Tamper detection
- Key rotation
- Memory safety
"""

import pytest
import json
from datetime import datetime, timezone

from modules.security.crypto import (
    generate_master_key,
    generate_salt,
    generate_nonce,
    derive_key_from_passphrase,
    hkdf_expand,
    encrypt,
    decrypt,
    constant_time_compare,
    MASTER_KEY_SIZE,
    DEK_SIZE,
    NONCE_SIZE,
    SALT_SIZE,
)
from modules.security.secret_store import (
    SecretStore,
    EncryptedSecret,
)


class InMemoryStorageAdapter:
    """In-memory storage for testing."""
    
    def __init__(self):
        self._data = {}
    
    async def set_async(self, key: str, value: str) -> None:
        self._data[key] = value
    
    async def get_async(self, key: str) -> str | None:
        return self._data.get(key)
    
    async def delete_async(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
    
    async def list_keys_async(self, pattern: str) -> list[str]:
        """List all keys matching pattern."""
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._data.keys() if k.startswith(prefix)]
        return list(self._data.keys())


# ============================================================================
# Crypto Primitives Tests
# ============================================================================

class TestCryptoPrimitives:
    """Test crypto primitives."""
    
    def test_generate_master_key(self):
        """Generate random master key."""
        key = generate_master_key()
        assert len(key) == MASTER_KEY_SIZE
        assert isinstance(key, bytes)
        
        # Two calls produce different keys
        key2 = generate_master_key()
        assert key != key2
    
    def test_generate_salt(self):
        """Generate random salt."""
        salt = generate_salt()
        assert len(salt) == SALT_SIZE
        assert isinstance(salt, bytes)
        
        salt2 = generate_salt()
        assert salt != salt2
    
    def test_generate_nonce(self):
        """Generate random nonce."""
        nonce = generate_nonce()
        assert len(nonce) == NONCE_SIZE
        assert isinstance(nonce, bytes)
        
        nonce2 = generate_nonce()
        assert nonce != nonce2
    
    def test_key_derivation_from_passphrase(self):
        """Derive key from passphrase."""
        passphrase = "my-super-secret-passphrase"
        key, salt = derive_key_from_passphrase(passphrase)
        
        assert len(key) == MASTER_KEY_SIZE
        assert len(salt) == SALT_SIZE
        assert isinstance(key, bytes)
        assert isinstance(salt, bytes)
    
    def test_key_derivation_deterministic(self):
        """Key derivation is deterministic with same salt."""
        passphrase = "test-passphrase"
        salt = generate_salt()
        
        key1, _ = derive_key_from_passphrase(passphrase, salt)
        key2, _ = derive_key_from_passphrase(passphrase, salt)
        
        assert key1 == key2
    
    def test_key_derivation_different_passphrase(self):
        """Different passphrases produce different keys."""
        salt = generate_salt()
        
        key1, _ = derive_key_from_passphrase("passphrase1", salt)
        key2, _ = derive_key_from_passphrase("passphrase2", salt)
        
        assert key1 != key2
    
    def test_key_derivation_short_passphrase_fails(self):
        """Short passphrases are rejected."""
        with pytest.raises(ValueError, match="at least 8 characters"):
            derive_key_from_passphrase("short")
    
    def test_hkdf_expand(self):
        """HKDF key expansion."""
        master_key = generate_master_key()
        dek = hkdf_expand(master_key, info=b"data_encryption_key")
        
        assert len(dek) == DEK_SIZE
        assert isinstance(dek, bytes)
    
    def test_hkdf_expand_deterministic(self):
        """HKDF expansion is deterministic."""
        master_key = generate_master_key()
        
        dek1 = hkdf_expand(master_key, info=b"dek")
        dek2 = hkdf_expand(master_key, info=b"dek")
        
        assert dek1 == dek2
    
    def test_hkdf_expand_different_info(self):
        """Different info produces different keys."""
        master_key = generate_master_key()
        
        dek1 = hkdf_expand(master_key, info=b"key1")
        dek2 = hkdf_expand(master_key, info=b"key2")
        
        assert dek1 != dek2
    
    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt and decrypt data."""
        plaintext = b"This is a secret message"
        key = generate_master_key()
        
        nonce, ciphertext, tag = encrypt(plaintext, key)
        recovered = decrypt(nonce, ciphertext, tag, key)
        
        assert recovered == plaintext
    
    def test_encrypt_unique_nonce(self):
        """Each encryption produces unique nonce."""
        plaintext = b"test"
        key = generate_master_key()
        
        nonce1, _, _ = encrypt(plaintext, key)
        nonce2, _, _ = encrypt(plaintext, key)
        
        assert nonce1 != nonce2
    
    def test_encrypt_unique_ciphertext(self):
        """Same plaintext + key produces different ciphertext (due to nonce)."""
        plaintext = b"test message"
        key = generate_master_key()
        
        _, ct1, _ = encrypt(plaintext, key)
        _, ct2, _ = encrypt(plaintext, key)
        
        assert ct1 != ct2  # Different due to different nonces
    
    def test_decrypt_wrong_key_fails(self):
        """Decryption with wrong key fails."""
        plaintext = b"secret"
        key1 = generate_master_key()
        key2 = generate_master_key()
        
        nonce, ciphertext, tag = encrypt(plaintext, key1)
        
        with pytest.raises(Exception):  # cryptography raises InvalidTag
            decrypt(nonce, ciphertext, tag, key2)
    
    def test_decrypt_tampered_ciphertext_fails(self):
        """Decryption detects tampered ciphertext."""
        plaintext = b"secret"
        key = generate_master_key()
        
        nonce, ciphertext, tag = encrypt(plaintext, key)
        
        # Tamper with ciphertext
        tampered = bytearray(ciphertext)
        tampered[0] ^= 0xFF
        
        with pytest.raises(Exception):  # InvalidTag
            decrypt(nonce, bytes(tampered), tag, key)
    
    def test_decrypt_tampered_tag_fails(self):
        """Decryption detects tampered tag."""
        plaintext = b"secret"
        key = generate_master_key()
        
        nonce, ciphertext, tag = encrypt(plaintext, key)
        
        # Tamper with tag
        tampered_tag = bytearray(tag)
        tampered_tag[0] ^= 0xFF
        
        with pytest.raises(Exception):  # InvalidTag
            decrypt(nonce, ciphertext, bytes(tampered_tag), key)
    
    def test_constant_time_compare_equal(self):
        """Constant-time comparison of equal values."""
        data = b"secret_data_1234"
        result = constant_time_compare(data, data)
        assert result is True
    
    def test_constant_time_compare_different(self):
        """Constant-time comparison of different values."""
        data1 = b"secret1"
        data2 = b"secret2"
        result = constant_time_compare(data1, data2)
        assert result is False
    
    def test_constant_time_compare_different_length(self):
        """Constant-time comparison of different lengths."""
        data1 = b"short"
        data2 = b"much_longer_data"
        result = constant_time_compare(data1, data2)
        assert result is False


# ============================================================================
# EncryptedSecret Tests
# ============================================================================

class TestEncryptedSecret:
    """Test EncryptedSecret dataclass."""
    
    def test_create_encrypted_secret(self):
        """Create encrypted secret."""
        secret = EncryptedSecret(
            nonce="aabbccdd",
            ciphertext="11223344",
            tag="55667788",
            created_at="2026-02-17T00:00:00",
            version=1,
        )
        
        assert secret.nonce == "aabbccdd"
        assert secret.version == 1
    
    def test_encrypted_secret_to_dict(self):
        """Convert encrypted secret to dict."""
        secret = EncryptedSecret(
            nonce="aa",
            ciphertext="bb",
            tag="cc",
            created_at="2026-02-17T00:00:00",
        )
        
        data = secret.to_dict()
        assert isinstance(data, dict)
        assert data["nonce"] == "aa"
        assert data["version"] == 1
    
    def test_encrypted_secret_from_dict(self):
        """Create encrypted secret from dict."""
        data = {
            "nonce": "aabbccdd",
            "ciphertext": "11223344",
            "tag": "55667788",
            "created_at": "2026-02-17T00:00:00",
            "version": 1,
        }
        
        secret = EncryptedSecret.from_dict(data)
        assert secret.nonce == "aabbccdd"
        assert secret.version == 1


# ============================================================================
# SecretStore Tests
# ============================================================================

class TestSecretStore:
    """Test SecretStore."""
    
    @pytest.fixture
    async def store(self):
        """Create secret store for testing."""
        adapter = InMemoryStorageAdapter()
        store = SecretStore(adapter)
        yield store
        await store.close()
    
    @pytest.mark.asyncio
    async def test_initialize_creates_keys(self, store):
        """Initialize creates master key and DEK."""
        assert not store._initialized
        
        await store.initialize("test-passphrase-1234")
        
        assert store._initialized
        assert store._master_key is not None
        assert store._dek is not None
        assert store._salt is not None
    
    @pytest.mark.asyncio
    async def test_initialize_idempotent_fails(self, store):
        """Can't initialize twice."""
        await store.initialize("passphrase")
        
        with pytest.raises(RuntimeError, match="already initialized"):
            await store.initialize("new-passphrase")
    
    @pytest.mark.asyncio
    async def test_put_get_roundtrip(self, store):
        """Store and retrieve secret."""
        await store.initialize("passphrase")
        
        secret = b"my-api-token-12345"
        await store.put("api:token", secret)
        
        retrieved = await store.get("api:token")
        assert retrieved == secret
    
    @pytest.mark.asyncio
    async def test_put_get_multiple_secrets(self, store):
        """Store and retrieve multiple secrets."""
        await store.initialize("passphrase")
        
        secrets = {
            "ssh:host1": b"ssh-password-1",
            "ssh:host2": b"ssh-password-2",
            "api:github": b"github-token",
        }
        
        for key, value in secrets.items():
            await store.put(key, value)
        
        for key, expected in secrets.items():
            actual = await store.get(key)
            assert actual == expected
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        """Get non-existent secret returns None."""
        await store.initialize("passphrase")
        
        result = await store.get("nonexistent")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_delete_secret(self, store):
        """Delete a secret."""
        await store.initialize("passphrase")
        
        await store.put("temp:secret", b"data")
        assert await store.get("temp:secret") == b"data"
        
        deleted = await store.delete("temp:secret")
        assert deleted is True
        
        assert await store.get("temp:secret") is None
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        """Deleting non-existent secret returns False."""
        await store.initialize("passphrase")
        
        result = await store.delete("nonexistent")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_exists_secret(self, store):
        """Check if secret exists."""
        await store.initialize("passphrase")
        
        await store.put("test", b"data")
        assert await store.exists("test") is True
        assert await store.exists("nonexistent") is False
    
    @pytest.mark.asyncio
    async def test_list_secrets(self, store):
        """List all secrets."""
        await store.initialize("passphrase")
        
        secrets = ["ssh:host1", "api:github", "db:password"]
        for secret_key in secrets:
            await store.put(secret_key, b"value")
        
        listed = await store.list_secrets()
        assert set(listed) == set(secrets)
    
    @pytest.mark.asyncio
    async def test_open_with_passphrase(self, store):
        """Reopen store with passphrase."""
        # First store
        await store.initialize("my-passphrase")
        await store.put("test", b"secret-value")
        await store.close()
        
        # Reopen with same passphrase
        store2 = SecretStore(store._storage)
        await store2.open_with_passphrase("my-passphrase")
        
        result = await store2.get("test")
        assert result == b"secret-value"
        
        await store2.close()
    
    @pytest.mark.asyncio
    async def test_open_with_wrong_passphrase_fails(self, store):
        """Wrong passphrase fails to decrypt."""
        await store.initialize("correct-passphrase")
        await store.put("test", b"secret")
        await store.close()
        
        # Try to reopen with wrong passphrase
        store2 = SecretStore(store._storage)
        await store2.open_with_passphrase("wrong-passphrase")
        
        # This should fail on decryption
        with pytest.raises(ValueError):
            await store2.get("test")
        
        await store2.close()
    
    @pytest.mark.asyncio
    async def test_encrypt_check_format(self, store):
        """Check encrypted data has correct format."""
        await store.initialize("passphrase")
        await store.put("test", b"secret")
        
        storage_key = "secrets.store.test"
        secret_json = await store._storage.get_async(storage_key)
        
        data = json.loads(secret_json)
        assert "nonce" in data
        assert "ciphertext" in data
        assert "tag" in data
        assert "created_at" in data
        assert "version" in data
        
        # Verify hex encoding
        assert isinstance(data["nonce"], str)
        bytes.fromhex(data["nonce"])  # Should not raise
    
    @pytest.mark.asyncio
    async def test_rotate_master_key(self, store):
        """Rotate master key (re-encrypt all secrets)."""
        await store.initialize("old-passphrase")
        
        # Store some secrets
        await store.put("secret1", b"value1")
        await store.put("secret2", b"value2")
        
        # Rotate key
        await store.rotate_master_key("new-passphrase")
        
        # Verify secrets still accessible
        assert await store.get("secret1") == b"value1"
        assert await store.get("secret2") == b"value2"
        
        # Close and reopen with new  passphrase
        await store.close()
        
        store2 = SecretStore(store._storage)
        await store2.open_with_passphrase("new-passphrase")
        
        assert await store2.get("secret1") == b"value1"
        await store2.close()
    
    @pytest.mark.asyncio
    async def test_get_metadata(self, store):
        """Get secret metadata without decryption."""
        await store.initialize("passphrase")
        await store.put("test", b"secret")
        
        metadata = await store.get_metadata("test")
        assert metadata is not None
        assert "created_at" in metadata
        assert "version" in metadata
        assert metadata["version"] == 1
    
    @pytest.mark.asyncio
    async def test_get_metadata_nonexistent(self, store):
        """Get metadata of non-existent secret."""
        await store.initialize("passphrase")
        
        metadata = await store.get_metadata("nonexistent")
        assert metadata is None
    
    @pytest.mark.asyncio
    async def test_put_uninitialized_fails(self, store):
        """Can't put before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.put("test", b"value")
    
    @pytest.mark.asyncio
    async def test_get_uninitialized_fails(self, store):
        """Can't get before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.get("test")
    
    @pytest.mark.asyncio
    async def test_different_nonces_per_secret(self, store):
        """Each secret has unique nonce."""
        await store.initialize("passphrase")
        
        await store.put("secret1", b"value1")
        await store.put("secret2", b"value2")
        
        # Get encrypted blobs
        blob1_json = await store._storage.get_async("secrets.store.secret1")
        blob2_json = await store._storage.get_async("secrets.store.secret2")
        
        blob1 = json.loads(blob1_json)
        blob2 = json.loads(blob2_json)
        
        assert blob1["nonce"] != blob2["nonce"]
    
    @pytest.mark.asyncio
    async def test_close_zeroizes_keys(self, store):
        """Close() zeroizes keys from memory."""
        await store.initialize("passphrase")
        
        # Verify keys are in memory
        assert store._master_key is not None
        assert store._dek is not None
        
        await store.close()
        
        # Verify keys are zeroized
        assert store._master_key is None
        assert store._dek is None
        assert store._initialized is False
    
    @pytest.mark.asyncio
    async def test_binary_secret_data(self, store):
        """Store and retrieve binary data."""
        await store.initialize("passphrase")
        
        # Binary data with null bytes
        binary_data = b"\x00\x01\x02\xff\xfe\xfd"
        await store.put("binary", binary_data)
        
        retrieved = await store.get("binary")
        assert retrieved == binary_data
    
    @pytest.mark.asyncio
    async def test_large_secret(self, store):
        """Store and retrieve large secret (1MB)."""
        await store.initialize("passphrase")
        
        large_data = b"x" * (1024 * 1024)  # 1MB
        await store.put("large", large_data)
        
        retrieved = await store.get("large")
        assert retrieved == large_data
    
    @pytest.mark.asyncio
    async def test_concurrent_reads(self, store):
        """Concurrent read operations."""
        import asyncio
        
        await store.initialize("passphrase")
        await store.put("test", b"value")
        
        async def read_secret():
            return await store.get("test")
        
        # Run 10 concurrent reads
        results = await asyncio.gather(*[read_secret() for _ in range(10)])
        
        for result in results:
            assert result == b"value"
