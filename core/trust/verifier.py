"""Legacy compatibility wrapper for trust verifier helpers."""

import warnings

warnings.warn(
    "core.trust.verifier is deprecated; use core.security.trust.verifier instead",
    DeprecationWarning,
    stacklevel=2,
)

from core.security.trust.verifier import PluginTrustError, PluginTrustVerifier

__all__ = ["PluginTrustVerifier", "PluginTrustError"]
