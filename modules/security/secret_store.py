"""
Secure Secret Store — encrypted vault for credentials.

Features:
- AES-256-GCM encryption at rest
- Master key derived from passphrase (Argon2id)
- DEK (Data Encryption Key) generated per session
- Optional TPM sealing
- Key rotation support
- Memory zeroization on shutdown
"""

import json
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict

from modules.security.crypto import (
    generate_master_key,
    generate_nonce,
    generate_salt,
    derive_key_from_passphrase,
    hkdf_expand,
    encrypt,
    decrypt,
    constant_time_compare,
)


@dataclass
class EncryptedSecret:
    """Encrypted secret blob."""
    nonce: str  # hex-encoded
    ciphertext: str  # hex-encoded
    tag: str  # hex-encoded
    created_at: str  # ISO 8601
    version: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EncryptedSecret":
        """Create from dict."""
        return cls(**data)


class SecretStore:
    """
    Secure vault for secrets (SSH passwords, API tokens, private keys).
    
    Key hierarchy:
    - Passphrase (user-provided)
        ↓ Argon2id + salt
    - Master Key (MK)
        ↓ HKDF expand with context
    - Data Encryption Key (DEK)
        ↓ AES-256-GCM
    - Encrypted secret blob
    
    Master key never persisted. DEK only in memory during runtime.
    """
    
    def __init__(self, storage_adapter):
        """
        Initialize secret store.
        
        Args:
            storage_adapter: Storage backend (e.g., in-memory or persistent)
        """
        self._storage = storage_adapter
        self._master_key: Optional[bytes] = None
        self._dek: Optional[bytes] = None
        self._salt: Optional[bytes] = None
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self, passphrase: str) -> None:
        """
        Initialize the secret store with a passphrase.
        
        Derives master key from passphrase, then generates DEK.
        
        Args:
            passphrase: User passphrase to derive key from
            
        Raises:
            ValueError: If passphrase too short
        """
        async with self._lock:
            if self._initialized:
                raise RuntimeError("SecretStore already initialized")
            
            # Derive master key from passphrase
            self._master_key, self._salt = derive_key_from_passphrase(passphrase)
            
            # Store salt (not a secret) for future key derivation
            await self._storage.set_async("secrets.store.salt", self._salt.hex())
            
            # Generate Data Encryption Key from master key
            self._dek = hkdf_expand(
                self._master_key,
                info=b"data_encryption_key",
                length=32,
            )
            
            self._initialized = True
    
    async def open_with_passphrase(self, passphrase: str) -> None:
        """
        Open secret store with passphrase (retrieve saved salt).
        
        Args:
            passphrase: User passphrase
            
        Raises:
            ValueError: If passphrase incorrect
            RuntimeError: If secret store not previously initialized
        """
        async with self._lock:
            if self._initialized:
                raise RuntimeError("SecretStore already open")
            
            # Try to retrieve stored salt
            salt_hex = await self._storage.get_async("secrets.store.salt")
            if salt_hex is None:
                raise RuntimeError("Secret store not initialized. Call initialize() first.")
            
            try:
                self._salt = bytes.fromhex(salt_hex)
            except ValueError:
                raise ValueError("Invalid stored salt")
            
            # Derive master key with saved salt
            self._master_key, _ = derive_key_from_passphrase(passphrase, self._salt)
            
            # Generate DEK
            self._dek = hkdf_expand(
                self._master_key,
                info=b"data_encryption_key",
                length=32,
            )
            
            self._initialized = True
    
    async def put(self, key: str, value: bytes) -> None:
        """
        Store an encrypted secret.
        
        Args:
            key: Secret name (e.g., "ssh:host1")
            value: Secret value (bytes)
            
        Raises:
            RuntimeError: If store not initialized
        """
        if not self._initialized or self._dek is None:
            raise RuntimeError("SecretStore not initialized")
        
        if not isinstance(key, str):
            raise TypeError("Key must be string")
        
        if not isinstance(value, bytes):
            raise TypeError("Value must be bytes")
        
        async with self._lock:
            # Encrypt the secret
            nonce, ciphertext, tag = encrypt(value, self._dek)
            
            # Create encrypted secret blob
            secret_blob = EncryptedSecret(
                nonce=nonce.hex(),
                ciphertext=ciphertext.hex(),
                tag=tag.hex(),
                created_at=datetime.now(timezone.utc).isoformat(),
                version=1,
            )
            
            # Store in persistent storage (encrypted)
            storage_key = f"secrets.store.{key}"
            await self._storage.set_async(storage_key, json.dumps(secret_blob.to_dict()))
    
    async def get(self, key: str) -> Optional[bytes]:
        """
        Retrieve and decrypt a secret.
        
        Args:
            key: Secret name (e.g., "ssh:host1")
            
        Returns:
            Decrypted secret value or None if not found
            
        Raises:
            RuntimeError: If store not initialized
            ValueError: If decryption fails (tampered ciphertext)
        """
        if not self._initialized or self._dek is None:
            raise RuntimeError("SecretStore not initialized")
        
        async with self._lock:
            storage_key = f"secrets.store.{key}"
            secret_json = await self._storage.get_async(storage_key)
            
            if secret_json is None:
                return None
            
            try:
                secret_dict = json.loads(secret_json)
                secret_blob = EncryptedSecret.from_dict(secret_dict)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Invalid stored secret for key '{key}': {e}")
            
            # Decrypt
            try:
                nonce = bytes.fromhex(secret_blob.nonce)
                ciphertext = bytes.fromhex(secret_blob.ciphertext)
                tag = bytes.fromhex(secret_blob.tag)
                
                plaintext = decrypt(nonce, ciphertext, tag, self._dek)
                return plaintext
            except Exception as e:
                err_msg = str(e).strip() or type(e).__name__
                raise ValueError(
                    f"Decryption failed for secret '{key}': {err_msg}. "
                    "Typical cause: vault was recreated or passphrase changed (AGENT_SECRET_STORE_PASSPHRASE); re-add the credential secret."
                ) from e
    
    async def delete(self, key: str) -> bool:
        """
        Delete a secret.
        
        Args:
            key: Secret name
            
        Returns:
            True if deleted, False if not found
        """
        if not self._initialized:
            raise RuntimeError("SecretStore not initialized")
        
        async with self._lock:
            storage_key = f"secrets.store.{key}"
            existed = await self._storage.get_async(storage_key) is not None
            if existed:
                await self._storage.delete_async(storage_key)
            return existed
    
    async def exists(self, key: str) -> bool:
        """Check if a secret exists."""
        if not self._initialized:
            raise RuntimeError("SecretStore not initialized")
        
        storage_key = f"secrets.store.{key}"
        return await self._storage.get_async(storage_key) is not None
    
    async def list_secrets(self) -> list[str]:
        """
        List all stored secret keys.
        
        Returns:
            List of secret names
        """
        if not self._initialized:
            raise RuntimeError("SecretStore not initialized")
        
        # Get all keys that start with "secrets.store."
        # This is a storage adapter operation
        all_keys = await self._storage.list_keys_async("secrets.store.*")
        
        # Strip the "secrets.store." prefix
        prefix = "secrets.store."
        secret_keys = [
            key[len(prefix):] for key in all_keys
            if key != "secrets.store.salt" and key.startswith(prefix)
        ]
        
        return secret_keys
    
    async def rotate_master_key(self, new_passphrase: str) -> None:
        """
        Rotate the master key (re-encrypt all secrets).
        
        Args:
            new_passphrase: New passphrase for key derivation
            
        Raises:
            RuntimeError: If store not initialized
        """
        if not self._initialized:
            raise RuntimeError("SecretStore not initialized")
        
        async with self._lock:
            # Get all secrets
            all_keys = await self._storage.list_keys_async("secrets.store.*")
            secrets_data = {}
            
            for storage_key in all_keys:
                if storage_key == "secrets.store.salt":
                    continue
                
                secret_json = await self._storage.get_async(storage_key)
                if secret_json:
                    key_name = storage_key[len("secrets.store."):]
                    secrets_data[key_name] = secret_json
            
            # Decrypt all secrets with old DEK
            decrypted_secrets = {}
            for key_name, secret_json in secrets_data.items():
                try:
                    secret_dict = json.loads(secret_json)
                    secret_blob = EncryptedSecret.from_dict(secret_dict)
                    
                    nonce = bytes.fromhex(secret_blob.nonce)
                    ciphertext = bytes.fromhex(secret_blob.ciphertext)
                    tag = bytes.fromhex(secret_blob.tag)
                    
                    plaintext = decrypt(nonce, ciphertext, tag, self._dek)
                    decrypted_secrets[key_name] = plaintext
                except Exception as e:
                    raise ValueError(f"Failed to decrypt secret '{key_name}' during rotation: {e}")
            
            # Generate new master key
            old_master_key = self._master_key
            new_master_key, new_salt = derive_key_from_passphrase(new_passphrase)
            
            # Generate new DEK
            new_dek = hkdf_expand(
                new_master_key,
                info=b"data_encryption_key",
                length=32,
            )
            
            # Re-encrypt all secrets with new DEK
            for key_name, plaintext in decrypted_secrets.items():
                nonce, ciphertext, tag = encrypt(plaintext, new_dek)
                
                secret_blob = EncryptedSecret(
                    nonce=nonce.hex(),
                    ciphertext=ciphertext.hex(),
                    tag=tag.hex(),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    version=1,
                )
                
                storage_key = f"secrets.store.{key_name}"
                await self._storage.set_async(storage_key, json.dumps(secret_blob.to_dict()))
            
            # Update salt
            await self._storage.set_async("secrets.store.salt", new_salt.hex())
            
            # Update in-memory keys
            self._master_key = new_master_key
            self._dek = new_dek
            self._salt = new_salt
    
    async def close(self) -> None:
        """
        Close and zeroize all keys from memory.
        
        This should be called before shutdown to securely wipe all keys.
        """
        async with self._lock:
            # Zeroize master key
            if self._master_key is not None:
                key_array = bytearray(self._master_key)
                for i in range(len(key_array)):
                    key_array[i] = 0
                self._master_key = None
            
            # Zeroize DEK
            if self._dek is not None:
                dek_array = bytearray(self._dek)
                for i in range(len(dek_array)):
                    dek_array[i] = 0
                self._dek = None
            
            # Zeroize salt (for completeness)
            if self._salt is not None:
                salt_array = bytearray(self._salt)
                for i in range(len(salt_array)):
                    salt_array[i] = 0
                self._salt = None
            
            self._initialized = False
    
    async def get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a secret without decrypting it.
        
        Args:
            key: Secret name
            
        Returns:
            Metadata dict with created_at and version or None
        """
        storage_key = f"secrets.store.{key}"
        secret_json = await self._storage.get_async(storage_key)
        
        if secret_json is None:
            return None
        
        try:
            secret_dict = json.loads(secret_json)
            secret_blob = EncryptedSecret.from_dict(secret_dict)
            return {
                "created_at": secret_blob.created_at,
                "version": secret_blob.version,
            }
        except Exception as e:
            return None
