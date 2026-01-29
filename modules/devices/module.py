"""
DevicesModule — встроенный модуль управления устройствами.

Обязательный домен системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from core.runtime_module import RuntimeModule
from . import services, handlers


class DevicesModule(RuntimeModule):
    """
    Модуль управления устройствами.

    Регистрирует сервисы для работы с устройствами и подписывается
    на события внешних устройств.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "devices"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.

        Регистрирует сервисы и подписывается на события.
        """
        # Регистрация сервисов (+ централизованный ACL через ServiceRegistry.register_with_acl)
        service_names = [
            ("devices.list", services.list_devices),
            ("devices.get", services.get_device),
            ("devices.create", services.create_device),
            ("devices.set_state", services.set_state),
            ("devices.list_external", services.list_external),
            ("devices.create_mapping", services.create_mapping),
            ("devices.list_mappings", services.list_mappings),
            ("devices.delete_mapping", services.delete_mapping),
            ("devices.auto_map_external", services.auto_map_external),
            ("devices.get_hung_pending", services.get_hung_pending_devices),
            ("devices.clear_pending", services.clear_pending_device),
        ]

        acl_meta = {
            "devices.list": {"resource": "device", "filter_result": True},
            "devices.get": {"resource": "device", "enforce_result": True},
            # на create делаем owner injection (owner_id=ctx.user_id), без копипасты в services.py
            "devices.create": {"inject_owner_param": "owner_id"},
            # для set_state делаем preload устройства до выполнения (важно: write)
            "devices.set_state": {"resource": "device", "preload": "device_by_id"},
            # инвентарь/маппинги — admin-only при наличии ctx
            "devices.list_external": {"admin_only": True},
            "devices.create_mapping": {"admin_only": True},
            "devices.list_mappings": {"admin_only": True},
            "devices.delete_mapping": {"admin_only": True},
            "devices.auto_map_external": {"admin_only": True},
            # Diagnostics — admin-only
            "devices.get_hung_pending": {"admin_only": True},
            "devices.clear_pending": {"admin_only": True},
        }

        self._registered_services = []

        for name, func in service_names:
            # Skip services that are already registered (idempotent)
            try:
                if await self.runtime.service_registry.has_service(name):
                    continue
            except Exception:
                # If service_registry doesn't implement has_service for some reason,
                # fall back to attempting registration and catching ValueError below.
                pass

            async def _wrapper(*args, _func=func, **kwargs):
                return await _func(self.runtime, *args, **kwargs)

            try:
                meta = acl_meta.get(name, {})

                # preload loaders
                preload_resource = None
                if meta.get("preload") == "device_by_id":
                    async def _preload(args, kwargs, _runtime=self.runtime):
                        device_id = None
                        if args:
                            device_id = args[0]
                        if device_id is None:
                            device_id = kwargs.get("device_id") or kwargs.get("id")
                        if not device_id:
                            return None
                        return await _runtime.storage.get("devices", device_id)

                    preload_resource = _preload

                if hasattr(self.runtime.service_registry, "register_with_acl"):
                    await self.runtime.service_registry.register_with_acl(
                        name,
                        _wrapper,
                        resource=meta.get("resource"),
                        admin_only=bool(meta.get("admin_only", False)),
                        filter_result=bool(meta.get("filter_result", False)),
                        enforce_result=bool(meta.get("enforce_result", False)),
                        preload_resource=preload_resource,
                        inject_owner_param=meta.get("inject_owner_param"),
                    )
                else:
                    # Fallback: older ServiceRegistry without ACL support
                    await self.runtime.service_registry.register(name, _wrapper)
                self._registered_services.append(name)
            except ValueError:
                # already registered concurrently — skip
                continue

        # Подписка на события
        await self.runtime.event_bus.subscribe(
            "external.device_state_reported",
            self._handle_external_state
        )
        await self.runtime.event_bus.subscribe(
            "external.device_discovered",
            self._handle_external_device_discovered
        )

    async def start(self) -> None:
        """
        Запуск модуля.

        Запускает background task для очистки зависших pending команд.
        """
        # Запускаем background cleaner для зависших pending команд
        try:
            from .pending_cleaner import start_pending_cleaner
            await start_pending_cleaner(self.runtime)
        except Exception as e:
            # Логируем но не ломаем старт модуля
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Failed to start pending cleaner: {e}",
                    module="devices"
                )
            except Exception:
                pass

    async def stop(self) -> None:
        """
        Остановка модуля.

        Отписывается от событий и отменяет регистрацию сервисов.
        """
        # Отписка от событий
        try:
            await self.runtime.event_bus.unsubscribe(
                "external.device_state_reported",
                self._handle_external_state
            )
        except Exception:
            pass

        try:
            await self.runtime.event_bus.unsubscribe(
                "external.device_discovered",
                self._handle_external_device_discovered
            )
        except Exception:
            pass

        # Отмена регистрации сервисов
        for service_name in getattr(self, "_registered_services", []):
            try:
                await self.runtime.service_registry.unregister(service_name)
            except Exception:
                pass

    async def _handle_external_state(self, event_type: str, data: dict) -> None:
        """Обработчик события external.device_state_reported."""
        await handlers.handle_external_state(self.runtime, data)

    async def _handle_external_device_discovered(self, event_type: str, data: dict) -> None:
        """Обработчик события external.device_discovered."""
        await handlers.handle_external_device_discovered(self.runtime, data)
