"""
Capability Registry Package (D2).

Metadata registry for capabilities:
- registry.py: CapabilityRegistry main class
- security.py: Trust-aware security checks and permission validation

For backward compatibility, CapabilityRegistry is re-exported from this package.
"""

from core.capability.registry import CapabilityRegistry
from core.capability.security import (
    CapabilitySecurityError,
    trust_level_to_privilege,
    check_capability_namespace_permission
)

# Private version for backward compatibility with old tests
_check_capability_namespace_permission = check_capability_namespace_permission

__all__ = [
    "CapabilityRegistry",
    "CapabilitySecurityError",
    "trust_level_to_privilege",
    "check_capability_namespace_permission",
    "_check_capability_namespace_permission"
]
