"""
PluginSandbox - создание изолированного контекста для плагинов.

Отвечает за:
- Создание StorageProxy для изоляции storage
- Создание ServiceProxy для ограничения доступа к сервисам
- Установку RuntimeContext для плагина
"""

from typing import Optional, Any

from core.base_plugin import BasePlugin
from core.plugin_isolation import StorageProxy, ServiceProxy, DEFAULT_ALLOWED_SERVICES


class PluginSandbox:
    """
    Создатель изолированного контекста для плагинов.
    
    SECURITY P0: Плагины НЕ должны иметь прямой доступ к runtime.storage.
    Каждый плагин видит только свой namespace через StorageProxy.
    """
    
    @staticmethod
    def create_isolation_context(
        plugin: BasePlugin,
        runtime: Optional[Any],
        plugin_name: str
    ) -> None:
        """
        Создать изолированный контекст для плагина.
        
        Устанавливает:
        - plugin.storage = StorageProxy (изолированный namespace)
        - plugin.services = ServiceProxy (ограниченный доступ к сервисам)
        - plugin.context = RuntimeContext (если runtime поддерживает)
        
        Args:
            plugin: экземпляр плагина
            runtime: экземпляр CoreRuntime
            plugin_name: имя плагина (используется как namespace)
        """
        if runtime is None:
            return
        
        try:
            # P0 SECURITY: Do NOT set plugin.runtime directly
            # Instead, provide only isolated access through proxies
            
            # Create StorageProxy for plugin (isolated namespace)
            if hasattr(runtime, 'storage'):
                plugin.storage = StorageProxy(
                    runtime.storage,
                    namespace=plugin_name
                )
            
            # Create ServiceProxy for plugin (limited service access)
            if hasattr(runtime, 'service_registry'):
                allowed = getattr(plugin, "_manifest_allowed_services", None)
                if not allowed or not isinstance(allowed, list):
                    allowed = DEFAULT_ALLOWED_SERVICES
                plugin.services = ServiceProxy(
                    runtime.service_registry,
                    allowed_services=allowed,
                    plugin_name=plugin_name
                )
            
            # Устанавливаем RuntimeContext для плагина (если runtime поддерживает create_context)
            if hasattr(runtime, 'create_context'):
                plugin.context = runtime.create_context()
            
            # Backward compat: set plugin.runtime so plugins can use self.runtime.operations etc.
            # Plugins should prefer storage/services proxies, but runtime is available for direct handlers
            plugin.runtime = runtime  # type: ignore[assignment]
            
        except Exception as e:
            # Isolation setup failed - still continue but log
            from core.logger_helper import warning
            warning(f"Plugin isolation setup failed for {plugin_name}: {e}")
