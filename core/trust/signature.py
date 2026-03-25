"""Legacy compatibility wrapper for trust signature helpers."""

import warnings

warnings.warn(
    "core.trust.signature is deprecated; use core.security.trust.signature instead",
    DeprecationWarning,
    stacklevel=2,
)

from modules.security.trust.signature import (
    SignatureError,
    compute_archive_sha256,
    compute_payload_hash,
    generate_keypair,
    sign_message,
    verify_signature,
)

__all__ = [
    "SignatureError",
    "generate_keypair",
    "sign_message",
    "verify_signature",
    "compute_payload_hash",
    "compute_archive_sha256",
]
