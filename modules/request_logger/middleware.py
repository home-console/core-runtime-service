
"""
Middleware для перехвата HTTP запросов и записи логов в RequestLoggerModule.
"""
import logging
import uuid
import time
from typing import Any, Callable, Optional
from contextvars import ContextVar
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
logger = logging.getLogger(__name__)

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


async def _log_request_to_console(
    runtime: Any,
    method: str,
    path: str,
    status_code: int,
    duration_sec: float,
    client: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """
    Логирует каждый HTTP-запрос в консоль из ядра (одна строка: метод путь статус длительность).
    Сначала пробует logger.log, при недоступности — print(), чтобы запросы всегда были видны.
    """
    duration_ms = int(duration_sec * 1000)
    client_str = f" {client}" if client else ""
    err_str = f" {error}" if error else ""
    message = f"{method} {path} {status_code} {duration_ms}ms{client_str}{err_str}"

    try:
        if runtime and await runtime.service_registry.has_service("logger.log"):
            await runtime.service_registry.call(
                "logger.log",
                level="info",
                message=message,
                component="http",
                context={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client": client,
                    "error": error,
                },
            )
            return
    except STORAGE_BOUNDARY_ERRORS:
        logger.debug(
            "_log_request_to_console: logger.log unavailable (storage boundary)",
            exc_info=True,
        )
    except Exception:
        logger.debug("_log_request_to_console: logger.log failed", exc_info=True)
    print(f"[http] {message}")


class RequestLoggerOperationContext:
    """
    Адаптер для Core: реализует OperationContextProvider, делегируя в ContextVar.
    Регистрируется в core.runtime.operation_context при старте RequestLoggerModule.
    """

    def get_operation_id(self) -> Optional[str]:
        return get_operation_id()

    def set_operation_id(self, value: str) -> None:
        set_operation_id(value)


async def request_logger_middleware(request: Request, call_next: Callable) -> Response:
    """
    Middleware для перехвата HTTP запросов и записи логов.
    
    SECURITY: Sanitizes sensitive data (tokens, passwords, headers) before logging.
    In DEBUG mode, logs request/response bodies for debugging.
    In production mode, does NOT log bodies to prevent data exfiltration.
    
    Создаёт request_id для каждого запроса и записывает все логи в RequestLoggerModule.
    """
    import os
    
    # SECURITY: Import sanitizer
    from modules.security import sanitize_for_logging
    
    # Check if DEBUG mode enabled
    debug_mode = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    
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
    # SECURITY: Sanitize sensitive headers
    sanitized_request_headers = sanitize_for_logging(request_headers)
    
    # SECURITY: Capture request body ONLY in DEBUG mode
    request_body = None
    if debug_mode:
        try:
            if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
                # Пытаемся прочитать body
                body_bytes = await request.body()
                if body_bytes:
                    try:
                        import json
                        request_body = json.loads(body_bytes.decode("utf-8"))
                        # SECURITY: Sanitize body even in debug mode
                        request_body = sanitize_for_logging(request_body)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Если не JSON, сохраняем как строку (ограничиваем размер)
                        request_body = body_bytes.decode("utf-8", errors="replace")[:10000]
        except ClientDisconnect:
            logger.debug(
                "request_logger middleware: client disconnected while reading request body",
                exc_info=True,
            )
        except Exception:
            logger.debug(
                "request_logger middleware: request body capture failed", exc_info=True
            )
    
    # Сохраняем метаданные запроса
    request_metadata = {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "headers": sanitized_request_headers,
        "body": request_body if debug_mode else None,  # Only in DEBUG mode
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
        # SECURITY: Sanitize sensitive response headers
        sanitized_response_headers = sanitize_for_logging(response_headers)
        
        # SECURITY: Capture response body ONLY in DEBUG mode
        response_body = None
        if debug_mode:
            try:
                # Проверяем, есть ли body в response (для JSONResponse)
                if hasattr(response, "body"):
                    body_bytes = response.body
                    if body_bytes:
                        try:
                            import json
                            response_body = json.loads(body_bytes.decode("utf-8"))
                            # SECURITY: Sanitize body even in debug mode
                            response_body = sanitize_for_logging(response_body)
                        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                            # Если не JSON, сохраняем как строку (ограничиваем размер)
                            try:
                                response_body = body_bytes.decode("utf-8", errors="replace")[:10000]
                            except (AttributeError, TypeError):
                                response_body = str(body_bytes)[:10000] if body_bytes else None
            except Exception:
                logger.debug(
                    "request_logger middleware: response body capture failed",
                    exc_info=True,
                )
        
        # Сохраняем метаданные ответа
        response_metadata = {
            "status_code": response.status_code,
            "headers": sanitized_response_headers,
            "body": response_body if debug_mode else None,  # Only in DEBUG mode
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

        # Логируем каждый запрос в консоль из ядра (один раз на запрос: метод путь статус длительность)
        await _log_request_to_console(
            runtime,
            request.method,
            request.url.path,
            response.status_code,
            duration,
            request.client.host if request.client else None,
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
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "request_logger middleware: error-path metadata (storage boundary)",
                exc_info=True,
            )
        except Exception:
            logger.debug(
                "request_logger middleware: error-path metadata logging failed",
                exc_info=True,
            )

        # Логируем запрос в консоль даже при ошибке
        await _log_request_to_console(
            runtime,
            request.method,
            request.url.path,
            500,
            duration,
            request.client.host if request.client else None,
            error=str(e),
        )
        
        # Пробрасываем исключение дальше
        raise
