"""
Cryptographic primitives for secure secret storage.

AES-256-GCM encryption with:
- Argon2id key derivation
- HKDF expansion
- Constant-time operations
- Memory zeroization
"""

import os
import secrets
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from argon2.low_level import hash_secret_raw, Type
import hashlib


# Constants
MASTER_KEY_SIZE = 32  # 256 bits
DEK_SIZE = 32  # 256 bits for AES-256
NONCE_SIZE = 12  # 96 bits for GCM (standard)
SALT_SIZE = 32  # 256 bits
TAG_SIZE = 16  # 128 bits for GCM

# Argon2id parameters
ARGON2_MEMORY_COST = 64 * 1024  # 64 MB
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 4


def generate_master_key() -> bytes:
    """Generate a random master key (256 bits)."""
    return secrets.token_bytes(MASTER_KEY_SIZE)


def generate_nonce() -> bytes:
    """Generate a random nonce for GCM (96 bits - 12 bytes)."""
    return secrets.token_bytes(NONCE_SIZE)


def generate_salt() -> bytes:
    """Generate a random salt for key derivation."""
    return secrets.token_bytes(SALT_SIZE)


def derive_key_from_passphrase(
    passphrase: str,
    salt: bytes | None = None,
) -> Tuple[bytes, bytes]:
    """
    Derive a master key from passphrase using Argon2id.
    
    Args:
        passphrase: User passphrase
        salt: Optional salt (generated if not provided)
        
    Returns:
        (derived_key, salt) tuple
    """
    if salt is None:
        salt = generate_salt()
    
    if not isinstance(passphrase, str):
        raise TypeError("Passphrase must be string")
    
    if len(passphrase) < 8:
        raise ValueError("Passphrase must be at least 8 characters")
    
    passphrase_bytes = passphrase.encode('utf-8')
    
    # Use Argon2id for key derivation via argon2-cffi
    # hash_secret_raw returns raw binary output (not encoded)
    raw_hash = hash_secret_raw(
        passphrase_bytes,
        salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=MASTER_KEY_SIZE,
        type=Type.ID,
    )
    
    # Zeroize passphrase from memory
    passphrase_bytes = b'\x00' * len(passphrase_bytes)
    del passphrase_bytes
    
    return raw_hash, salt


def hkdf_expand(
    master_key: bytes,
    info: bytes | None = None,
    length: int = DEK_SIZE,
) -> bytes:
    """
    Expand master key using HKDF (no salt = all-zeros salt).
    
    Args:
        master_key: Master key to expand
        info: Context info (e.g., b"data_encryption_key")
        length: Output key length
        
    Returns:
        Expanded key
    """
    if info is None:
        info = b""
    
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,  # Use zero salt
        info=info,
        backend=default_backend(),
    )
    
    return hkdf.derive(master_key)


def encrypt(data: bytes, key: bytes) -> Tuple[bytes, bytes, bytes]:
    """
    Encrypt data using AES-256-GCM.
    
    Args:
        data: Plaintext to encrypt
        key: Encryption key (32 bytes for AES-256)
        
    Returns:
        (nonce, ciphertext, tag) tuple
        
    Raises:
        ValueError: If key is not 32 bytes
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")
    
    nonce = generate_nonce()
    cipher = AESGCM(key)
    
    # AESGCM.encrypt returns ciphertext + tag concatenated
    # We need to split them
    ciphertext_and_tag = cipher.encrypt(nonce, data, None)
    
    # Last 16 bytes is the tag, rest is ciphertext
    ciphertext = ciphertext_and_tag[:-TAG_SIZE]
    tag = ciphertext_and_tag[-TAG_SIZE:]
    
    return nonce, ciphertext, tag


def decrypt(
    nonce: bytes,
    ciphertext: bytes,
    tag: bytes,
    key: bytes,
) -> bytes:
    """
    Decrypt data using AES-256-GCM.
    
    Args:
        nonce: The nonce used for encryption
        ciphertext: Encrypted data (without tag)
        tag: Authentication tag
        key: Decryption key (32 bytes for AES-256)
        
    Returns:
        Decrypted plaintext
        
    Raises:
        cryptography.exceptions.InvalidTag: If authentication fails
        ValueError: If key is not 32 bytes
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes, got {len(key)}")
    
    if len(nonce) != NONCE_SIZE:
        raise ValueError(f"Nonce must be {NONCE_SIZE} bytes, got {len(nonce)}")
    
    if len(tag) != TAG_SIZE:
        raise ValueError(f"Tag must be {TAG_SIZE} bytes, got {len(tag)}")
    
    cipher = AESGCM(key)
    
    # Combine ciphertext and tag for decrypt
    ciphertext_and_tag = ciphertext + tag
    
    # AESGCM.decrypt verifies tag and raises InvalidTag on failure
    plaintext = cipher.decrypt(nonce, ciphertext_and_tag, None)
    
    return plaintext


def constant_time_compare(a: bytes, b: bytes) -> bool:
    """
    Compare two byte strings in constant time.
    
    Args:
        a: First bytes
        b: Second bytes
        
    Returns:
        True if equal, False otherwise
    """
    return len(a) == len(b) and secrets.compare_digest(a, b)


def zeroize(data: bytearray) -> None:
    """
    Zeroize sensitive data in memory.
    
    Args:
        data: Bytearray to zeroize
    """
    if isinstance(data, bytearray):
        for i in range(len(data)):
            data[i] = 0
