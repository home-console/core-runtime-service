"""Capability registry package moved out of core."""

from modules.capability.registry import CapabilityRegistry
from modules.capability.security import (
    CapabilitySecurityError,
    check_capability_namespace_permission,
    trust_level_to_privilege,
)

_check_capability_namespace_permission = check_capability_namespace_permission

__all__ = [
    "CapabilityRegistry",
    "CapabilitySecurityError",
    "trust_level_to_privilege",
    "check_capability_namespace_permission",
    "_check_capability_namespace_permission",
]
