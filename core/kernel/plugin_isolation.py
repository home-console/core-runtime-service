"""
Plugin isolation primitives.

SECURITY P0:
- Plugins must not get direct access to runtime storage/services.
- Isolation is enforced via small proxy wrappers that are safe to use from core.

This module lives in `core` on purpose: it contains no app/module dependencies and
can be used by the kernel/runtime as a safe default.
"""

from __future__ import annotations

import logging
import inspect
from typing import Any, Awaitable, Callable, Iterable, List, Optional

from core.exceptions import ForbiddenError

_log = logging.getLogger(__name__)

DEFAULT_ALLOWED_SERVICES = [
    "logger.log",
    "logger.info",
    "logger.warning",
    "logger.error",
    "logger.debug",
]

# Prefixes reserved for core runtime — plugins must not squat these namespaces.
RESERVED_NAMESPACE_PREFIXES: tuple[str, ...] = (
    "runtime.",
    "hc.",
    "system.",
    "core.",
)
RESERVED_NAMESPACE_EXACT: frozenset[str] = frozenset(
    prefix.rstrip(".") for prefix in RESERVED_NAMESPACE_PREFIXES
)

# Integration plugins may subscribe to cross-plugin buses without listing every type.
DEFAULT_SUBSCRIBE_PREFIXES: tuple[str, ...] = ("internal.", "external.")


def is_reserved_event_type(event_type: str) -> bool:
    """True if event_type uses a core-reserved prefix (runtime.*, hc.*, …)."""
    normalized = str(event_type or "").strip().lower()
    if not normalized:
        return True
    if normalized in RESERVED_NAMESPACE_EXACT:
        return True
    return any(normalized.startswith(prefix) for prefix in RESERVED_NAMESPACE_PREFIXES)


def assert_plugin_namespace_allowed(namespace: str, *, context: str = "namespace") -> None:
    """
    Reject plugin namespaces that overlap core/runtime reserved prefixes.

    Blocks exact names (runtime, hc, system, core) and dotted prefixes (runtime.*, …).
    """
    if not namespace or ":" in namespace:
        raise ValueError(f"Invalid {context}: {namespace!r}")

    normalized = namespace.strip().lower()
    if normalized in RESERVED_NAMESPACE_EXACT:
        raise ValueError(
            f"Reserved {context} {namespace!r}: "
            f"cannot use {', '.join(sorted(RESERVED_NAMESPACE_EXACT))}"
        )
    for prefix in RESERVED_NAMESPACE_PREFIXES:
        if normalized.startswith(prefix):
            raise ValueError(
                f"Reserved {context} {namespace!r}: prefix {prefix!r} is reserved for core"
            )


def _as_patterns(values: Optional[Iterable[str]]) -> list[str]:
    if values is None:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _matches_patterns(name: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if pattern == name:
            return True
        if pattern.endswith(".*") and name.startswith(f"{pattern[:-2]}."):
            return True
    return False


class StorageProxy:
    """
    Proxy for isolating plugins from direct storage access.

    - Plugin can only see its own namespace.
    - Keys are automatically prefixed with "<namespace>:".
    - Admin-style operations are forbidden.
    """

    def __init__(self, storage: Any, namespace: str):
        assert_plugin_namespace_allowed(namespace, context="storage namespace")

        self._storage = storage
        self._namespace = namespace

    def _make_key(self, key: str) -> str:
        if ":" in key:
            raise ForbiddenError(f"Key cannot contain ':' separator: {key}")
        return f"{self._namespace}:{key}"

    async def get(self, key: str, default: Any = None) -> Any:
        result = await self._storage.get(self._namespace, key)
        return result if result is not None else default

    async def put(self, key: str, value: Any) -> None:
        await self._storage.set(self._namespace, key, value)

    async def delete(self, key: str) -> None:
        await self._storage.delete(self._namespace, key)

    async def exists(self, key: str) -> bool:
        return await self._storage.get(self._namespace, key) is not None

    async def keys(self, pattern: Optional[str] = None) -> List[str]:
        all_keys = await self._storage.list_keys(self._namespace)
        if pattern:
            import fnmatch

            all_keys = [k for k in all_keys if fnmatch.fnmatch(k, pattern)]
        return all_keys

    async def clear(self) -> None:
        keys = await self.keys()
        for key in keys:
            await self.delete(key)

    async def list_all(self) -> List[str]:
        raise ForbiddenError("StorageProxy: list_all() is forbidden for plugins")

    async def clear_all(self) -> None:
        raise ForbiddenError("StorageProxy: clear_all() is forbidden for plugins")


class NamespacedStorageProxy:
    """
    Storage proxy for the *namespaced* storage adapter interface (namespace + key).

    Used for plugin-facing RuntimeContext / runtime facade, so a plugin cannot access
    other namespaces by passing arbitrary `namespace` values.
    """

    def __init__(
        self,
        storage: Any,
        namespace: str,
        *,
        allowed_namespaces: Optional[Iterable[str]] = None,
    ):
        assert_plugin_namespace_allowed(namespace, context="storage namespace")
        self._storage = storage
        self._namespace = namespace
        allowed = [namespace, *_as_patterns(allowed_namespaces)]
        for ns in allowed:
            assert_plugin_namespace_allowed(ns, context="allowed storage namespace")
        self._allowed_namespaces = set(allowed)

    def _require_ns(self, namespace: str) -> None:
        if namespace not in self._allowed_namespaces:
            raise ForbiddenError(
                f"Storage access to namespace '{namespace}' is forbidden for plugin namespace '{self._namespace}'"
            )

    async def get(self, namespace: str, key: str) -> Any:
        self._require_ns(namespace)
        return await self._storage.get(namespace, key)

    async def set(self, namespace: str, key: str, value: Any) -> None:
        self._require_ns(namespace)
        return await self._storage.set(namespace, key, value)

    async def delete(self, namespace: str, key: str) -> Any:
        self._require_ns(namespace)
        return await self._storage.delete(namespace, key)

    async def list_keys(self, namespace: str) -> Any:
        self._require_ns(namespace)
        return await self._storage.list_keys(namespace)

    async def list_namespaces(self) -> list[str]:
        raise ForbiddenError("StorageProxy: list_namespaces() is forbidden for plugins")


class ServiceProxy:
    """
    Proxy for limiting plugin access to services.
    """

    def __init__(self, service_registry: Any, allowed_services: List[str], plugin_name: str):
        self._service_registry = service_registry
        self._allowed_services = set(allowed_services)
        self._plugin_name = plugin_name

    def _is_allowed(self, service_name: str) -> bool:
        if service_name in self._allowed_services:
            return True
        for pattern in self._allowed_services:
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if service_name.startswith(f"{prefix}."):
                    return True
        return False

    async def call(self, service_name: str, *args: Any, **kwargs: Any) -> Any:
        if not self._is_allowed(service_name):
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' is not allowed to call service '{service_name}'"
            )
        return await self._service_registry.call(service_name, *args, **kwargs)

    async def has_service(self, service_name: str) -> bool:
        if not self._is_allowed(service_name):
            return False
        return await self._service_registry.has_service(service_name)


class ServiceRegistryProxy(ServiceProxy):
    """
    ServiceProxy + безопасный доступ к регистрации сервисов.

    Naming convention enforcement:
    - Плагин должен регистрировать сервисы под своим namespace: "{plugin_name}.*"
      или под объявленным namespace из манифеста: "{namespace}.*"
    - Нарушение блокируется. Warning-only аудит оставлял service-squatting
      уязвимость: плагин мог зарегистрировать новый сервис вне своего namespace.
    - dynamic_services=True: trusted proxy-плагины (remote_plugin_proxy),
      которые регистрируют сервисы динамически.
    """

    def __init__(
        self,
        service_registry: Any,
        allowed_services: List[str],
        plugin_name: str,
        *,
        namespace: str = "",
        dynamic_services: bool = False,
        allowed_provided_services: Optional[Iterable[str]] = None,
    ):
        super().__init__(service_registry, allowed_services, plugin_name)
        self._namespace = namespace
        self._dynamic_services = dynamic_services
        self._allowed_provided_services = _as_patterns(allowed_provided_services)

    def _in_allowed_namespace(self, name: str) -> bool:
        if self._dynamic_services:
            return True
        if name.startswith(f"{self._plugin_name}."):
            return True
        if self._namespace and name.startswith(f"{self._namespace}."):
            return True
        if _matches_patterns(name, self._allowed_provided_services):
            return True
        return False

    def _require_registration_namespace(self, name: str) -> None:
        if not self._in_allowed_namespace(name):
            ns_hint = f" or '{self._namespace}.*'" if self._namespace else ""
            allowed_hint = (
                f" or declared services {self._allowed_provided_services!r}"
                if self._allowed_provided_services
                else ""
            )
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' cannot register/unregister service '{name}'. "
                f"Allowed: '{self._plugin_name}.*'{ns_hint}{allowed_hint}."
            )

    async def register_with_acl(self, name: str, func: Any, **kwargs: Any) -> None:
        self._require_registration_namespace(name)
        register_with_acl = getattr(self._service_registry, "register_with_acl", None)
        if callable(register_with_acl):
            await register_with_acl(name, func, **kwargs)  # type: ignore[misc]
            return
        register = getattr(self._service_registry, "register", None)
        if callable(register):
            await register(name, func, **kwargs)  # type: ignore[misc]
            return
        raise AttributeError("Underlying service_registry has no register method")

    async def register(self, name: str, func: Any, **kwargs: Any) -> None:
        self._require_registration_namespace(name)
        register = getattr(self._service_registry, "register", None)
        if callable(register):
            await register(name, func, **kwargs)  # type: ignore[misc]
            return
        raise AttributeError("Underlying service_registry has no register method")

    async def unregister(self, name: str) -> None:
        self._require_registration_namespace(name)
        unregister = getattr(self._service_registry, "unregister", None)
        if callable(unregister):
            await unregister(name)  # type: ignore[misc]
            return
        raise AttributeError("Underlying service_registry has no unregister method")


class EventBusProxy:
    """
    Proxy для изоляции плагинов от сырого EventBus.

    publish — blocking: плагин может публиковать только под своим namespace
    ({plugin_name}.*) или под объявленным namespace из манифеста ({namespace}.*).
    Eavesdropping через publish опаснее squatting в services, поэтому тут hard block.

    subscribe — allowlist: собственный namespace, internal.* / external.*, declared
    subscribes_events, system events. Reserved prefixes (runtime.*, …) запрещены.
    """

    def __init__(
        self,
        event_bus: Any,
        plugin_name: str,
        *,
        namespace: str = "",
        allowed_events: Optional[Iterable[str]] = None,
        subscribed_events: Optional[Iterable[str]] = None,
        allowed_system_events: Optional[Iterable[str]] = None,
    ):
        if namespace:
            assert_plugin_namespace_allowed(namespace, context="event namespace")
        assert_plugin_namespace_allowed(plugin_name, context="plugin name")
        self._event_bus = event_bus
        self._plugin_name = plugin_name
        self._namespace = namespace
        self._allowed_events = _as_patterns(allowed_events)
        self._subscribed_events = _as_patterns(subscribed_events)
        self._allowed_system_events = _as_patterns(allowed_system_events)

    def _can_subscribe(self, event_type: str) -> bool:
        if is_reserved_event_type(event_type):
            return False
        if event_type.startswith(f"{self._plugin_name}."):
            return True
        if self._namespace and event_type.startswith(f"{self._namespace}."):
            return True
        if any(event_type.startswith(prefix) for prefix in DEFAULT_SUBSCRIBE_PREFIXES):
            return True
        if _matches_patterns(event_type, self._subscribed_events):
            return True
        if event_type in self._allowed_system_events:
            return True
        return False

    def _can_publish(self, event_type: str) -> bool:
        if event_type.startswith(f"{self._plugin_name}."):
            return True
        if self._namespace and event_type.startswith(f"{self._namespace}."):
            return True
        if _matches_patterns(event_type, self._allowed_events):
            return True
        if event_type in self._allowed_system_events:
            return True
        return False

    async def subscribe(self, event_type: str, handler: Any) -> None:
        if not self._can_subscribe(event_type):
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' cannot subscribe to '{event_type}'. "
                f"Declare it in manifest 'subscribes_events' or use "
                f"'{self._plugin_name}.*', 'internal.*', or 'external.*'."
            )
        _log.debug("plugin '%s' subscribing to '%s'", self._plugin_name, event_type)
        await self._event_bus.subscribe(event_type, handler)

    async def unsubscribe(self, event_type: str, handler: Any) -> None:
        await self._event_bus.unsubscribe(event_type, handler)

    async def publish(self, event_type: str, payload: Any) -> None:
        if not self._can_publish(event_type):
            ns_hint = f" or '{self._namespace}.*'" if self._namespace else ""
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' cannot publish '{event_type}'. "
                f"Allowed: '{self._plugin_name}.*'{ns_hint}. "
                f"Set 'namespace' in manifest to expand publish permissions."
            )
        await self._event_bus.publish(event_type, payload)


class HttpRegistryProxy:
    """Restrict plugin HTTP contracts to services the plugin is allowed to provide."""

    def __init__(
        self,
        http_registry: Any,
        plugin_name: str,
        *,
        namespace: str = "",
        allowed_provided_services: Optional[Iterable[str]] = None,
        dynamic_services: bool = False,
    ):
        self._http_registry = http_registry
        self._plugin_name = plugin_name
        self._namespace = namespace
        self._allowed_provided_services = _as_patterns(allowed_provided_services)
        self._dynamic_services = dynamic_services

    def _can_reference_service(self, name: str) -> bool:
        if self._dynamic_services:
            return True
        if name.startswith(f"{self._plugin_name}."):
            return True
        if self._namespace and name.startswith(f"{self._namespace}."):
            return True
        return _matches_patterns(name, self._allowed_provided_services)

    def register(self, endpoint: Any, *args: Any, **kwargs: Any) -> Any:
        service_name = str(getattr(endpoint, "service", "") or "")
        if not self._can_reference_service(service_name):
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' cannot expose HTTP endpoint for service '{service_name}'"
            )
        return self._http_registry.register(endpoint, *args, **kwargs)

    def list(self) -> list[Any]:
        endpoints = getattr(self._http_registry, "list")()
        return [
            endpoint
            for endpoint in endpoints
            if self._can_reference_service(str(getattr(endpoint, "service", "") or ""))
        ]


PluginOperationHandler = Callable[..., Awaitable[Any] | Any]


class OperationRegistryProxy:
    """Restrict plugin operation handlers and keep raw CoreRuntime out of handler args."""

    def __init__(
        self,
        operations: Any,
        plugin_name: str,
        *,
        namespace: str = "",
        allowed_operations: Optional[Iterable[str]] = None,
        dynamic_services: bool = False,
    ):
        self._operations = operations
        self._plugin_name = plugin_name
        self._namespace = namespace
        self._allowed_operations = _as_patterns(allowed_operations)
        self._dynamic_services = dynamic_services
        self._restricted_runtime: Any = None

    def set_restricted_runtime(self, runtime: Any) -> None:
        self._restricted_runtime = runtime

    def _can_register(self, op_type: str) -> bool:
        if self._dynamic_services:
            return True
        if op_type.startswith(f"{self._plugin_name}."):
            return True
        if self._namespace and op_type.startswith(f"{self._namespace}."):
            return True
        return _matches_patterns(op_type, self._allowed_operations)

    def _require_operation_namespace(self, op_type: str) -> None:
        if not self._can_register(op_type):
            raise ForbiddenError(
                f"Plugin '{self._plugin_name}' cannot register/unregister operation '{op_type}'"
            )

    def _handler_context(self, operation: Any) -> dict[str, Any]:
        return {
            "runtime": self._restricted_runtime,
            "operation": operation,
            "operation_id": getattr(operation, "operation_id", None),
        }

    async def _invoke_plugin_handler(
        self,
        handler: PluginOperationHandler,
        operation: Any,
    ) -> Any:
        sig = inspect.signature(handler)
        params = list(sig.parameters.values())
        context = self._handler_context(operation)

        candidates: list[tuple[Any, ...]] = []
        if not params:
            candidates.append(())
        elif len(params) == 1:
            pname = params[0].name
            if pname in {"operation", "op"}:
                candidates.append((operation,))
            candidates.append((getattr(operation, "params", {}),))
        else:
            first_name = params[0].name
            second_name = params[1].name
            if first_name in {"runtime", "rt"} or second_name in {"operation", "op"}:
                candidates.append((self._restricted_runtime, operation))
            candidates.append((getattr(operation, "params", {}), context))
            candidates.append((self._restricted_runtime, operation))

        last_error: Exception | None = None
        for args in candidates:
            try:
                result = handler(*args)
            except TypeError as exc:
                last_error = exc
                continue
            if inspect.isawaitable(result):
                return await result
            return result

        raise RuntimeError(
            f"Plugin operation handler invocation failed for '{self._plugin_name}': {last_error}"
        )

    def _wrap_handler(self, handler: PluginOperationHandler) -> PluginOperationHandler:
        async def _wrapped(_runtime: Any, operation: Any) -> Any:
            return await self._invoke_plugin_handler(handler, operation)

        setattr(_wrapped, "__plugin_operation_owner__", self._plugin_name)
        return _wrapped

    def register_handler(self, op_type: str, handler: PluginOperationHandler) -> None:
        self._require_operation_namespace(op_type)
        self._operations.register_handler(op_type, self._wrap_handler(handler))

    def unregister_handler(self, op_type: str) -> None:
        self._require_operation_namespace(op_type)
        unregister = getattr(self._operations, "unregister_handler", None)
        if callable(unregister):
            unregister(op_type)

    def list_handler_types(self) -> list[str]:
        list_handler_types = getattr(self._operations, "list_handler_types", None)
        if not callable(list_handler_types):
            return []
        return [
            op_type
            for op_type in list_handler_types()
            if self._can_register(str(op_type))
        ]


class AgentManagerProxy:
    """Narrow client enrollment surface for plugins that need agent handshakes."""

    def __init__(self, agent_manager: Any):
        self._agent_manager = agent_manager

    async def validate_enrollment_token(self, enrollment_token: str) -> str:
        return await self._agent_manager.validate_enrollment_token(enrollment_token)

    async def register_agent_from_ws(self, agent_name: str, client_id: str) -> Any:
        return await self._agent_manager.register_agent_from_ws(agent_name, client_id)


class CapabilityRegistryProxy:
    """Read-only capability metadata surface for plugin code."""

    def __init__(self, capability_registry: Any):
        self._capability_registry = capability_registry

    def get_providers(self, capability_id: str) -> list[str]:
        return list(self._capability_registry.get_providers(capability_id))

    def get_providers_sorted_by_health(self, capability_id: str) -> list[str]:
        return list(self._capability_registry.get_providers_sorted_by_health(capability_id))

    def get_provider_info(self, capability_id: str, provider_name: str) -> Any:
        return self._capability_registry.get_provider_info(capability_id, provider_name)

    def get_required_capabilities(self, plugin_name: str) -> list[str]:
        return list(self._capability_registry.get_required_capabilities(plugin_name))
