"""
Canonical bridge for legacy cryptographic trust layer.

This module provides a security-domain import path for the existing
cryptographic trust implementation currently located under core.trust.*.
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
