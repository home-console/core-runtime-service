"""
IntegrationModule — модуль для HTTP endpoints интеграций.

Декларирует HTTP endpoints и регистрирует сервис admin.v1.integrations.
AdminModule не знает про integrations; список интеграций предоставляет этот модуль.
"""

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint


class IntegrationsModule(RuntimeModule):
    """
    Модуль HTTP endpoints для интеграций.
    Владеет GET /admin/v1/integrations и сервисом admin.v1.integrations.
    """

    @property
    def name(self) -> str:
        return "integrations"

    async def register(self) -> None:
        from modules.admin.integrations import admin_v1_integrations

        # Сервис: список интеграций (generic, без имён плагинов в контракте)
        async def _wrap(**kw):
            return await admin_v1_integrations(self.runtime)

        try:
            if hasattr(self.runtime.service_registry, "register_with_acl"):
                await self.runtime.service_registry.register_with_acl(
                    "admin.v1.integrations", _wrap, admin_only=True
                )
            else:
                await self.runtime.service_registry.register("admin.v1.integrations", _wrap)
        except ValueError:
            pass

        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/integrations",
            service="admin.v1.integrations",
            description="List registered integrations"
        ))

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
