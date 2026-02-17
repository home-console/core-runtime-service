"""
Trust Layer — Cryptographic plugin authentication and authorization.

Provides:
- Ed25519 signature verification
- Trusted key store management
- Plugin trust verification
- Capability security rules

Public API:
- PluginTrustVerifier - verify plugin signatures
- TrustStore - manage trusted keys
- TrustLevel - trust levels (core, publisher, developer)
"""

from core.trust.signature import (
    generate_keypair,
    sign_message,
    verify_signature,
    compute_payload_hash,
    compute_archive_sha256,
    SignatureError
)

from core.trust.trust_store import (
    TrustStore,
    TrustLevel,
    TrustError
)

from core.trust.verifier import (
    PluginTrustVerifier,
    PluginTrustError
)

__all__ = [
    'generate_keypair',
    'sign_message',
    'verify_signature',
    'compute_payload_hash',
    'compute_archive_sha256',
    'SignatureError',
    'TrustStore',
    'TrustLevel',
    'TrustError',
    'PluginTrustVerifier',
    'PluginTrustError'
]
