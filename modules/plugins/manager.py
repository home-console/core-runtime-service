"""
Shim для совместимости.

Реализация PluginManager переехала в `core.kernel`.
"""

from core.kernel.plugin_manager import PluginManager

__all__ = ["PluginManager"]
