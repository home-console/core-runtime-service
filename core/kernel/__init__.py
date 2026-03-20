"""
Kernel components - низкоуровневые компоненты ядра.

Содержит разбиение fat objects на отдельные файлы по ответственности.
"""

from core.kernel.plugin_registry import PluginState, PluginRegistry
from core.kernel.plugin_lifecycle import PluginLifecycleManager
from core.kernel.plugin_loader import PluginManifestLoader
from core.kernel.plugin_sandbox import PluginSandbox
from core.kernel.context import KernelContext

__all__ = [
    'PluginState',
    'PluginRegistry',
    'PluginLifecycleManager',
    'PluginManifestLoader',
    'PluginSandbox',
    'KernelContext',
]
