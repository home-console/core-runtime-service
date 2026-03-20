"""
Backwards-compatibility shim for `core.base_plugin`.

Re-exports public symbols from `core.kernel.base_plugin` so older imports
continue to work after refactor.
"""

from core.kernel.base_plugin import BasePlugin, PluginMetadata

__all__ = ["BasePlugin", "PluginMetadata"]
