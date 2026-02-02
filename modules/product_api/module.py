"""
ProductApiModule — BFF (Backend for Frontend) для пользовательских клиентов.

- Product API НЕ использует Inspector.
- Product API МОЖЕТ вызывать service_registry.call() и агрегировать данные из доменных сервисов.
- Product API НЕ регистрирует operations handlers.
- Product API = для пользователей (User UI / Mobile / Mini-app).
- Inspector = для админов/дебага.

Ручки вида /api/v1/devices делегируют в доменные сервисы devices.list, devices.get.
Состояние не читается напрямую — только через доменные сервисы.
"""

from typing import Any

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint


class ProductApiModule(RuntimeModule):
    """
    Модуль Product API (BFF).
    Регистрирует HTTP endpoints /api/v1/* и сервисы product_api.v1.*,
    которые вызывают доменные сервисы (devices.list, devices.get и т.д.).
    """

    @property
    def name(self) -> str:
        return "product_api"

    async def register(self) -> None:
        runtime = self.runtime

        async def _devices_list(**kwargs: Any) -> Any:
            """BFF: GET /api/v1/devices → devices.list()."""
            return await runtime.service_registry.call("devices.list")

        async def _devices_get(id: str, **kwargs: Any) -> Any:
            """BFF: GET /api/v1/devices/{id} → devices.get(id)."""
            return await runtime.service_registry.call("devices.get", id)

        await runtime.service_registry.register("product_api.v1.devices.list", _devices_list)
        await runtime.service_registry.register("product_api.v1.devices.get", _devices_get)

        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/api/v1/devices",
            service="product_api.v1.devices.list",
            description="Product API: list devices (BFF → devices.list)",
        ))
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/api/v1/devices/{id}",
            service="product_api.v1.devices.get",
            description="Product API: get device by id (BFF → devices.get)",
        ))

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for name in ("product_api.v1.devices.list", "product_api.v1.devices.get"):
            try:
                await self.runtime.service_registry.unregister(name)
            except Exception:
                pass
