"""
Базовый класс и интерфейс для плагинов.

Наследует контракт от sdk.BasePlugin; добавляет хелперы (register_service, get_env_config).
Плагины могут наследоваться от core.kernel.base_plugin.BasePlugin или от sdk.BasePlugin.

Контракт: sdk/README.md, docs/08-PLUGIN-CONTRACT.md
"""

from __future__ import annotations

import os
from abc import abstractmethod
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol, cast, runtime_checkable

from sdk.metadata import PluginMetadata as SDKPluginMetadata
from sdk.plugin import BasePlugin as SDKBasePlugin

from core.runtime.runtime_context import RuntimeContext
from core.service._acl import PreloadResourceFunc
from core.service.models import ServiceAuthConfig
import logging
logger = logging.getLogger(__name__)


@runtime_checkable
class SupportsContext(Protocol):
    def create_context(self) -> RuntimeContext: ...


@runtime_checkable
class SupportsPluginRuntimeAPI(Protocol):
    async def register_service(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *,
        resource: Optional[str] = None,
        admin_only: Optional[bool] = None,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[PreloadResourceFunc] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
        auth_config: Optional[ServiceAuthConfig] = None,
    ) -> None: ...

    async def unregister_service(self, name: str) -> None: ...

    async def has_service(self, name: str) -> bool: ...

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any: ...

    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None: ...

    async def subscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None: ...

    async def unsubscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None: ...

    async def storage_get(self, namespace: str, key: str) -> Any: ...

    async def storage_set(self, namespace: str, key: str, value: Any) -> None: ...

    async def storage_delete(self, namespace: str, key: str) -> bool: ...

    async def storage_list_keys(self, namespace: str) -> list[str]: ...

    def register_http(self, endpoint: Any) -> None: ...

    def register_operation_handler(
        self, op_type: str, handler: Callable[..., Any]
    ) -> None: ...


@dataclass(frozen=True)
class PluginMetadata(SDKPluginMetadata):
    """Метаданные плагина."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=lambda: cast(list[str], []))  # Список имён плагинов-зависимостей
    # По умолчанию все сервисы плагина доступны не только админам.
    # Можно включить default_admin_only=True для "админских" плагинов.
    default_admin_only: bool = False
    # Capability: плагин объявляет, какие capabilities предоставляет и какие требует.
    capabilities_provided: list[str] = field(default_factory=lambda: cast(list[str], []))  # ["oauth:yandex"]
    capabilities_required: list[str] = field(default_factory=lambda: cast(list[str], []))  # ["oauth:yandex", "yandex:session_cookies"]
    # Remote configuration для remote capability providers
    # Если не None, то этот плагин является remote provider
    remote_config: dict[str, Any] | None = None  # {"base_url": "http://...", "timeout": 10}
    # Plugin execution mode
    execution_mode: Literal["in_process", "process", "container", "remote"] = (
        "in_process"
    )
    # Optional configuration for process/container execution
    process_config: dict[str, Any] | None = None  # {"timeout": 30, "max_memory": "256M"}
    container_config: dict[str, Any] | None = None  # {"image": "...", "timeout": 30}
    # Resource limits
    resource_limits: dict[str, Any] | None = (
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
        runtime_or_context: RuntimeContext | SupportsContext,
    ) -> None:
        """
        Инициализация плагина.

        Args:
            runtime_or_context: экземпляр RuntimeContext или runtime с create_context()
        """
        self._loaded = False
        self._started = False
        self.runtime: SupportsPluginRuntimeAPI | None = None
        super().__init__(None)

        if isinstance(runtime_or_context, RuntimeContext):
            self.context = runtime_or_context
            return

        # Backward compatibility for lightweight tests/dummy plugins.
        if runtime_or_context is None:
            self.context = SimpleNamespace(
                storage=None,
                services=None,
                http=None,
                capabilities=None,
                operations=None,
                vault=None,
                state=None,
            )
            return

        self.runtime = cast(Any, runtime_or_context)
        create_context = getattr(runtime_or_context, "create_context", None)
        if callable(create_context):
            self.context = create_context()
            return

        # Backward compatibility for lightweight tests/mocks without create_context().
        self.context = RuntimeContext(
            storage=getattr(runtime_or_context, "storage", None),
            vault=getattr(runtime_or_context, "vault", None),
            services=cast(Any, getattr(runtime_or_context, "service_registry", None)),
            http=cast(Any, getattr(runtime_or_context, "http", None)),
            capabilities=cast(
                Any,
                getattr(
                    runtime_or_context,
                    "capability_registry",
                    getattr(runtime_or_context, "capabilities", None),
                ),
            ),
            operations=cast(Any, getattr(runtime_or_context, "operations", None)),
            state=getattr(
                runtime_or_context,
                "state_engine",
                getattr(runtime_or_context, "state", None),
            ),
        )

    def _runtime_api(self) -> Any:
        runtime_obj = self.runtime
        if runtime_obj is None:
            raise RuntimeError("Plugin runtime API not available")
        return getattr(runtime_obj, "api", None) or runtime_obj

    async def register_service(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *,
        resource: Optional[str] = None,
        admin_only: Optional[bool] = None,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[PreloadResourceFunc] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
        auth_config: Optional[ServiceAuthConfig] = None,
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
        except (AttributeError, TypeError, ValueError):

            # В сомнительных случаях не ужесточаем, оставляем на усмотрение конвенций в ServiceRegistry
            logger.debug("base_plugin.register_service: error (using fallback value)", exc_info=True)
            effective_admin_only = admin_only

        runtime_api = self._runtime_api()
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
            auth_config=auth_config,
        )

    async def unregister_service(self, name: str) -> None:
        runtime_api = self._runtime_api()
        await runtime_api.unregister_service(name)

    async def has_service(self, name: str) -> bool:
        runtime_api = self._runtime_api()
        return bool(await runtime_api.has_service(name))

    async def call_service(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """SDK-friendly helper for service calls."""
        runtime_api = self._runtime_api()
        return await runtime_api.call_service(name, *args, **kwargs)

    async def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """SDK-friendly helper for event publishing."""
        runtime_api = self._runtime_api()
        await runtime_api.publish_event(event_type, payload)

    async def publish_operation_ready(self, operation_id: str, **extra: Any) -> None:
        """Публикация `operation_ready` по контракту (очередь OperationWorker)."""
        runtime_api = self._runtime_api()
        await runtime_api.publish_operation_ready(operation_id, **extra)

    async def subscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        runtime_api = self._runtime_api()
        await runtime_api.subscribe_event(event_type, handler)

    async def unsubscribe_event(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        runtime_api = self._runtime_api()
        await runtime_api.unsubscribe_event(event_type, handler)

    async def storage_get(self, namespace: str, key: str) -> Any:
        """SDK-friendly helper for storage read."""
        runtime_api = self._runtime_api()
        return await runtime_api.storage_get(namespace, key)

    async def storage_set(self, namespace: str, key: str, value: Any) -> None:
        """SDK-friendly helper for storage write."""
        runtime_api = self._runtime_api()
        await runtime_api.storage_set(namespace, key, value)

    async def storage_delete(self, namespace: str, key: str) -> bool:
        runtime_api = self._runtime_api()
        return bool(await runtime_api.storage_delete(namespace, key))

    async def storage_list_keys(self, namespace: str) -> list[str]:
        runtime_api = self._runtime_api()
        keys: list[str] = await runtime_api.storage_list_keys(namespace)
        return keys

    def register_http_endpoint(self, endpoint: Any) -> None:
        runtime_api = self._runtime_api()
        runtime_api.register_http(endpoint)

    def register_operation_handler(self, op_type: str, handler: Any) -> None:
        runtime_api = self._runtime_api()
        runtime_api.register_operation_handler(op_type, handler)

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
            except (AttributeError, TypeError, ValueError):
                # Если metadata недоступен, используем имя класса
                logger.debug("base_plugin.get_env_config: error (using fallback value)", exc_info=True)
                prefix = self.__class__.__name__.upper()

        # Пробуем варианты в порядке приоритета
        env_keys = [
            f"{prefix}_{key}",  # С префиксом плагина
            key,  # Без префикса
        ]

        # NOTE: keep env read local to this helper.
        import os

        for env_key in env_keys:
            value = os.environ.get(env_key)
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
            await self.call_service(
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
