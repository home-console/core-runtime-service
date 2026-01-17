"""
Middleware для перехвата HTTP запросов и записи логов в RequestLoggerModule.
"""

import uuid
import time
from typing import Any, Callable, Optional
from contextvars import ContextVar
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ContextVar для хранения request_id в текущем контексте выполнения
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
# ContextVar для хранения operation_id в текущем контексте выполнения
# operation_id = request_id для HTTP запросов, или новый UUID для system операций
_operation_id_var: ContextVar[Optional[str]] = ContextVar("operation_id", default=None)


def get_request_id() -> Optional[str]:
    """Получить request_id из текущего контекста выполнения."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Установить request_id в текущий контекст выполнения."""
    _request_id_var.set(request_id)
    # Для HTTP запросов operation_id = request_id
    _operation_id_var.set(request_id)


def get_operation_id() -> Optional[str]:
    """Получить operation_id из текущего контекста выполнения.
    
    operation_id = request_id для HTTP запросов, или новый UUID для system операций.
    """
    operation_id = _operation_id_var.get()
    if operation_id is None:
        # Если нет operation_id, но есть request_id, используем его
        request_id = _request_id_var.get()
        if request_id:
            operation_id = request_id
            _operation_id_var.set(operation_id)
        # Если нет ни operation_id, ни request_id - возвращаем None
        # Это позволяет operation() context manager создать новый UUID и установить метаданные
    return operation_id


def set_operation_id(operation_id: str) -> None:
    """Установить operation_id в текущий контекст выполнения."""
    _operation_id_var.set(operation_id)


async def request_logger_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware для перехвата HTTP запросов и записи логов.
    
    Создаёт request_id для каждого запроса и записывает все логи в RequestLoggerModule.
    Захватывает полную информацию о запросе и ответе (заголовки, тело).
    """
    runtime = request.app.state.runtime
    
    # Генерируем request_id (или используем из заголовка X-Request-ID)
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    
    # Для HTTP запросов operation_id = request_id
    operation_id = request_id
    
    # Сохраняем request_id в request.state для доступа из handlers
    request.state.request_id = request_id
    
    # Устанавливаем request_id и operation_id в контекст выполнения для автоматической передачи в логи
    set_request_id(request_id)
    # set_request_id уже устанавливает operation_id = request_id, но явно устанавливаем для ясности
    _operation_id_var.set(operation_id)
    
    # Пропускаем логирование для endpoint логирования (чтобы избежать рекурсии и шума)
    if request.url.path == "/admin/v1/request-logs/log":
        # Просто выполняем запрос без логирования
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    
    # Начало запроса
    start_time = time.time()
    
    # Захватываем информацию о запросе
    request_headers = dict(request.headers)
    # Убираем чувствительные данные из заголовков
    sensitive_headers = ["authorization", "cookie", "x-api-key"]
    sanitized_request_headers = {
        k: "***" if k.lower() in sensitive_headers else v
        for k, v in request_headers.items()
    }
    
    # Захватываем тело запроса
    # ВАЖНО: FastAPI может уже прочитать body в handler'е, поэтому мы пытаемся прочитать его здесь
    # Если body уже прочитано, request.body() может вернуть пустые байты или выбросить исключение
    request_body = None
    try:
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            # Проверяем, есть ли body в request.state (может быть сохранено в handler'е)
            if hasattr(request.state, "request_body"):
                request_body = request.state.request_body
            else:
                # Пытаемся прочитать body напрямую
                body_bytes = await request.body()
                if body_bytes:
                    try:
                        # Пытаемся распарсить как JSON
                        import json
                        request_body = json.loads(body_bytes.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Если не JSON, сохраняем как строку (ограничиваем размер)
                        request_body = body_bytes.decode("utf-8", errors="replace")[:10000]
    except Exception:
        # Игнорируем ошибки при чтении тела (body может быть уже прочитано)
        pass
    
    # Сохраняем метаданные запроса
    request_metadata = {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "headers": sanitized_request_headers,
        "body": request_body,
        "client": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "direction": "incoming",  # Входящий запрос
        "origin": "http",  # HTTP запрос
    }
    
    try:
        # Проверяем, доступен ли RequestLoggerModule
        has_request_logger = await runtime.service_registry.has_service("request_logger.log")
        
        if has_request_logger:
            # Сохраняем метаданные запроса используя operation_id (который равен request_id для HTTP запросов)
            await runtime.service_registry.call(
                "request_logger.set_request_metadata",
                request_id=operation_id,  # Используем operation_id вместо request_id
                request_metadata=request_metadata
            )
            
            # Логируем начало запроса (только в request_logger, не в обычный logger чтобы избежать двойного логирования)
            await runtime.service_registry.call(
                "request_logger.log",
                request_id=operation_id,  # Используем operation_id вместо request_id
                level="info",
                message=f"HTTP {request.method} {request.url.path}",
                context={
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": dict(request.query_params),
                    "client": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                    "origin": "http",  # HTTP запрос
                }
            )
        
        # Выполняем запрос
        response = await call_next(request)
        
        # Добавляем request_id в заголовки ответа
        response.headers["X-Request-ID"] = request_id
        
        # Конец запроса
        duration = time.time() - start_time
        
        # Захватываем информацию об ответе
        response_headers = dict(response.headers)
        # Убираем чувствительные данные из заголовков ответа
        sanitized_response_headers = {
            k: "***" if k.lower() in ["set-cookie"] else v
            for k, v in response_headers.items()
        }
        
        # Захватываем тело ответа
        # Используем кастомный Response wrapper для захвата body
        response_body = None
        try:
            # Проверяем, есть ли body в response (для JSONResponse)
            if hasattr(response, "body"):
                body_bytes = response.body
                if body_bytes:
                    try:
                        import json
                        response_body = json.loads(body_bytes.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                        # Если не JSON или не bytes, пытаемся получить как строку
                        try:
                            response_body = body_bytes.decode("utf-8", errors="replace")[:10000]
                        except (AttributeError, TypeError):
                            # Если body не bytes, возможно это уже dict/str
                            response_body = str(body_bytes)[:10000] if body_bytes else None
            elif hasattr(response, "body_iterator"):
                # Для StreamingResponse читаем iterator
                body_chunks = []
                async for chunk in response.body_iterator:
                    body_chunks.append(chunk)
                
                if body_chunks:
                    body_bytes = b"".join(body_chunks)
                    try:
                        import json
                        response_body = json.loads(body_bytes.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        response_body = body_bytes.decode("utf-8", errors="replace")[:10000]
                
                # Восстанавливаем body iterator для ответа
                from starlette.responses import StreamingResponse
                async def body_generator():
                    for chunk in body_chunks:
                        yield chunk
                
                response = StreamingResponse(
                    body_generator(),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type
                )
        except Exception:
            # Если не удалось захватить тело, продолжаем без него
            pass
        
        # Сохраняем метаданные ответа
        response_metadata = {
            "status_code": response.status_code,
            "headers": sanitized_response_headers,
            "body": response_body,
            "duration_ms": duration * 1000,
        }
        
        if has_request_logger:
            # Сохраняем метаданные ответа используя operation_id
            await runtime.service_registry.call(
                "request_logger.set_request_metadata",
                request_id=operation_id,  # Используем operation_id вместо request_id
                request_metadata=request_metadata,
                response_metadata=response_metadata
            )
            
            # Логируем завершение запроса
            await runtime.service_registry.call(
                "request_logger.log",
                request_id=operation_id,  # Используем operation_id вместо request_id
                level="info",
                message=f"HTTP {request.method} {request.url.path} completed",
                context={
                    "status_code": response.status_code,
                    "duration_ms": duration * 1000,
                    "origin": "http",  # HTTP запрос
                }
            )
        
        return response
        
    except Exception as e:
        # Ошибка при обработке запроса
        duration = time.time() - start_time
        
        # Сохраняем метаданные ответа с ошибкой
        error_response_metadata = {
            "status_code": 500,
            "error": str(e),
            "error_type": type(e).__name__,
            "duration_ms": duration * 1000,
        }
        
        try:
            has_request_logger = await runtime.service_registry.has_service("request_logger.log")
            if has_request_logger:
                # Получаем operation_id для этого запроса
                operation_id = _operation_id_var.get() or request_id
                
                # Сохраняем метаданные ответа с ошибкой используя operation_id
                await runtime.service_registry.call(
                    "request_logger.set_request_metadata",
                    request_id=operation_id,  # Используем operation_id вместо request_id
                    request_metadata=request_metadata,
                    response_metadata=error_response_metadata
                )
                
                await runtime.service_registry.call(
                    "request_logger.log",
                    request_id=operation_id,  # Используем operation_id вместо request_id
                    level="error",
                    message=f"HTTP {request.method} {request.url.path} failed",
                    context={
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "duration_ms": duration * 1000,
                        "origin": "http",  # HTTP запрос
                    }
                )
        except Exception:
            pass
        
        # Пробрасываем исключение дальше
        raise
