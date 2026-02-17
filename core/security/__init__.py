"""Step 14: Security module — Secure Secret Store."""

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
