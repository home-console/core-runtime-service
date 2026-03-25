"""
PluginSandbox - создание изолированного контекста для плагинов.

Отвечает за:
- Создание StorageProxy для изоляции storage
- Создание ServiceProxy для ограничения доступа к сервисам
- Установку RuntimeContext для плагина
"""

from typing import Optional, Any

from core.kernel.base_plugin import BasePlugin
from core.kernel.plugin_runtime_facade import PluginRuntimeFacade


class PluginSandbox:
    """
    Создатель изолированного контекста для плагинов.

    SECURITY P0: Плагины НЕ должны иметь прямой доступ к runtime.storage.
    Каждый плагин видит только свой namespace через StorageProxy.
    """

    @staticmethod
    def create_isolation_context(
        plugin: BasePlugin, runtime: Optional[Any], plugin_name: str
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
            storage_proxy_cls = getattr(runtime, "plugin_storage_proxy_cls", None)
            service_proxy_cls = getattr(runtime, "plugin_service_proxy_cls", None)
            default_allowed_services = getattr(
                runtime, "plugin_default_allowed_services", []
            )

            # Create StorageProxy for plugin (isolated namespace)
            if storage_proxy_cls is not None and hasattr(runtime, "storage"):
                plugin.storage = storage_proxy_cls(runtime.storage, namespace=plugin_name)

            # Create ServiceProxy for plugin (limited service access)
            if service_proxy_cls is not None and hasattr(runtime, "service_registry"):
                allowed = getattr(plugin, "_manifest_allowed_services", None)
                if not allowed or not isinstance(allowed, list):
                    allowed = default_allowed_services
                plugin.services = service_proxy_cls(
                    runtime.service_registry,
                    allowed_services=allowed,
                    plugin_name=plugin_name,
                )

            # Устанавливаем RuntimeContext для плагина (если runtime поддерживает create_context)
            if hasattr(runtime, "create_context"):
                plugin.context = runtime.create_context()
            
            # Backward compat (SECURITY): provide facade instead of raw CoreRuntime.
            plugin.runtime = PluginRuntimeFacade(
                storage=getattr(plugin, "storage", None) or getattr(runtime, "storage", None),
                service_registry=getattr(runtime, "service_registry", None),
                http=getattr(runtime, "http", None),
                operations=getattr(runtime, "operations", None),
                state=getattr(runtime, "state", None),
                event_bus=getattr(runtime, "event_bus", None),
                capabilities=getattr(runtime, "capability_registry", None) or getattr(runtime, "capabilities", None),
                vault=getattr(runtime, "vault", None),
                config=getattr(runtime, "config", None),
                agent_manager=getattr(runtime, "agent_manager", None),
                agent_registry=getattr(runtime, "agent_registry", None),
            )  # type: ignore[assignment]
            
        except Exception as e:
            # Isolation setup failed - still continue but log
            from core.logger_helper import warning

            warning(f"Plugin isolation setup failed for {plugin_name}: {e}")
