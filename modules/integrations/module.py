"""
IntegrationModule — модуль для HTTP endpoints интеграций.

Декларирует HTTP endpoints и регистрирует сервис admin.v1.integrations.
AdminModule не знает про integrations; список интеграций предоставляет этот модуль.
"""

from core.runtime_module import RuntimeModule
from core.http import HttpEndpoint


class IntegrationsModule(RuntimeModule):
    """
    Модуль HTTP endpoints для интеграций.
    Владеет GET /admin/v1/integrations и GET /api/v1/user/integrations.
    """

    @property
    def name(self) -> str:
        return "integrations"

    async def register(self) -> None:
        from modules.admin.integrations import admin_v1_integrations
        from modules.api.user_integrations import user_v1_integrations

        # Сервис: список интеграций для admin (с полной информацией о плагинах)
        async def _admin_wrap(**kw):
            return await admin_v1_integrations(self.runtime)

        # Сервис: список интеграций для пользователя
        async def _user_wrap(**kw):
            return await user_v1_integrations(self.runtime)

        try:
            services = self.runtime.kernel_context.get_service("service_registry")
            await services.register_with_acl(
                "admin.v1.integrations", _admin_wrap, admin_only=True
            )
            await services.register_with_acl(
                "user.v1.integrations", _user_wrap, admin_only=False
            )
        except ValueError:
            pass
        
        # Admin endpoint with full information
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/integrations",
            service="admin.v1.integrations",
            description="List registered integrations (admin only)"
        ))

        # User endpoint
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/api/v1/user/integrations",
            service="user.v1.integrations",
            description="List user integrations"
        ))

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
