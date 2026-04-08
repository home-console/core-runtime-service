"""Core capability registry exports."""

from core.capability.registry import CapabilityRegistry
from core.capability.component import CapabilityComponent


class CapabilitySecurityError(Exception):
    """Raised when a capability security check fails."""


__all__ = ["CapabilityRegistry", "CapabilityComponent", "CapabilitySecurityError"]
