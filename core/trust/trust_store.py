"""Legacy compatibility wrapper for trust store helpers."""

import warnings

warnings.warn(
    "core.trust.trust_store is deprecated; use core.security.trust.trust_store instead",
    DeprecationWarning,
    stacklevel=2,
)

from modules.security.trust.trust_store import TrustError, TrustLevel, TrustStore

__all__ = ["TrustStore", "TrustLevel", "TrustError"]
