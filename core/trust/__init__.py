"""Legacy compatibility wrapper for trust package exports."""

import warnings

warnings.warn(
    "core.trust is deprecated; use core.security.trust.legacy_crypto instead",
    DeprecationWarning,
    stacklevel=2,
)

from modules.security.trust.legacy_crypto import (
    PluginTrustError,
    PluginTrustVerifier,
    SignatureError,
    TrustError,
    TrustLevel,
    TrustStore,
    compute_archive_sha256,
    compute_payload_hash,
    generate_keypair,
    sign_message,
    verify_signature,
)

__all__ = [
    "generate_keypair",
    "sign_message",
    "verify_signature",
    "compute_payload_hash",
    "compute_archive_sha256",
    "SignatureError",
    "TrustStore",
    "TrustLevel",
    "TrustError",
    "PluginTrustVerifier",
    "PluginTrustError",
]
