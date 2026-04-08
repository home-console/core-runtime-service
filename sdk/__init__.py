"""
Plugin SDK v0 — внешний контракт плагина.

Плагин пишется, импортируя только sdk.
Без ссылок на admin, ui, product api, modules, plugins.

Основные импорты для плагинов:
    from sdk.plugin_ext import BasePlugin, PluginMetadata   # full-featured base
    from sdk import HttpEndpoint, operation, PluginRuntime  # helpers
"""

from sdk.plugin import BasePlugin as _SDKBasePlugin  # noqa: F401 — base ABC (sdk-native)
from sdk.metadata import PluginMetadata as _SDKPluginMetadata  # noqa: F401 — base metadata
# NOTE: sdk.plugin_ext (core.kernel.base_plugin) is NOT imported here — circular import.
# Use: from sdk.plugin_ext import BasePlugin, PluginMetadata

from sdk.capabilities import CapabilityId
from sdk.context import PluginRuntime
from sdk.operations_events import (
    OPERATION_READY_EVENT_TYPE,
    build_operation_ready_payload,
)
from sdk.security import TokenEncryption, sanitize_for_logging, sanitize_headers
from sdk.http import HttpEndpoint, EndpointAuthConfig, EndpointParamMapping
from sdk.operation import operation
from sdk.events import ExternalDeviceDiscoveredPayload

__all__ = [
    # Runtime context
    "PluginRuntime",
    "CapabilityId",
    # Operations / events
    "OPERATION_READY_EVENT_TYPE",
    "build_operation_ready_payload",
    "operation",
    # HTTP
    "HttpEndpoint",
    "EndpointAuthConfig",
    "EndpointParamMapping",
    # Security
    "TokenEncryption",
    "sanitize_for_logging",
    "sanitize_headers",
    # Event schemas
    "ExternalDeviceDiscoveredPayload",
]
