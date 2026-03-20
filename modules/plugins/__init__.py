"""
Canonical plugin subsystem package.

Contains the public plugin API, validation helpers, isolation proxies,
and the plugin manager facade.
"""

from modules.plugins.isolation import DEFAULT_ALLOWED_SERVICES, ServiceProxy, StorageProxy
# Avoid importing PluginManager at package import time to prevent circular
# imports with core.kernel (PluginLifecycleManager). Import manager
# implementations directly where needed.
try:
    from modules.plugins.schema import ValidationError, validate_plugin_json
except Exception:
    # Defer schema import errors to runtime where the module is actually used
    ValidationError = Exception
    def validate_plugin_json(*_args, **_kwargs):
        raise RuntimeError("modules.plugins.schema is not available at import time")
from core.kernel.plugin_registry import PluginState

__all__ = [
    "DEFAULT_ALLOWED_SERVICES",
    "PluginState",
    "ServiceProxy",
    "StorageProxy",
    "ValidationError",
    "validate_plugin_json",
]
