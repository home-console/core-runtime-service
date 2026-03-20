"""
Capability Registry — backward compatibility re-export.

All capabilities are now in core.capability package.
This module kept for backward compatibility with existing imports.
"""

import warnings

warnings.warn(
    "core.capability_registry is deprecated; use core.capability instead",
    DeprecationWarning,
    stacklevel=2,
)

from core.capability import (
    CapabilityRegistry,
    CapabilitySecurityError,
    trust_level_to_privilege,
    _check_capability_namespace_permission
)

__all__ = [
    "CapabilityRegistry",
    "CapabilitySecurityError",
    "trust_level_to_privilege",
    "_check_capability_namespace_permission"
]
