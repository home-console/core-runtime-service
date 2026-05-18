"""
PluginSandbox - создание изолированного контекста для плагинов.

Отвечает за:
- Создание StorageProxy для изоляции storage
- Создание ServiceProxy для ограничения доступа к сервисам
- Установку RuntimeContext для плагина
"""

import logging
from typing import Any, Optional

from core.kernel.base_plugin import BasePlugin
from core.runtime.runtime_context import RuntimeContext
from sdk.operations_events import OPERATION_READY_EVENT_TYPE

from core.kernel.plugin_isolation import (
    AgentManagerProxy,
    CapabilityRegistryProxy,
    EventBusProxy,
    HttpRegistryProxy,
    NamespacedStorageProxy,
    OperationRegistryProxy,
    ServiceRegistryProxy,
)
from core.kernel.plugin_runtime_facade import PluginRuntimeFacade

_log = logging.getLogger(__name__)


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

        # FAIL-FAST: если StorageProxy не настроен — это P0 нарушение изоляции
        storage_proxy_cls = getattr(runtime, "plugin_storage_proxy_cls", None)
        if storage_proxy_cls is None:
            raise RuntimeError(
                "StorageProxy not configured in CoreRuntime. "
                "Plugin isolation is DISABLED — this is a P0 security violation. "
                "Set runtime.plugin_storage_proxy_cls before loading plugins."
            )

        # P0 SECURITY: Do NOT set plugin.runtime directly
        # Instead, provide only isolated access through proxies.
        # SECURITY: No try/except here — if isolation setup fails, the exception must
        # propagate to PluginLifecycleManager which will set PluginState.ERROR and abort
        # loading. Swallowing errors here would leave the plugin with no isolation.
        service_proxy_cls = getattr(runtime, "plugin_service_proxy_cls", None)
        default_allowed_services = getattr(runtime, "plugin_default_allowed_services", [])

        # Pre-initialize allowed so it is always defined when building the facade below.
        allowed: list = list(default_allowed_services) if isinstance(default_allowed_services, list) else []

        # Create StorageProxy for plugin (isolated namespace)
        if storage_proxy_cls is not None and hasattr(runtime, "storage"):
            plugin.storage = storage_proxy_cls(runtime.storage, namespace=plugin_name)

        # Read namespace and dynamic_service_registration from manifest context.
        # Falls back to plugin.metadata for plugins loaded without a manifest file.
        _plugin_ctx = getattr(plugin, "_plugin_context", None)
        _manifest = getattr(_plugin_ctx, "manifest", None) if _plugin_ctx is not None else None
        plugin_namespace: str = str(getattr(_manifest, "namespace", None) or "")
        dynamic_svc: bool = bool(getattr(_manifest, "dynamic_service_registration", False))
        manifest_extra = getattr(_manifest, "extra", {}) if _manifest is not None else {}
        manifest_provides = manifest_extra.get("provides", {}) if isinstance(manifest_extra, dict) else {}
        allowed_provided_services = list(getattr(_manifest, "provides_services", []) or [])
        allowed_events = list(getattr(_manifest, "provides_events", []) or [])
        subscribed_events = list(getattr(_manifest, "subscribes_events", []) or [])
        allowed_operations = list(getattr(_manifest, "provides_operations", []) or [])
        allowed_storage_namespaces = list(getattr(_manifest, "storage_namespaces", []) or [])
        if isinstance(manifest_provides, dict):
            allowed_provided_services.extend(manifest_provides.get("services", []) or [])
            allowed_events.extend(manifest_provides.get("events", []) or [])
            subscribed_events.extend(
                manifest_provides.get("subscribes", [])
                or manifest_provides.get("subscribes_events", [])
                or []
            )
            allowed_operations.extend(manifest_provides.get("operations", []) or [])
        # Metadata-level fallback (e.g. RemotePluginProxy sets dynamic_service_registration=True)
        if not dynamic_svc:
            _meta = getattr(plugin, "metadata", None)
            if _meta is not None:
                dynamic_svc = bool(getattr(_meta, "dynamic_service_registration", False))

        # Capability providers register operation handlers by capability id.
        # Tests and legacy plugins do this via PluginMetadata.capabilities_provided (without a manifest).
        _meta = getattr(plugin, "metadata", None)
        if _meta is not None:
            meta_caps = getattr(_meta, "capabilities_provided", None)
            if isinstance(meta_caps, list) and meta_caps:
                allowed_operations.extend([c for c in meta_caps if isinstance(c, str) and c.strip()])

        # Create ServiceProxy for plugin (limited service access)
        if service_proxy_cls is not None and hasattr(runtime, "service_registry"):
            manifest_allowed = getattr(_manifest, "allowed_services", None)
            if isinstance(manifest_allowed, list) and manifest_allowed:
                allowed_raw = manifest_allowed
            else:
                allowed_raw = default_allowed_services
            allowed = list(allowed_raw) if isinstance(allowed_raw, list) else allowed
            plugin.services = service_proxy_cls(
                runtime.service_registry,
                allowed_services=allowed,
                plugin_name=plugin_name,
            )

        # Build EventBusProxy for this plugin (P2.1).
        raw_event_bus = getattr(runtime, "event_bus", None)
        event_bus_proxy = (
            EventBusProxy(
                raw_event_bus,
                plugin_name,
                namespace=plugin_namespace,
                allowed_events=allowed_events,
                subscribed_events=subscribed_events,
                allowed_system_events=[OPERATION_READY_EVENT_TYPE],
            )
            if raw_event_bus is not None
            else None
        )

        raw_operations = getattr(runtime, "operations", None)
        operations_proxy = (
            OperationRegistryProxy(
                raw_operations,
                plugin_name,
                namespace=plugin_namespace,
                allowed_operations=allowed_operations,
                dynamic_services=dynamic_svc,
            )
            if raw_operations is not None
            else None
        )
        raw_http = getattr(runtime, "http", None)
        http_proxy = (
            HttpRegistryProxy(
                raw_http,
                plugin_name,
                namespace=plugin_namespace,
                allowed_provided_services=allowed_provided_services,
                dynamic_services=dynamic_svc,
            )
            if raw_http is not None
            else None
        )
        raw_capabilities = getattr(runtime, "capability_registry", None)
        capabilities_proxy = (
            CapabilityRegistryProxy(raw_capabilities) if raw_capabilities is not None else None
        )
        raw_agent_manager = getattr(runtime, "agent_manager", None)
        agent_manager_proxy = (
            AgentManagerProxy(raw_agent_manager) if raw_agent_manager is not None else None
        )

        create_context = getattr(runtime, "create_context", None)
        if not callable(create_context):
            raise RuntimeError(
                "CoreRuntime must provide create_context() for plugin isolation."
            )
        runtime_context = create_context()
        if not isinstance(runtime_context, RuntimeContext):
            raise RuntimeError(
                "CoreRuntime.create_context() must return RuntimeContext for plugin isolation."
            )
        plugin.context = runtime_context

        # SECURITY P0/P2.3: RuntimeContext is also a plugin surface.
        # Replace services, storage, and event_bus with proxied versions.
        if getattr(plugin, "context", None) is not None:
            try:
                if hasattr(plugin, "services") and getattr(plugin, "services", None) is not None:
                    setattr(plugin.context, "services", plugin.services)
                raw_storage = getattr(runtime, "storage", None)
                if raw_storage is not None:
                    setattr(
                        plugin.context,
                        "storage",
                        NamespacedStorageProxy(
                            raw_storage,
                            namespace=plugin_name,
                            allowed_namespaces=allowed_storage_namespaces,
                        ),
                    )
                # P2.3: replace raw event_bus in context with EventBusProxy
                if event_bus_proxy is not None and hasattr(plugin.context, "event_bus"):
                    setattr(plugin.context, "event_bus", event_bus_proxy)
                if operations_proxy is not None and hasattr(plugin.context, "operations"):
                    setattr(plugin.context, "operations", operations_proxy)
                if http_proxy is not None and hasattr(plugin.context, "http"):
                    setattr(plugin.context, "http", http_proxy)
                if capabilities_proxy is not None and hasattr(plugin.context, "capabilities"):
                    setattr(plugin.context, "capabilities", capabilities_proxy)
                if hasattr(plugin.context, "vault"):
                    setattr(plugin.context, "vault", None)
            except Exception:
                _log.exception("Failed to harden plugin.context surfaces")
                raise

        # Backward compat (SECURITY): provide facade instead of raw CoreRuntime.
        plugin.runtime = PluginRuntimeFacade(
            storage=NamespacedStorageProxy(
                getattr(runtime, "storage", None),
                namespace=plugin_name,
                allowed_namespaces=allowed_storage_namespaces,
            ),
            # SECURITY P0: do NOT leak raw service_registry to plugin code.
            service_registry=(
                ServiceRegistryProxy(
                    getattr(runtime, "service_registry", None),
                    allowed_services=allowed,
                    plugin_name=plugin_name,
                    namespace=plugin_namespace,
                    dynamic_services=dynamic_svc,
                    allowed_provided_services=allowed_provided_services,
                )
                if getattr(runtime, "service_registry", None) is not None
                else None
            ),
            http=http_proxy,
            operations=operations_proxy,
            state=getattr(runtime, "state", None),
            event_bus=event_bus_proxy,  # P2.1: use EventBusProxy
            capabilities=capabilities_proxy,
            vault=None,
            config=getattr(runtime, "config", None),
            agent_manager=agent_manager_proxy,
            agent_registry=None,
        )  # type: ignore[assignment]
