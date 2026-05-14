"""
OperationsModule — модуль для HTTP endpoints операций.

Декларирует HTTP endpoints для управления операциями.
Services (admin.operations.*) остаются в AdminModule.
Это разделение: HTTP ownership vs Service ownership.
"""

from typing import List

from core.runtime.runtime_module import RuntimeModule
from core.http.models import HttpEndpoint, EndpointAuthConfig
from modules.api.schemas import (
    ApiResponse,
    CancelRetryResponse,
    CreateOperationRequest,
    CreateOperationResponse,
    ExecutionDto,
    OperationDto,
)


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
            path="/api/v1/admin/operations",
            service="admin.operations.create",
            description="Create and execute an operation",
            auth_config=_admin_write,
            tags=["Operations"],
            response_model=CreateOperationResponse,
            request_model=CreateOperationRequest,
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/api/v1/admin/operations",
            service="admin.operations.list",
            description="List operations with pagination",
            auth_config=_admin_read,
            tags=["Operations"],
            response_model=ApiResponse[List[OperationDto]],
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/api/v1/admin/operations/{operation_id}",
            service="admin.operations.get",
            description="Get operation details by ID",
            auth_config=_admin_read,
            tags=["Operations"],
            response_model=ApiResponse[OperationDto],
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/api/v1/admin/operations/{operation_id}/cancel",
            service="admin.operations.cancel",
            description="Cancel a pending or running operation",
            auth_config=_admin_write,
            tags=["Operations"],
            response_model=CancelRetryResponse,
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/api/v1/admin/operations/{operation_id}/retry",
            service="admin.operations.retry",
            description="Retry a failed operation",
            auth_config=_admin_write,
            tags=["Operations"],
            response_model=CancelRetryResponse,
        ))

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
