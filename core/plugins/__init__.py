"""
Compatibility package for the plugin subsystem.

Canonical implementations live under modules.plugins.
"""

from modules.plugins.isolation import DEFAULT_ALLOWED_SERVICES, ServiceProxy, StorageProxy
from core.kernel.plugin_manager import PluginManager
from modules.plugins.schema import ValidationError, validate_plugin_json
from core.kernel.plugin_registry import PluginState

__all__ = [
    "DEFAULT_ALLOWED_SERVICES",
    "PluginManager",
    "PluginState",
    "ServiceProxy",
    "StorageProxy",
    "ValidationError",
    "validate_plugin_json",
]
