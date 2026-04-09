"""
Базовый класс для встроенных модулей Runtime (RuntimeModule).

RuntimeModule — это обязательные домены системы, которые:
- регистрируются напрямую в CoreRuntime через ModuleManager
- не зависят от PluginManager
- используют только Core API (storage, event_bus, service_registry, state_engine, http)

КОНТРАКТ LIFECYCLE:
- register() вызывается ровно один раз при регистрации модуля
- start() вызывается ровно один раз при runtime.start()
- stop() вызывается ровно один раз при runtime.stop()
- Порядок: __init__ → register() → start() → stop()

КОНТРАКТ IDEMPOTENCY:
- register() должен быть идемпотентным (повторные вызовы безопасны)
- ModuleManager защищает от двойной регистрации одного имени
- Один экземпляр модуля может быть зарегистрирован только один раз

КОНТРАКТ REQUIRED vs OPTIONAL:
- REQUIRED модули обязательны для работы runtime
- Runtime не стартует, если REQUIRED модуль не зарегистрирован или не запустился
- OPTIONAL модули могут отсутствовать или фейлиться без остановки runtime

Подробный контракт: docs/07-RUNTIME-MODULE-CONTRACT.md
"""

from abc import ABC, abstractmethod
from typing import (
    Any,
    Awaitable,
    Callable,
    Optional,
    Protocol,
    runtime_checkable,
)

from core.runtime.runtime_context import RuntimeContext
from core.service._acl import PreloadResourceFunc
from core.service.models import ServiceAuthConfig

# Тип для сервисной функции: async (*args, **kwargs) -> Any
ServiceFunc = Callable[..., Awaitable[Any]]


@runtime_checkable
class SupportsContext(Protocol):
    def create_context(self) -> RuntimeContext:
        """Создать ограниченный runtime-контекст."""
        ...


class RuntimeModule(ABC):
    """
    Базовый класс для встроенных модулей Runtime.

    RuntimeModule — это доменный или инфраструктурный модуль, который
    подключается *снаружи* (на уровне приложения / bootstrap) через ModuleManager.

    Важно:
    - CoreRuntime сам по себе не знает, какие домены существуют
    - Любой модуль может быть отключён/удалён (если приложение не пометило его REQUIRED)
    - Модуль не обязан быть "обязательным доменом" по определению
      (например: `devices` может быть required для продукта, а `automation` — optional)

    LIFECYCLE:
        - register() вызывается ровно один раз при регистрации модуля
        - start() вызывается ровно один раз при runtime.start()
        - stop() вызывается ровно один раз при runtime.stop()
        - Порядок: __init__ → register() → start() → stop()

    IDEMPOTENCY:
        - register() должен быть идемпотентным (повторные вызовы безопасны)
        - ModuleManager защищает от двойной регистрации одного имени
        - Один экземпляр модуля может быть зарегистрирован только один раз
    """

    def __init__(
        self,
        runtime_or_context: RuntimeContext | SupportsContext,
    ):
        """
        Инициализация модуля.

        Args:
            runtime_or_context: экземпляр RuntimeContext или runtime с create_context()
        """
        self.runtime: SupportsContext | None
        self.context: RuntimeContext

        if isinstance(runtime_or_context, RuntimeContext):
            self.context = runtime_or_context
            self.runtime = None
            return

        self.runtime = runtime_or_context

        create_context = getattr(runtime_or_context, "create_context", None)
        if callable(create_context):
            maybe_context = create_context()
            if isinstance(maybe_context, RuntimeContext):
                self.context = maybe_context
                return
            # Some tests/mocks define create_context() but return None or a non-RuntimeContext.
            # Fall back to a best-effort RuntimeContext constructed from runtime attributes.

        # Backward compatibility for lightweight tests/mocks without create_context().
        self.context = RuntimeContext(
            storage=getattr(runtime_or_context, "storage", None),
            vault=getattr(runtime_or_context, "vault", None),
            services=getattr(runtime_or_context, "service_registry", None),
            http=getattr(runtime_or_context, "http", None),
            capabilities=getattr(
                runtime_or_context,
                "capability_registry",
                getattr(runtime_or_context, "capabilities", None),
            ),
            operations=getattr(runtime_or_context, "operations", None),
            state=getattr(
                runtime_or_context,
                "state_engine",
                getattr(runtime_or_context, "state", None),
            ),
        )

    async def register_service(
        self,
        name: str,
        func: ServiceFunc,
        *,
        resource: Optional[str] = None,
        admin_only: bool = False,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[PreloadResourceFunc] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
        auth_config: Optional[ServiceAuthConfig] = None,
    ) -> None:
        """
        Удобный helper для регистрации сервиса из модулей без копипасты.

        Автоматически:
        - пробрасывает RuntimeContext как первый аргумент в доменные service-функции
        - вешает ACL-метаданные через ServiceRegistry.register_with_acl
        """

        async def _wrapper(*args: object, **kwargs: object) -> Any:
            return await func(self.context, *args, **kwargs)

        reg = self.context.services
        register_with_acl: Callable[..., Awaitable[Any]] | None = getattr(
            reg, "register_with_acl", None
        )
        try:
            if register_with_acl is not None:
                await register_with_acl(
                    name,
                    _wrapper,
                    resource=resource,
                    admin_only=admin_only,
                    filter_result=filter_result,
                    enforce_result=enforce_result,
                    preload_resource=preload_resource,
                    inject_owner_param=inject_owner_param,
                    version=version,
                    auth_config=auth_config,
                )
                return

            await reg.register(name, _wrapper, version=version, auth_config=auth_config)
        except ValueError:
            # Service already registered (hot-reload / repeated test setup) — skip silently.
            pass

    async def register_runtime_service(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *,
        resource: Optional[str] = None,
        admin_only: bool = False,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[PreloadResourceFunc] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
        auth_config: Optional[ServiceAuthConfig] = None,
    ) -> None:
        """
        Удобный helper для регистрации сервиса из модулей, где доменный хендлер
        ожидает `runtime` первым аргументом (исторический контракт многих модулей).
        """

        async def _wrapper(*args: object, **kwargs: object) -> Any:
            return await func(self.runtime, *args, **kwargs)

        reg = self.context.services
        register_with_acl: Callable[..., Awaitable[Any]] | None = getattr(
            reg, "register_with_acl", None
        )
        try:
            if register_with_acl is not None:
                await register_with_acl(
                    name,
                    _wrapper,
                    resource=resource,
                    admin_only=admin_only,
                    filter_result=filter_result,
                    enforce_result=enforce_result,
                    preload_resource=preload_resource,
                    inject_owner_param=inject_owner_param,
                    version=version,
                    auth_config=auth_config,
                )
                return

            await reg.register(name, _wrapper, version=version, auth_config=auth_config)
        except ValueError:
            # Service already registered (hot-reload / repeated test setup) — skip silently.
            pass

    async def register_raw_service(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *,
        resource: Optional[str] = None,
        admin_only: bool = False,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[PreloadResourceFunc] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
        auth_config: Optional[ServiceAuthConfig] = None,
    ) -> None:
        """
        Зарегистрировать сервис "как есть" (без инъекции runtime/context в аргументы).

        Нужен для glue-хендлеров, которые уже закрыли над собой runtime/контекст
        или имеют нестандартную сигнатуру.
        """

        async def _wrapper(*args: object, **kwargs: object) -> Any:
            return await func(*args, **kwargs)

        reg = self.context.services
        register_with_acl: Callable[..., Awaitable[Any]] | None = getattr(
            reg, "register_with_acl", None
        )
        try:
            if register_with_acl is not None:
                await register_with_acl(
                    name,
                    _wrapper,
                    resource=resource,
                    admin_only=admin_only,
                    filter_result=filter_result,
                    enforce_result=enforce_result,
                    preload_resource=preload_resource,
                    inject_owner_param=inject_owner_param,
                    version=version,
                    auth_config=auth_config,
                )
                return

            await reg.register(name, _wrapper, version=version, auth_config=auth_config)
        except ValueError:
            # Service already registered (hot-reload / repeated test setup) — skip silently.
            pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Уникальное имя модуля.

        Returns:
            имя модуля (например, "devices", "presence", "operations")
        """
        pass

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Выполняется при создании модуля через ModuleManager.
        Здесь регистрируются:
        - сервисы в service_registry
        - подписки на события в event_bus
        - HTTP endpoints в http_registry (опционально)

        КОНТРАКТ:
        - Вызывается ровно один раз при регистрации модуля
        - Должен быть идемпотентным (повторные вызовы безопасны)
        - ModuleManager защищает от двойной регистрации одного имени

        По умолчанию — no-op. Переопределяется в подклассах.
        """
        pass

    async def start(self) -> None:
        """
        Запуск модуля.

        Вызывается при runtime.start().
        Здесь выполняется инициализация, которая требует запущенного runtime.

        КОНТРАКТ:
        - Вызывается ровно один раз при runtime.start()
        - Вызывается после успешного register()
        - Для REQUIRED модулей ошибка в start() останавливает runtime

        По умолчанию — no-op. Переопределяется в подклассах.
        """
        pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Вызывается при runtime.stop().
        Здесь выполняется cleanup, отписка от событий и т.д.

        КОНТРАКТ:
        - Вызывается ровно один раз при runtime.stop()
        - Вызывается даже при частичном старте (если start() упал)
        - Должен быть безопасным (можно вызывать даже если start() не был вызван)

        По умолчанию — no-op. Переопределяется в подклассах.
        """
        pass
