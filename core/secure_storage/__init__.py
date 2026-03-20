"""
Secure Storage Package — P0 hardening for cold storage (Step 14).

Добавляет криптографическую защиту:
- Part B: Global Storage Epoch (rollback protection)
- Part C: Cryptographic state verification (Merkle root, signed)
- Part 4: Atomic transaction guarantee
- Part 5: Append-only audit log
- Part 6: Enforcement of secure writes for critical namespaces

Structure:
- wrapper.py: SecureStorageWrapper main class

For backward compatibility, SecureStorageWrapper is re-exported from this package.
"""

from core.secure_storage.wrapper import SecureStorageWrapper

__all__ = ["SecureStorageWrapper"]
