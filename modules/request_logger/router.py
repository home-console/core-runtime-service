"""
API Router для RequestLoggerModule.
"""

from typing import Any, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Request, Body
from fastapi.responses import JSONResponse


def create_request_logger_router(runtime: Any) -> APIRouter:
    """
    Создаёт FastAPI роутер для RequestLoggerModule.
    
    Args:
        runtime: экземпляр CoreRuntime
        
    Returns:
        FastAPI роутер с endpoints для получения логов
    """
    router = APIRouter(prefix="/admin/v1/request-logs", tags=["request-logs"])
    
    @router.get("/{request_id}")
    async def get_request_logs(request_id: str):
        """
        Получить все логи для конкретного запроса.
        
        Args:
            request_id: уникальный идентификатор запроса
            
        Returns:
            Словарь с информацией о запросе и списком логов
        """
        try:
            if not await runtime.service_registry.has_service("request_logger.get_request_logs"):
                raise HTTPException(
                    status_code=503,
                    detail="RequestLogger module is not available. The module may not be loaded or failed to start. Check server logs for details."
                )
            
            result = await runtime.service_registry.call(
                "request_logger.get_request_logs",
                request_id=request_id
            )
            return result
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("")
    async def list_requests(
        limit: int = Query(100, ge=1, le=1000, description="Максимальное количество запросов"),
        offset: int = Query(0, ge=0, description="Смещение для пагинации")
    ):
        """
        Получить список запросов.
        
        Args:
            limit: максимальное количество запросов
            offset: смещение для пагинации
            
        Returns:
            Словарь со списком запросов и метаданными
        """
        try:
            if not await runtime.service_registry.has_service("request_logger.list_requests"):
                raise HTTPException(
                    status_code=503,
                    detail="RequestLogger module is not available. The module may not be loaded or failed to start. Check server logs for details."
                )
            
            result = await runtime.service_registry.call(
                "request_logger.list_requests",
                limit=limit,
                offset=offset
            )
            return result
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.delete("")
    async def clear_logs():
        """
        Очистить все логи запросов.
        
        Returns:
            Подтверждение очистки
        """
        try:
            if not await runtime.service_registry.has_service("request_logger.clear_logs"):
                raise HTTPException(
                    status_code=503,
                    detail="RequestLogger module is not available. The module may not be loaded or failed to start. Check server logs for details."
                )
            
            result = await runtime.service_registry.call("request_logger.clear_logs")
            return result
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/log")
    async def log_frontend_request(
        request: Request,
        body: Dict[str, Any] = Body(...)
    ):
        """
        Принять лог запроса с фронтенда.
        
        Body (JSON):
        {
            "request_id": "uuid",
            "level": "info",
            "message": "сообщение",
            "context": {...},
            "request_metadata": {...},
            "response_metadata": {...}
        }
        """
        try:
            if not await runtime.service_registry.has_service("request_logger.log"):
                raise HTTPException(
                    status_code=503,
                    detail="RequestLogger module is not available. The module may not be loaded or failed to start. Check server logs for details."
                )
            
            request_id = body.get("request_id")
            if not request_id:
                raise HTTPException(status_code=400, detail="request_id is required")
            
            level = body.get("level", "info")
            message = body.get("message", "")
            context = body.get("context", {})
            request_metadata = body.get("request_metadata")
            response_metadata = body.get("response_metadata")
            
            # Убеждаемся, что direction установлен (если не установлен, по умолчанию incoming)
            if request_metadata and "direction" not in request_metadata:
                request_metadata["direction"] = "incoming"
            
            # Логируем сообщение
            await runtime.service_registry.call(
                "request_logger.log",
                request_id=request_id,
                level=level,
                message=message,
                **context
            )
            
            # Сохраняем метаданные запроса и ответа, если они есть
            if request_metadata or response_metadata:
                await runtime.service_registry.call(
                    "request_logger.set_request_metadata",
                    request_id=request_id,
                    request_metadata=request_metadata or {},
                    response_metadata=response_metadata
                )
            
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
