"""Core capability registry exports."""

from core.capability.registry import CapabilityRegistry
from core.capability.component import CapabilityComponent


class CapabilitySecurityError(Exception):
    """Compatibility exception for legacy imports."""


__all__ = ["CapabilityRegistry", "CapabilityComponent", "CapabilitySecurityError"]
