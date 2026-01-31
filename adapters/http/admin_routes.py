"""
HTTP inbound adapter для admin API endpoints.

Вызывает сервисы через service_registry, не содержит бизнес-логики.
ACL проверяется на уровне сервисов.
"""

from typing import Any
from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from core.http_registry import HttpEndpoint


def create_admin_router(runtime: Any) -> APIRouter:
    """Создаёт FastAPI router для admin endpoints."""
    router = APIRouter(prefix="/admin/v1", tags=["admin"])
    
    # Регистрируем HTTP контракты в HttpRegistry
    runtime.http.register(
        HttpEndpoint(
            method="GET",
            path="/admin/v1/integrations",
            service="admin.v1.integrations",
            description="List registered integrations"
        )
    )
    
    @router.get("/integrations")
    async def get_integrations(request: Request):
        """GET /admin/v1/integrations - список интеграций."""
        try:
            result = await runtime.service_registry.call("admin.v1.integrations")
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
