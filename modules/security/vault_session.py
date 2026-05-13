"""
Session-Based Vault Model with TTL.

- unlock(passphrase) → derive master key with Argon2id
- Store master key in SecureBuffer
- Auto-expire after TTL (default 900s = 15 min)
- Background asyncio task for expiration
- lock() zeroizes immediately
- DEK derived on demand from master key
"""

import asyncio
from typing import Optional, Awaitable
from datetime import datetime, timedelta, UTC
from contextlib import asynccontextmanager
import hashlib

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from modules.security.secure_memory import SecureBuffer, wipe_memory


class VaultLockedError(RuntimeError):
    """Vault is locked (session expired or never unlocked)."""
    pass


class SessionExpiredError(VaultLockedError):
    """Session expired."""
    pass


class VaultSession:
    """
    Session-based vault unlock model with TTL.
    
    Workflow:
    1. await vault.unlock(passphrase)
       → Derives master key with Argon2id
       → Stores in SecureBuffer
       → Starts expiration timer
    
    2. Use vault.secure_get/secure_put/derive_key
       → All operations require unlock state
       → Derive DEK on demand from master key
    
    3. Session expires after TTL
       → Master key is zeroized
       → Future operations fail with VaultLockedError
    
    4. Call vault.lock() explicitly
       → Zeroizes immediately
       → Idempotent (safe to call multiple times)
    
    Security properties:
    - Master key only in memory (locked with mlock)
    - DEK derived fresh each time (no caching)
    - Namespace isolation via HKDF-expand
    - Auto-cleanup on expiration
    """
    
    def __init__(
        self,
        ttl_seconds: int = 900,  # 15 minutes default
        argon2_time_cost: int = 2,
        argon2_memory_cost: int = 65536,  # 64MB
        argon2_parallelism: int = 4,
    ):
        """
        Initialize vault session (not unlocked yet).
        
        Args:
            ttl_seconds: Session TTL (default 15 min)
            argon2_time_cost: Argon2id time cost
            argon2_memory_cost: Argon2id memory cost (bytes)
            argon2_parallelism: Argon2id parallelism
        """
        self._master_key: Optional[SecureBuffer] = None
        self._ttl_seconds = ttl_seconds
        self._unlock_time: Optional[datetime] = None
        self._locked = False  # Explicit lock call
        self._expired = False  # TTL expiration
        self._expiration_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
        # Argon2id parameters
        self._argon2_time = argon2_time_cost
        self._argon2_memory = argon2_memory_cost
        self._argon2_parallel = argon2_parallelism
        
        # Derivation salt (fixed for determinism)
        self._derivation_salt = b"vault_session_kdf_v1"
    
    async def unlock(self, passphrase: str) -> None:
        """
        Unlock vault with passphrase.
        
        Derives 32-byte master key using Argon2id.
        Starts TTL expiration timer.
        
        Args:
            passphrase: User passphrase
            
        Raises:
            ValueError: if passphrase is empty
            RuntimeError: if unlock fails
        """
        async with self._lock:
            if not isinstance(passphrase, str):
                raise TypeError("passphrase must be string")
            
            if not passphrase:
                raise ValueError("passphrase cannot be empty")
            
            # Argon2id via argon2-cffi (same stack as modules.security.crypto).
            # hash_secret_raw expects bytes/str for the secret buffer, not bytearray.
            passphrase_bytes = passphrase.encode("utf-8")
            master_key_bytes = hash_secret_raw(
                passphrase_bytes,
                self._derivation_salt,
                time_cost=self._argon2_time,
                memory_cost=self._argon2_memory,
                parallelism=self._argon2_parallel,
                hash_len=32,
                type=Type.ID,
            )
            passphrase_bytes = b"\x00" * len(passphrase_bytes)
            del passphrase_bytes
            
            # Store in secure buffer (mlock + zeroize)
            self._master_key = SecureBuffer(master_key_bytes)
            
            # Wipe temporary
            wipe_memory(bytearray(master_key_bytes))
            
            # Set unlock time and clear expiration flags
            self._unlock_time = datetime.now(UTC)
            self._locked = False
            self._expired = False
            
            # Start expiration timer
            if self._expiration_task:
                self._expiration_task.cancel()
            self._expiration_task = asyncio.create_task(self._expiration_timer())
    
    async def lock(self) -> None:
        """
        Explicitly lock vault (zeroize master key).
        
        Idempotent - safe to call multiple times.
        """
        async with self._lock:
            if self._master_key:
                self._master_key.close()
                self._master_key = None
            
            self._locked = True
            
            if self._expiration_task:
                self._expiration_task.cancel()
                self._expiration_task = None
    
    async def _expiration_timer(self) -> None:
        """Background task for TTL expiration."""
        try:
            await asyncio.sleep(self._ttl_seconds)
            
            async with self._lock:
                if self._master_key:
                    self._master_key.close()
                    self._master_key = None
                
                self._expired = True
        except asyncio.CancelledError:
            pass
    
    def _check_unlocked(self) -> None:
        """Verify vault is unlocked."""
        if self._locked:
            raise VaultLockedError("Vault is explicitly locked")
        
        if self._expired:
            raise SessionExpiredError(f"Session expired (TTL: {self._ttl_seconds}s)")
        
        if not self._master_key:
            raise VaultLockedError("Vault is not unlocked")
    
    def is_unlocked(self) -> bool:
        """Check if vault is currently unlocked."""
        return (
            not self._locked and
            not self._expired and
            self._master_key is not None
        )
    
    def get_session_info(self) -> dict:
        """Get session info."""
        return {
            "is_unlocked": self.is_unlocked(),
            "is_locked": self._locked,
            "is_expired": self._expired,
            "ttl_seconds": self._ttl_seconds,
            "unlock_time": self._unlock_time.isoformat() if self._unlock_time else None,
            "seconds_remaining": self._get_seconds_remaining(),
        }
    
    def _get_seconds_remaining(self) -> Optional[int]:
        """Get seconds until session expires."""
        if not self._unlock_time or self._locked or self._expired:
            return None
        
        elapsed = (datetime.now(UTC) - self._unlock_time).total_seconds()
        remaining = max(0, self._ttl_seconds - elapsed)
        return int(remaining)
    
    def derive_namespace_key(self, namespace: str, key_length: int = 32) -> bytes:
        """
        Derive namespace-specific DEK from master key.
        
        Uses HKDF-expand with namespace as info.
        Each namespace gets unique key derived from same master.
        
        Args:
            namespace: namespace identifier
            key_length: desired key length (default 32)
            
        Returns:
            Derived key bytes
            
        Raises:
            VaultLockedError: if vault not unlocked
        """
        self._check_unlocked()
        
        if not isinstance(namespace, str):
            raise TypeError("namespace must be string")
        
        if key_length <= 0 or key_length > 32:
            raise ValueError("key_length must be 1-32")
        
        # HKDF-expand with namespace as info
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=key_length,
            salt=self._derivation_salt,
            info=namespace.encode('utf-8'),
            backend=default_backend(),
        )
        
        return hkdf.derive(self._master_key.bytes)
    
    async def ensure_unlocked(self) -> None:
        """Ensure vault is unlocked, raise otherwise."""
        self._check_unlocked()
    
    @asynccontextmanager
    async def transaction(self):
        """
        Context manager for session operations.
        
        Ensures vault remains unlocked for duration of block.
        Raises VaultLockedError if expires during transaction.
        """
        self._check_unlocked()
        try:
            yield self
        finally:
            # Verify still unlocked (transaction didn't cause expiration)
            if not self.is_unlocked():
                raise SessionExpiredError("Session expired during transaction")
