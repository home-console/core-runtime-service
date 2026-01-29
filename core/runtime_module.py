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
from typing import Any, Awaitable, Callable, Optional

# Тип для сервисной функции: async (*args, **kwargs) -> Any
ServiceFunc = Callable[..., Awaitable[Any]]


class RuntimeModule(ABC):
    """
    Базовый класс для встроенных модулей Runtime.

    Модули — это обязательные домены системы (devices, automation, presence),
    которые регистрируются автоматически при создании CoreRuntime.

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

    def __init__(self, runtime: Any):
        """
        Инициализация модуля.

        Args:
            runtime: экземпляр CoreRuntime
        """
        self.runtime = runtime

    async def register_service(
        self,
        name: str,
        func: ServiceFunc,
        *,
        resource: Optional[str] = None,
        admin_only: bool = False,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[Callable[[tuple, dict], Awaitable[Any]]] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
    ) -> None:
        """
        Удобный helper для регистрации сервиса из модулей без копипасты.

        Автоматически:
        - пробрасывает runtime как первый аргумент в доменные service-функции
        - вешает ACL-метаданные через ServiceRegistry.register_with_acl (если доступно)
        """

        async def _wrapper(*args, **kwargs):
            return await func(self.runtime, *args, **kwargs)

        reg = self.runtime.service_registry
        if hasattr(reg, "register_with_acl"):
            await reg.register_with_acl(
                name,
                _wrapper,
                resource=resource,
                admin_only=admin_only,
                filter_result=filter_result,
                enforce_result=enforce_result,
                preload_resource=preload_resource,
                inject_owner_param=inject_owner_param,
                version=version,
            )
        else:
            await reg.register(name, _wrapper, version=version)

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Уникальное имя модуля.

        Returns:
            имя модуля (например, "automation", "devices")
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
