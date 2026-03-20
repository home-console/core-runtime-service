"""
Canonical plugin subsystem package.

Contains the public plugin API, validation helpers, isolation proxies,
and the plugin manager facade.
"""

from modules.plugins.isolation import DEFAULT_ALLOWED_SERVICES, ServiceProxy, StorageProxy
from modules.plugins.manager import PluginManager
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
