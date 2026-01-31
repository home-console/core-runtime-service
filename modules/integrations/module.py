"""
IntegrationModule — модуль для HTTP endpoints интеграций.

Декларирует HTTP endpoints для управления интеграциями.
Services (admin.v1.integrations, admin.integrations.*) остаются в AdminModule.
Это разделение: HTTP ownership vs Service ownership.
"""

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint


class IntegrationsModule(RuntimeModule):
    """
    Модуль HTTP endpoints для интеграций.
    
    Владеет HTTP декларациями для integrations API.
    НЕ дублирует services - они в AdminModule.
    НЕ знает конкретные интеграции (yandex, zigbee и т.д.).
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "integrations"

    async def register(self) -> None:
        """
        Регистрация HTTP endpoints для интеграций.
        
        Декларирует только HTTP → service mapping.
        Services уже зарегистрированы в AdminModule.
        """
        # Integration management endpoints
        self.runtime.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/integrations",
            service="admin.v1.integrations",
            description="List registered integrations"
        ))
        
        # Note: enable/disable/status endpoints будут добавлены когда появятся соответствующие services
        # Пока существует только admin.v1.integrations (list)

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
