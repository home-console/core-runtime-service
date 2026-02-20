"""
Security Module for Vault - Step 14 & Step 16.

Step 14: Secure Secret Store (encryption, TPM sealing)
Step 16: Linux-first Hardened Vault (mlock, hardening, sessions)

Components:
- secure_memory: mlock, MADV_DONTDUMP, SecureBuffer
- vault_hardening: core dump disable, ptrace disable, mlockall
- vault_session: TTL-based unlock model with Argon2id
- secret_policy: namespace access control (whitelist)
"""

# Rate limiting (API middleware)
from .rate_limiter import RateLimiter

# Step 16 imports
from .secure_memory import SecureBuffer, SecureBytes, wipe_memory
from .vault_hardening import VaultHardening, HardeningStatus
from .vault_session import VaultSession, VaultLockedError, SessionExpiredError
from .secret_policy import SecretAccessPolicy, SecretAccessDenied, create_default_policy

# Step 14 imports (legacy, if available)
try:
    from .crypto import (
        generate_master_key,
        generate_nonce,
        generate_salt,
        derive_key_from_passphrase,
        hkdf_expand,
        encrypt,
        decrypt,
        constant_time_compare,
        zeroize,
        MASTER_KEY_SIZE,
        DEK_SIZE,
        NONCE_SIZE,
        SALT_SIZE,
        TAG_SIZE,
    )
except ImportError:
    pass

try:
    from .secret_store import (
        SecretStore,
        EncryptedSecret,
    )
except ImportError:
    pass

try:
    from .tpm import (
        TPMSealer,
        TPMUnavailableError,
        OptionalTPMSecretStore,
    )
except ImportError:
    pass

def sanitize_for_logging(data, mask="***REDACTED***"):
    """Simple sanitize function for logging."""
    if isinstance(data, dict):
        return {k: (mask if any(s in k.lower() for s in ["password", "token", "secret", "key"]) else sanitize_for_logging(v, mask)) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return type(data)(sanitize_for_logging(item, mask) for item in data)
    return data

__all__ = [
    # Rate limiting
    "RateLimiter",
    # Step 16 - Secure Memory
    "SecureBuffer",
    "SecureBytes",
    "wipe_memory",
    # Step 16 - Hardening
    "VaultHardening",
    "HardeningStatus",
    # Step 16 - Sessions
    "VaultSession",
    "VaultLockedError",
    "SessionExpiredError",
    # Step 16 - Policies
    "SecretAccessPolicy",
    "SecretAccessDenied",
    "create_default_policy",
    # Utilities
    "sanitize_for_logging",
    # Step 14 items (if available)
    "generate_master_key",
    "generate_nonce",
    "generate_salt",
    "derive_key_from_passphrase",
    "hkdf_expand",
    "encrypt",
    "decrypt",
    "constant_time_compare",
    "zeroize",
    "MASTER_KEY_SIZE",
    "DEK_SIZE",
    "NONCE_SIZE",
    "SALT_SIZE",
    "TAG_SIZE",
    "SecretStore",
    "EncryptedSecret",
    "TPMSealer",
    "TPMUnavailableError",
    "OptionalTPMSecretStore",
]

# Step 17.4 RBAC imports
try:
    from .rbac_models import (
        Role,
        CredentialAccessLevel,
        CredentialPolicy,
        AccessDecision,
    )
    from .policy_engine import (
        CredentialPolicyEngine,
        PolicyStore,
    )
    
    __all__.extend([
        "Role",
        "CredentialAccessLevel",
        "CredentialPolicy",
        "AccessDecision",
        "CredentialPolicyEngine",
        "PolicyStore",
    ])
except ImportError:
    pass  # RBAC optional in security module

