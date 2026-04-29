"""
Internal API — эндпоинты только для межсервисной коммуникации.

Доступны только с правильным INTERNAL_API_KEY.
Не документируются в OpenAPI.
Монтируются на /internal/v1/...
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/internal/v1", include_in_schema=False)

INTERNAL_API_KEY = (os.getenv("INTERNAL_API_KEY", "") or "").strip()


async def verify_internal_key(authorization: str = Header(...)) -> None:
    """Проверить что запрос пришёл от доверенного сервиса."""
    if not INTERNAL_API_KEY:
        raise HTTPException(503, "Internal API not configured")
    token = authorization.removeprefix("Bearer ").strip()
    if token != INTERNAL_API_KEY:
        raise HTTPException(401, "Invalid internal API key")


class ServiceCallRequest(BaseModel):
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ServiceCallResponse(BaseModel):
    result: Any = None
    error: str | None = None


def create_internal_router(runtime: Any) -> APIRouter:
    """Фабрика router'а с доступом к runtime."""

    @router.post(
        "/services/{service_name}",
        response_model=ServiceCallResponse,
        dependencies=[Depends(verify_internal_key)],
    )
    async def call_service(service_name: str, body: ServiceCallRequest) -> ServiceCallResponse:
        try:
            result = await runtime.service_registry.call(
                service_name, *body.args, **body.kwargs
            )
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            elif hasattr(result, "__dict__"):
                result = vars(result)
            return ServiceCallResponse(result=result)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except Exception as e:
            return ServiceCallResponse(error=str(e))

    @router.get(
        "/services/{service_name}/exists",
        dependencies=[Depends(verify_internal_key)],
    )
    async def service_exists(service_name: str) -> dict[str, Any]:
        exists = await runtime.service_registry.has_service(service_name)
        if not exists:
            raise HTTPException(404, f"Service '{service_name}' not found")
        return {"service": service_name, "exists": True}

    @router.get(
        "/services",
        dependencies=[Depends(verify_internal_key)],
    )
    async def list_services() -> dict[str, Any]:
        services = await runtime.service_registry.list_services()
        return {"services": services}

    return router

