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

from importlib import util as importlib_util
from pathlib import Path

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


def _load_legacy_security_helpers():
    legacy_path = Path(__file__).resolve().parents[1] / "security.py"
    spec = importlib_util.spec_from_file_location("_core_security_legacy", legacy_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_legacy_security = _load_legacy_security_helpers()

# Keep re-exported TOTP helpers and MFA enums referenced so Pylance treats
# them as part of the public facade rather than dead imports.
_ = (generate_totp, verify_totp, MFAMethodNotSupported)

if _legacy_security is not None:
    sanitize_for_logging = _legacy_security.sanitize_for_logging
    sanitize_headers = _legacy_security.sanitize_headers
    TokenEncryption = _legacy_security.TokenEncryption
    CSRFProtection = _legacy_security.CSRFProtection
else:
    def sanitize_for_logging(data, mask="***REDACTED***"):
        if isinstance(data, dict):
            return {k: (mask if any(s in k.lower() for s in ["password", "token", "secret", "key"]) else sanitize_for_logging(v, mask)) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return type(data)(sanitize_for_logging(item, mask) for item in data)
        return data

    def sanitize_headers(headers):
        return sanitize_for_logging(headers)

    TokenEncryption = None
    CSRFProtection = None


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

