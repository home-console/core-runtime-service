"""
OperationsModule — модуль для HTTP endpoints операций.

Декларирует HTTP endpoints для управления операциями.
Services (admin.operations.*) остаются в AdminModule.
Это разделение: HTTP ownership vs Service ownership.
"""

from core.runtime.runtime_module import RuntimeModule
from core.http.models import HttpEndpoint, EndpointAuthConfig


class OperationsModule(RuntimeModule):
    """
    Модуль HTTP endpoints для операций.
    
    Владеет HTTP декларациями для operations API.
    НЕ дублирует services - они в AdminModule.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "operations"

    async def register(self) -> None:
        """
        Регистрация HTTP endpoints для операций.
        
        Декларирует только HTTP → service mapping.
        Services уже зарегистрированы в AdminModule.
        """
        # Operations API endpoints
        _admin_read = EndpointAuthConfig(required_scopes=["admin.read"])
        _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/operations",
            service="admin.operations.create",
            description="Create and execute an operation",
            auth_config=_admin_write,
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/operations",
            service="admin.operations.list",
            description="List operations with pagination",
            auth_config=_admin_read,
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/operations/{operation_id}",
            service="admin.operations.get",
            description="Get operation details by ID",
            auth_config=_admin_read,
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/operations/{operation_id}/cancel",
            service="admin.operations.cancel",
            description="Cancel a pending or running operation",
            auth_config=_admin_write,
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/operations/{operation_id}/retry",
            service="admin.operations.retry",
            description="Retry a failed operation",
            auth_config=_admin_write,
        ))

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
