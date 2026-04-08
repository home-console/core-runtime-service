"""
Extended plugin base classes — re-exported from core for plugin use.

Provides the full-featured BasePlugin (with register_service, storage helpers,
get_env_config, etc.) and the extended PluginMetadata.

Import this module instead of core.kernel.base_plugin directly:

    from sdk.plugin_ext import BasePlugin, PluginMetadata
"""

from core.kernel.base_plugin import BasePlugin, PluginMetadata

__all__ = ["BasePlugin", "PluginMetadata"]
