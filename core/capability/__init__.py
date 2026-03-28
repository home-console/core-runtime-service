"""Core capability registry exports."""

from core.capability.registry import CapabilityRegistry
from core.capability.security import CapabilitySecurityError

__all__ = ["CapabilityRegistry", "CapabilitySecurityError"]

