"""
Service Registry — registry for service-based inter-plugin communication.

Реестр сервисов для между плагинов взаимодействия.

ACL builder и типы — см. core/service/_acl.py.
"""

import asyncio
from typing import Any, List, Optional

from core.service._acl import (
    PolicyEngineFactory,
    PreloadResourceFunc,
    ServiceAclWrapperBuilder,
    _default_acl_wrapper_builder,
    _default_policy_engine_factory,
)
from core.service.models import ServiceFunc, ServiceMiddleware
from core.service.service_executor import ServiceExecutor
from core.service.service_router import ServiceRouter


class ServiceRegistry:
    """
    Реестр сервисов для между плагинов взаимодействия.

    Принцип работы:
    - плагины регистрируют сервисы (методы)
    - другие плагины вызывают эти сервисы по имени
    - ServiceRegistry маршрутизирует вызовы
    - Все вызовы защищены timeout по умолчанию
    """

    def __init__(
        self,
        default_timeout: Optional[float] = None,
        *,
        policy_engine: Optional[Any] = None,
        policy_engine_factory: Optional[PolicyEngineFactory] = None,
        acl_wrapper_builder: Optional[ServiceAclWrapperBuilder] = None,
    ):
        """
        Инициализация ServiceRegistry.

        Args:
            default_timeout: дефолтный timeout для вызовов сервисов (секунды).
                           Если None, timeout не применяется (для обратной совместимости).
        """
        # Словарь: service_name -> function
        self._services: dict[str, ServiceFunc] = {}
        # Словарь: service_name -> ACL метаданные
        # {"resource": "device", "admin_only": bool, "filter_result": bool}
        self._service_acl: dict[str, dict[str, Any]] = {}
        # Lock для thread-safety операций с _services
        self._lock = asyncio.Lock()
        # Глобальные middleware для всех вызовов сервисов.
        self._middleware: list[ServiceMiddleware] = []
        # Дефолтный timeout для всех вызовов
        self._default_timeout: Optional[float] = default_timeout
        self._executor = ServiceExecutor(default_timeout=default_timeout)
        self._router = ServiceRouter(self._services)
        self._policy_engine_factory = (
            policy_engine_factory or _default_policy_engine_factory
        )
        self._acl_wrapper_builder = acl_wrapper_builder or _default_acl_wrapper_builder
        self._policy_engine = self._policy_engine_factory(policy_engine)

    async def add_middleware(self, middleware: ServiceMiddleware) -> None:
        """Добавить глобальный middleware для всех вызовов."""
        async with self._lock:
            self._middleware.append(middleware)

    async def remove_middleware(self, middleware: ServiceMiddleware) -> None:
        """Удалить глобальный middleware, если он зарегистрирован."""
        async with self._lock:
            try:
                self._middleware.remove(middleware)
            except ValueError:
                pass

    async def list_middleware(self) -> list[str]:
        """Список middleware для Inspector/diagnostics."""
        async with self._lock:
            return [getattr(m, "__class__", type(m)).__name__ for m in self._middleware]

    async def _invoke_with_middleware(
        self,
        service_name: str,
        func: ServiceFunc,
        middleware: list[ServiceMiddleware],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Выполнить сервис с цепочкой middleware."""
        return await self._executor.invoke_with_middleware(
            service_name,
            func,
            middleware,
            *args,
            **kwargs,
        )

    async def register(
        self, service_name: str, func: ServiceFunc, version: Optional[str] = None
    ) -> None:
        """
        Зарегистрировать сервис.

        Args:
            service_name: имя сервиса (например, "devices.turn_on")
            func: async функция-обработчик
            version: опциональная версия API (например, "v1", "v2")

        Пример:
            async def turn_on_device(device_id: str):
                # логика включения устройства
                pass

            await service_registry.register("devices.turn_on", turn_on_device)
            await service_registry.register("devices.turn_on", turn_on_device_v2, version="v2")
        """
        # Если указана версия, добавляем её к имени сервиса
        if version:
            versioned_name = f"{service_name}.{version}"
        else:
            versioned_name = service_name

        async with self._lock:
            if versioned_name in self._services:
                raise ValueError(f"Сервис '{versioned_name}' уже зарегистрирован")
            self._services[versioned_name] = func
            self._router.register(versioned_name)
            # Сбрасываем ACL метаданные, если были
            self._service_acl.pop(versioned_name, None)

    async def register_with_acl(
        self,
        service_name: str,
        func: ServiceFunc,
        *,
        resource: Optional[str] = None,
        admin_only: Optional[bool] = None,
        filter_result: bool = False,
        enforce_result: bool = False,
        preload_resource: Optional[PreloadResourceFunc] = None,
        inject_owner_param: Optional[str] = None,
        version: Optional[str] = None,
    ) -> None:
        """
        Зарегистрировать сервис с ACL-метаданными.

        Args:
            service_name: имя сервиса
            func: async функция-обработчик
            resource: логическое имя ресурса для политики (например, "device")
            admin_only: требует админ-доступ при наличии RequestContext
            filter_result: если True и результат — iterable[dict], отфильтрует через политику
            version: версия сервиса (опционально)
        """
        wrapped, effective_admin_only = self._acl_wrapper_builder(
            policy_engine=self._policy_engine,
            service_name=service_name,
            func=func,
            resource=resource,
            admin_only=admin_only,
            filter_result=filter_result,
            enforce_result=enforce_result,
            preload_resource=preload_resource,
            inject_owner_param=inject_owner_param,
        )

        await self.register(service_name, wrapped, version=version)
        versioned_name = f"{service_name}.{version}" if version else service_name
        self._service_acl[versioned_name] = {
            "resource": resource,
            "admin_only": effective_admin_only,
            "filter_result": filter_result,
            "enforce_result": enforce_result,
        }

    async def register_with_middleware(
        self, service_name: str, func: ServiceFunc, middleware: List[ServiceMiddleware]
    ) -> None:
        """
        Зарегистрировать сервис с middleware.

        Args:
            service_name: имя сервиса
            func: async функция-обработчик
            middleware: список middleware для применения

        Пример:
            class LoggingMiddleware(ServiceMiddleware):
                async def before_call(self, service_name, args, kwargs):
                    print(f"Calling {service_name}")

                async def after_call(self, service_name, result):
                    print(f"{service_name} returned {result}")

                async def on_error(self, service_name, error):
                    print(f"{service_name} failed: {error}")

            await service_registry.register_with_middleware(
                "devices.turn_on",
                turn_on_device,
                [LoggingMiddleware()]
            )
        """
        wrapped = self._executor.wrap_with_middleware(service_name, func, middleware)

        await self.register(service_name, wrapped)

    async def unregister(self, service_name: str) -> None:
        """
        Удалить сервис из реестра.

        Args:
            service_name: имя сервиса
        """
        async with self._lock:
            self._services.pop(service_name, None)
            self._router.unregister(service_name)

    async def call(self, service_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Вызвать сервис.

        Args:
            service_name: имя сервиса
            *args, **kwargs: аргументы для сервиса

        Returns:
            Результат выполнения сервиса

        Raises:
            ValueError: если сервис не найден
            asyncio.TimeoutError: если вызов превысил timeout (если установлен default_timeout)

        Пример:
            result = await service_registry.call("devices.turn_on", "lamp_kitchen")

        SECURITY NOTE:
        - ServiceRegistry.call() вызывает зарегистрированную функцию как есть.
        - Если сервис зарегистрирован через register_with_acl(), то проверки admin/policy выполняются
          внутри обёртки (до вызова исходного handler'а).
        - Boundary слой (ApiModule/AdminModule) всё равно должен ограничивать доступ к sensitive endpoints,
          но register_with_acl() является дополнительным уровнем защиты внутри процесса.

        TIMEOUT NOTE: Если установлен default_timeout, все вызовы защищены timeout автоматически.
        """
        # Получаем функцию под lock для thread-safety
        async with self._lock:
            func = self._router.resolve(service_name)
            if func is None:
                raise ValueError(f"Сервис '{service_name}' не найден")
            middleware = list(self._middleware)

        return await self._executor.execute(
            service_name,
            func,
            middleware,
            *args,
            **kwargs,
        )

    async def call_without_timeout(
        self,
        service_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Вызвать сервис, игнорируя default_timeout.

        Используется для долгоживущих операций (например, WebSocket‑хендлеров),
        которые по определению не укладываются в общий timeout.
        """
        async with self._lock:
            func = self._router.resolve(service_name)
            if func is None:
                raise ValueError(f"Сервис '{service_name}' не найден")
            middleware = list(self._middleware)
        return await self._executor.execute_without_timeout(
            service_name,
            func,
            middleware,
            *args,
            **kwargs,
        )

    async def call_with_timeout(
        self, service_name: str, timeout: float, *args: Any, **kwargs: Any
    ) -> Any:
        """
        Вызвать сервис с timeout.

        Args:
            service_name: имя сервиса
            timeout: timeout в секундах
            *args, **kwargs: аргументы для сервиса

        Returns:
            Результат выполнения сервиса

        Raises:
            ValueError: если сервис не найден
            asyncio.TimeoutError: если вызов превысил timeout

        Пример:
            result = await service_registry.call_with_timeout(
                "devices.turn_on",
                timeout=5.0,
                "lamp_kitchen"
            )
        """
        async with self._lock:
            func = self._router.resolve(service_name)
            if func is None:
                raise ValueError(f"Сервис '{service_name}' не найден")
            middleware = list(self._middleware)

        return await self._executor.execute_with_timeout(
            timeout,
            service_name,
            func,
            middleware,
            *args,
            **kwargs,
        )

    async def has_service(self, service_name: str) -> bool:
        """
        Проверить, существует ли сервис.

        Args:
            service_name: имя сервиса

        Returns:
            True если сервис зарегистрирован
        """
        async with self._lock:
            return service_name in self._services

    async def list_services(self) -> list[str]:
        """
        Получить список всех зарегистрированных сервисов.

        Returns:
            Список имён сервисов
        """
        async with self._lock:
            return list(self._services.keys())

    async def clear(self) -> None:
        """Очистить все сервисы."""
        async with self._lock:
            self._services.clear()
            self._router.clear()
            self._middleware.clear()

    async def get_versions(self, service_name: str) -> list[str]:
        """
        Получить список всех версий для сервиса.

        Args:
            service_name: имя сервиса (например, "devices.list")

        Returns:
            Список версий (например, ["v1", "v2"])

        Пример:
            versions = await service_registry.get_versions("devices.list")
            # Вернёт ["v1", "v2"] если есть devices.list.v1 и devices.list.v2
        """
        async with self._lock:
            return self._router.get_versions(service_name)

    async def is_deprecated(
        self, service_name: str, version: Optional[str] = None
    ) -> bool:
        """
        Проверить, является ли версия сервиса устаревшей.

        Args:
            service_name: имя сервиса
            version: версия API (если None, проверяет сервис без версии)

        Returns:
            True если версия помечена как deprecated

        Пример:
            if await service_registry.is_deprecated("devices.list", "v1"):
                print("Версия v1 устарела, используйте v2")
        """
        async with self._lock:
            return self._router.is_deprecated(service_name, version)

    async def mark_deprecated(
        self, service_name: str, version: Optional[str] = None
    ) -> None:
        """
        Пометить версию сервиса как устаревшую.

        Args:
            service_name: имя сервиса
            version: версия API (если None, помечает сервис без версии)

        Raises:
            ValueError: если сервис не найден

        Пример:
            await service_registry.mark_deprecated("devices.list", "v1")
        """
        async with self._lock:
            self._router.mark_deprecated(service_name, version)
