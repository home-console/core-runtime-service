"""
Compatibility package for the plugin subsystem.

Canonical implementations live under modules.plugins.
"""

from modules.plugins import (
    DEFAULT_ALLOWED_SERVICES,
    PluginManager,
    PluginState,
    ServiceProxy,
    StorageProxy,
    ValidationError,
    validate_plugin_json,
)

__all__ = [
    "DEFAULT_ALLOWED_SERVICES",
    "PluginManager",
    "PluginState",
    "ServiceProxy",
    "StorageProxy",
    "ValidationError",
    "validate_plugin_json",
]
