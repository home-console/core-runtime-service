"""
Plugin SDK v0 — внешний контракт плагина.

Плагин пишется, импортируя только sdk.
Без ссылок на admin, ui, product api, modules, plugins.
"""

from sdk.plugin import BasePlugin
from sdk.metadata import PluginMetadata
from sdk.capabilities import CapabilityId
from sdk.context import PluginRuntime

__all__ = [
    "BasePlugin",
    "PluginMetadata",
    "CapabilityId",
    "PluginRuntime",
]
