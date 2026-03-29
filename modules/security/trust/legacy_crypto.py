"""
Canonical bridge for cryptographic trust helpers.

This module exposes a stable import path for the security-domain
cryptographic trust implementation in `modules.security.trust.*`.
"""

from modules.security.trust.signature import (
    generate_keypair,
    sign_message,
    verify_signature,
    compute_payload_hash,
    compute_archive_sha256,
    SignatureError,
)
from modules.security.trust.trust_store import (
    TrustStore,
    TrustLevel,
    TrustError,
)
from modules.security.trust.verifier import (
    PluginTrustVerifier,
    PluginTrustError,
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
