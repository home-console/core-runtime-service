"""
Compatibility package for the plugin subsystem.

Canonical plugin runtime lives under core.kernel.
"""

from core.kernel.plugin_manager import PluginManager
from core.kernel.plugin_registry import PluginState

__all__ = [
    "PluginManager",
    "PluginState",
]
