"""Step 14: Security module — Secure Secret Store."""

# Import sanitize_for_logging from parent module
try:
    from ..security import sanitize_for_logging
except ImportError:
    # Fallback: define simple version if parent module unavailable
    def sanitize_for_logging(data, mask="***REDACTED***"):
        """Simple sanitize function."""
        if isinstance(data, dict):
            return {k: (mask if any(s in k.lower() for s in ["password", "token", "secret", "key"]) else sanitize_for_logging(v, mask)) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return type(data)(sanitize_for_logging(item, mask) for item in data)
        return data

from core.security.crypto import (
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
from core.security.secret_store import (
    SecretStore,
    EncryptedSecret,
)
from core.security.tpm import (
    TPMSealer,
    TPMUnavailableError,
    OptionalTPMSecretStore,
)

__all__ = [
    # Sanitization
    "sanitize_for_logging",
    # Crypto primitives
    "generate_master_key",
    "generate_nonce",
    "generate_salt",
    "derive_key_from_passphrase",
    "hkdf_expand",
    "encrypt",
    "decrypt",
    "constant_time_compare",
    "zeroize",
    # Constants
    "MASTER_KEY_SIZE",
    "DEK_SIZE",
    "NONCE_SIZE",
    "SALT_SIZE",
    "TAG_SIZE",
    # Secret Store
    "SecretStore",
    "EncryptedSecret",
    # TPM
    "TPMSealer",
    "TPMUnavailableError",
    "OptionalTPMSecretStore",
]
