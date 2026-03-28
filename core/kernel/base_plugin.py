"""
Базовый класс и интерфейс для плагинов.

Наследует контракт от sdk.BasePlugin; добавляет хелперы (register_service, get_env_config).
Плагины могут наследоваться от core.base_plugin.BasePlugin или от sdk.BasePlugin.

Контракт: sdk/README.md, docs/08-PLUGIN-CONTRACT.md
"""

from __future__ import annotations

import os
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Optional, Union

from core.runtime.runtime_context import LegacyRuntimeContext
from sdk.plugin import BasePlugin as SDKBasePlugin

if TYPE_CHECKING:
    from core.kernel.plugin_runtime_facade import PluginRuntimeFacade


@dataclass
class PluginMetadata:
    """Метаданные плагина."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: list[str] | None = field(
        default_factory=list
    )  # Список имён плагинов-зависимостей
    # По умолчанию все сервисы плагина доступны не только админам.
    # Можно включить default_admin_only=True для "админских" плагинов.
    default_admin_only: bool = False
    # Capability: плагин объявляет, какие capabilities предоставляет и какие требует.
    capabilities_provided: list[str] | None = field(
        default_factory=list
    )  # ["oauth:yandex"]
    capabilities_required: list[str] | None = field(
        default_factory=list
    )  # ["oauth:yandex", "yandex:session_cookies"]
    # Remote configuration для remote capability providers
    # Если не None, то этот плагин является remote provider
    remote_config: dict | None = None  # {"base_url": "http://...", "timeout": 10}
    # Plugin execution mode
    execution_mode: Literal["in_process", "process", "container", "remote"] = (
        "in_process"
    )
    # Optional configuration for process/container execution
    process_config: dict | None = None  # {"timeout": 30, "max_memory": "256M"}
    container_config: dict | None = None  # {"image": "...", "timeout": 30}
    # Resource limits
    resource_limits: dict | None = (
        None  # {"max_execution_seconds": 30, "max_memory_mb": 512, "max_calls_per_minute": 100}
    )


class BasePlugin(SDKBasePlugin):
    """
    Базовый класс для всех плагинов (расширяет sdk.BasePlugin).

    Lifecycle: on_load → on_start → on_stop → on_unload.

    Согласованность с RuntimeModule:
    - Module: __init__ → register() → start() → stop()
    - Plugin: __init__ → on_load() → on_start() → on_stop() → on_unload()

    Различия:
    - Module.register() регистрирует сервисы/endpoints (идентично Plugin.on_load())
    - Module.start() инициализирует runtime-зависимые ресурсы (идентично Plugin.on_start())
    - Module.stop() останавливает модуль (идентично Plugin.on_stop())
    - Plugin.on_unload() дополнительно очищает ресурсы (Module не имеет аналога)

    Оба используют RuntimeContext для доступа к ядру (storage, services, http, capabilities, operations).
    """

    _loaded: bool = False
    _started: bool = False

    def __init__(
        self,
        runtime_or_context: Optional[
            Union["PluginRuntimeFacade", LegacyRuntimeContext, Any]
        ] = None,
        *,
        runtime: Optional[Union["PluginRuntimeFacade", LegacyRuntimeContext, Any]] = None,
    ) -> None:
        """
        Инициализация плагина.

        Args:
            runtime_or_context: экземпляр CoreRuntime или RuntimeContext
                Если передан CoreRuntime, создаётся RuntimeContext автоматически
                Если None, context будет установлен позже через PluginManager
            runtime: alias для runtime_or_context (для обратной совместимости)
        """
        # Support passing runtime as keyword argument (backward compat)
        if runtime is not None and runtime_or_context is None:
            runtime_or_context = runtime
        # Для обратной совместимости передаём runtime в SDKBasePlugin
        runtime = (
            runtime_or_context
            if not isinstance(runtime_or_context, LegacyRuntimeContext)
            else None
        )
        super().__init__(runtime)

        # Сохраняем context если передан
        if isinstance(runtime_or_context, LegacyRuntimeContext):
            self.context = runtime_or_context
            self.runtime = None  # Не используем runtime напрямую
        elif runtime_or_context is not None:
            # Старый способ: передали runtime
            self.runtime = runtime_or_context
            # Создаём context из runtime если у runtime есть метод create_context
            if hasattr(runtime_or_context, "create_context"):
                self.context = runtime_or_context.create_context()
            else:
                self.context = None  # Будет установлен позже через PluginManager
        else:
            self.runtime = None
            self.context = None  # Будет установлен позже через PluginManager

        self._loaded = False
        self._started = False

    async def register_service(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *,
        resource: Optional[str] = None,
        admin_only: Optional[bool] = None,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[Callable[[tuple, dict], Awaitable[Any]]] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
    ) -> None:
        """
        Удобный helper для регистрации сервисов в плагинах.

        ACL enforcement находится в ядре (ServiceRegistry.register_with_acl).
        Плагин просто указывает метаданные при регистрации.
        """
        # Если явно не указали admin_only — берём дефолт из metadata (для всего плагина)
        effective_admin_only = admin_only
        try:
            if (
                effective_admin_only is None
                and getattr(self, "metadata", None) is not None
            ):
                effective_admin_only = bool(self.metadata.default_admin_only)
        except Exception:
            # В сомнительных случаях не ужесточаем, оставляем на усмотрение конвенций в ServiceRegistry
            effective_admin_only = admin_only

        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "register_service"):
            await runtime_api.register_service(
                name,
                func,
                resource=resource,
                admin_only=effective_admin_only,
                filter_result=filter_result,
                enforce_result=enforce_result,
                preload_resource=preload_resource,
                inject_owner_param=inject_owner_param,
                version=version,
            )
            return

        # Backward compatibility path for older runtime objects.
        if hasattr(self, "context") and self.context:
            reg = self.context.services
        elif runtime_obj is not None:
            reg = runtime_obj.service_registry
        else:
            raise RuntimeError("Plugin not initialized: no runtime or context available")

        register_with_acl = getattr(reg, "register_with_acl", None)
        if callable(register_with_acl):
            await register_with_acl(
                name,
                func,
                resource=resource,
                admin_only=effective_admin_only,
                filter_result=filter_result,
                enforce_result=enforce_result,
                preload_resource=preload_resource,
                inject_owner_param=inject_owner_param,
                version=version,
            )
            return
        await reg.register(name, func, version=version)

    async def unregister_service(self, name: str) -> None:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "unregister_service"):
            await runtime_api.unregister_service(name)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        await runtime_obj.service_registry.unregister(name)

    async def has_service(self, name: str) -> bool:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "has_service"):
            return bool(await runtime_api.has_service(name))
        if runtime_obj is None:
            return False
        return bool(await runtime_obj.service_registry.has_service(name))

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """SDK-friendly helper for service calls."""
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "call_service"):
            return await runtime_api.call_service(name, *args, **kwargs)
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        return await runtime_obj.service_registry.call(name, *args, **kwargs)

    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """SDK-friendly helper for event publishing."""
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "publish_event"):
            await runtime_api.publish_event(event_type, payload)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        await runtime_obj.event_bus.publish(event_type, payload)

    async def subscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "subscribe_event"):
            await runtime_api.subscribe_event(event_type, handler)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        await runtime_obj.event_bus.subscribe(event_type, handler)

    async def unsubscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "unsubscribe_event"):
            await runtime_api.unsubscribe_event(event_type, handler)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        await runtime_obj.event_bus.unsubscribe(event_type, handler)

    async def storage_get(self, namespace: str, key: str) -> Any:
        """SDK-friendly helper for storage read."""
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "storage_get"):
            return await runtime_api.storage_get(namespace, key)
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        return await runtime_obj.storage.get(namespace, key)

    async def storage_set(self, namespace: str, key: str, value: Any) -> None:
        """SDK-friendly helper for storage write."""
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "storage_set"):
            await runtime_api.storage_set(namespace, key, value)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        await runtime_obj.storage.set(namespace, key, value)

    async def storage_delete(self, namespace: str, key: str) -> bool:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "storage_delete"):
            return bool(await runtime_api.storage_delete(namespace, key))
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        return bool(await runtime_obj.storage.delete(namespace, key))

    async def storage_list_keys(self, namespace: str) -> list[str]:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "storage_list_keys"):
            keys = await runtime_api.storage_list_keys(namespace)
            return list(keys) if isinstance(keys, list) else []
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        return list(await runtime_obj.storage.list_keys(namespace))

    def register_http_endpoint(self, endpoint: Any) -> None:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "register_http"):
            runtime_api.register_http(endpoint)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        runtime_obj.http.register(endpoint)

    def register_operation_handler(self, op_type: str, handler: Any) -> None:
        runtime_obj = getattr(self, "_runtime", None)
        runtime_api = getattr(runtime_obj, "api", None)
        if runtime_api is not None and hasattr(runtime_api, "register_operation_handler"):
            runtime_api.register_operation_handler(op_type, handler)
            return
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime not set")
        runtime_obj.operations.register_handler(op_type, handler)

    def get_env_config(
        self, key: str, default: Optional[str] = None, prefix: Optional[str] = None
    ) -> Optional[str]:
        """
        Получить значение конфигурации из переменных окружения.

        Ищет переменную в следующем порядке:
        1. {prefix}_{key} (если prefix указан)
        2. {plugin_name}_{key} (где plugin_name из metadata)
        3. {key}

        Args:
            key: имя переменной окружения (без префикса)
            default: значение по умолчанию, если переменная не найдена
            prefix: опциональный префикс (если None, используется имя плагина из metadata)

        Returns:
            Значение переменной окружения или default

        Пример:
            # Ищет PLUGIN_NAME_REMOTE_URL, затем REMOTE_URL
            url = self.get_env_config("REMOTE_URL")

            # Ищет CUSTOM_REMOTE_URL, затем PLUGIN_NAME_REMOTE_URL, затем REMOTE_URL
            url = self.get_env_config("REMOTE_URL", prefix="CUSTOM")
        """
        # Определяем префикс
        if prefix is None:
            try:
                # Пытаемся получить имя плагина из metadata
                plugin_name = self.metadata.name.upper().replace("-", "_")
                prefix = plugin_name
            except Exception:
                # Если metadata недоступен, используем имя класса
                prefix = self.__class__.__name__.upper()

        # Пробуем варианты в порядке приоритета
        env_keys = [
            f"{prefix}_{key}",  # С префиксом плагина
            key,  # Без префикса
        ]

        for env_key in env_keys:
            value = os.getenv(env_key)
            if value is not None:
                return value

        return default

    def get_env_config_bool(
        self, key: str, default: bool = False, prefix: Optional[str] = None
    ) -> bool:
        """
        Получить булево значение из переменных окружения.

        Args:
            key: имя переменной окружения
            default: значение по умолчанию
            prefix: опциональный префикс

        Returns:
            True если значение "true", "1", "yes", "on" (case-insensitive), иначе False
        """
        value = self.get_env_config(key, default=None, prefix=prefix)
        if value is None:
            return default

        return value.lower() in ("true", "1", "yes", "on")

    def get_env_config_int(
        self, key: str, default: Optional[int] = None, prefix: Optional[str] = None
    ) -> Optional[int]:
        """
        Получить целое число из переменных окружения.

        Args:
            key: имя переменной окружения
            default: значение по умолчанию
            prefix: опциональный префикс

        Returns:
            Целое число или default если не удалось распарсить
        """
        value = self.get_env_config(key, default=None, prefix=prefix)
        if value is None:
            return default

        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """
        Метаданные плагина.
        Должен быть реализован в каждом плагине.
        """
        ...

    @property
    def is_loaded(self) -> bool:
        """Загружен ли плагин."""
        return self._loaded

    @property
    def is_started(self) -> bool:
        """Запущен ли плагин."""
        return self._started

    async def on_load(self) -> None:
        """
        Вызывается при загрузке плагина.

        Здесь можно:
        - инициализировать ресурсы
        - регистрировать сервисы
        - подписываться на события

        Для логирования используйте:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="...",
                plugin=self.metadata.name
            )
        """
        # Note: PluginManager may load plugins without a runtime set (tests).
        # Do not require runtime to be present here — lifecycle methods may be
        # invoked in environments where runtime is assigned later.
        self._loaded = True

    async def on_start(self) -> None:
        """
        Вызывается при запуске плагина.

        Здесь можно:
        - запустить фоновые задачи
        - начать обработку данных
        """
        self._started = True

    async def on_stop(self) -> None:
        """
        Вызывается при остановке плагина.

        Здесь нужно:
        - остановить фоновые задачи
        - освободить ресурсы
        """
        self._started = False

    async def on_unload(self) -> None:
        """
        Вызывается при выгрузке плагина.

        Здесь нужно:
        - отписаться от событий
        - удалить сервисы
        - закрыть соединения
        """
        self._loaded = False
