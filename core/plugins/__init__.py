"""
Plugins subsystem - управление lifecycle плагинов.

Re-export для обратной совместимости.
"""

from core.plugins.manager import PluginManager
from core.kernel.plugin_registry import PluginState

__all__ = ['PluginManager', 'PluginState']
