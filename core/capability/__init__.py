"""Core capability registry exports."""

from core.capability.registry import CapabilityRegistry


class CapabilitySecurityError(Exception):
    """Compatibility exception for legacy imports."""

__all__ = ["CapabilityRegistry", "CapabilitySecurityError"]
