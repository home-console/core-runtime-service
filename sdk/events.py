"""
Event payload schemas — re-exported from core for plugin use.

Plugins should import from sdk, not from core directly.
"""

from core.events_schemas import ExternalDeviceDiscoveredPayload

__all__ = ["ExternalDeviceDiscoveredPayload"]
