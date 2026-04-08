"""
Core security facade.

This package is the canonical public API for all security-related primitives
used by the kernel and modules:
- secure memory / hardening / session controls
- secrets storage and adapters
- rate limiting and sanitization
- CSRF and token encryption helpers
- RBAC / MFA / risk / trust policy engines
"""

from .check_env import check_security_env
from .crypto import (
    MASTER_KEY_SIZE,
    DEK_SIZE,
    NONCE_SIZE,
    SALT_SIZE,
    TAG_SIZE,
    constant_time_compare,
    decrypt,
    derive_key_from_passphrase,
    encrypt,
    generate_master_key,
    generate_nonce,
    generate_salt,
    hkdf_expand,
    zeroize,
)
from .mfa import (
    ElevationSession,
    ElevationSessionExpired,
    ElevationSessionInvalid,
    ElevationSessionManager,
    MFAFailed,
    MFAMethod,
    MFAMethodNotSupported,
    MFANotConfigured,
    MFARequired,
    MFAVerificationResult,
    MFAService,
    PasskeyMethod,
    RateLimitExceeded,
    TOTPMethod,
    WebAuthnMethod,
    generate_totp,
    verify_totp,
)
from .policy_engine import CredentialPolicyEngine, PolicyStore
from .rate_limiter import RateLimiter
from .rbac_models import AccessDecision, CredentialAccessLevel, CredentialPolicy, Role
from .risk import EventType, RiskAction, RiskAssessment, RiskConfig, RiskEngine, RiskEvent, RiskMemory, RiskPolicy
from .secret_policy import SecretAccessPolicy, SecretAccessDenied, create_default_policy
from .secret_store import EncryptedSecret, SecretStore
from .secret_store_adapter import SecretStoreStorageAdapter
from .secure_memory import SecureBuffer, SecureBytes, wipe_memory
from .trust import TrustAction, TrustConfig, TrustConfigs, TrustDecision, TrustEngine, TrustLevel, TrustPolicy, TrustState
from .vault_hardening import HardeningStatus, VaultHardening
from .vault_session import SessionExpiredError, VaultLockedError, VaultSession

# Re-export from sdk.security for backward compatibility
from sdk.security import (
    SENSITIVE_KEYS,
    TokenEncryption,
    sanitize_for_logging,
    sanitize_headers,
)

# Re-export CSRF from api.csrf_protection for backward compatibility
from modules.api.csrf_protection import CSRFProtection


__all__ = [
    "RateLimiter",
    "SecureBuffer",
    "SecureBytes",
    "wipe_memory",
    "VaultHardening",
    "HardeningStatus",
    "VaultSession",
    "VaultLockedError",
    "SessionExpiredError",
    "SecretAccessPolicy",
    "SecretAccessDenied",
    "create_default_policy",
    "sanitize_for_logging",
    "sanitize_headers",
    "TokenEncryption",
    "CSRFProtection",
    "check_security_env",
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
    "SecretStoreStorageAdapter",
    "Role",
    "CredentialAccessLevel",
    "CredentialPolicy",
    "AccessDecision",
    "CredentialPolicyEngine",
    "PolicyStore",
    "MFAMethod",
    "MFAVerificationResult",
    "TOTPMethod",
    "WebAuthnMethod",
    "PasskeyMethod",
    "ElevationSession",
    "ElevationSessionManager",
    "MFAService",
    "MFARequired",
    "MFAFailed",
    "MFANotConfigured",
    "MFAMethodNotSupported",
    "RateLimitExceeded",
    "ElevationSessionExpired",
    "ElevationSessionInvalid",
    "RiskEvent",
    "RiskAssessment",
    "RiskAction",
    "EventType",
    "RiskConfig",
    "RiskMemory",
    "RiskPolicy",
    "RiskEngine",
    "TrustLevel",
    "TrustAction",
    "TrustState",
    "TrustDecision",
    "TrustConfig",
    "TrustConfigs",
    "TrustPolicy",
    "TrustEngine",
]

