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
    
    # NOTE: IntegrationsModule already registers the /admin/v1/integrations
    # HttpEndpoint and the service `admin.v1.integrations`. Avoid duplicate
    # registration here to prevent double routes when both are enabled.
    
    @router.get("/integrations")
    async def get_integrations(request: Request):
        """GET /admin/v1/integrations - список интеграций."""
        try:
            result = await runtime.service_registry.call("admin.v1.integrations")
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
