"""
HTTP Client wrapper для логирования всех исходящих HTTP запросов.

Предоставляет обёртку над aiohttp.ClientSession, которая автоматически
логирует все запросы в RequestLoggerModule.

Использует aiohttp trace_config для перехвата запросов без изменения
поведения оригинального ClientSession.
"""

import time
import uuid
from typing import Any, Optional, Dict
import aiohttp
from contextvars import ContextVar

from modules.request_logger.middleware import get_request_id, get_operation_id


class LoggedClientSession:
    """
    Обёртка над aiohttp.ClientSession для логирования всех запросов.
    
    Автоматически логирует:
    - URL, метод, заголовки, тело запроса
    - Статус код, заголовки, тело ответа
    - Длительность запроса
    - Привязка к request_id текущего HTTP запроса (если есть)
    
    Использует aiohttp trace_config для перехвата запросов без изменения
    поведения оригинального ClientSession.
    """
    
    def __init__(self, runtime: Any, source: str = "unknown", **session_kwargs):
        """
        Инициализация обёртки.
        
        Args:
            runtime: экземпляр CoreRuntime для доступа к service_registry
            source: источник запроса (имя плагина/модуля для логирования)
            **session_kwargs: параметры для aiohttp.ClientSession
        """
        self.runtime = runtime
        self.source = source
        self._has_request_logger = None
        
        # Создаём trace_config для перехвата запросов
        trace_config = self._create_trace_config()
        
        # Создаём ClientSession с trace_config
        if "trace_configs" not in session_kwargs:
            session_kwargs["trace_configs"] = [trace_config]
        else:
            session_kwargs["trace_configs"].append(trace_config)
        
        self._session = aiohttp.ClientSession(**session_kwargs)
    
    def _create_trace_config(self) -> aiohttp.TraceConfig:
        """Создаёт trace_config для перехвата запросов."""
        trace_config = aiohttp.TraceConfig()
        
        async def on_request_start(session, trace_config_ctx, params):
            """Вызывается при начале запроса."""
            trace_config_ctx.start_time = time.time()
            # Используем operation_id вместо request_id
            # operation_id = request_id для HTTP запросов, или новый UUID для system операций
            trace_config_ctx.operation_id = get_operation_id()
            trace_config_ctx.request_id = get_request_id()  # Сохраняем для обратной совместимости
            # Определяем origin: "http" если есть request_id, иначе "system"
            trace_config_ctx.origin = "http" if trace_config_ctx.request_id else "system"
            trace_config_ctx.method = params.method
            trace_config_ctx.url = str(params.url)
            trace_config_ctx.headers = dict(params.headers) if params.headers else {}
            trace_config_ctx.body = None
            
            # Сохраняем body если есть
            if hasattr(params, "json") and params.json:
                trace_config_ctx.body = params.json
            elif hasattr(params, "data") and params.data:
                try:
                    if isinstance(params.data, (dict, list)):
                        trace_config_ctx.body = params.data
                    else:
                        trace_config_ctx.body = str(params.data)[:1000]  # Ограничиваем размер
                except Exception:
                    pass
        
        async def on_request_end(session, trace_config_ctx, params):
            """Вызывается при завершении запроса."""
            if not await self._check_request_logger():
                return
            
            duration_ms = (time.time() - trace_config_ctx.start_time) * 1000
            
            # Читаем тело ответа для логирования
            # ВАЖНО: Читаем body только если response ещё не был прочитан
            # Это может сломать код, который ожидает прочитать body позже,
            # но для большинства случаев это работает
            response_body = None
            try:
                # Проверяем, не был ли response уже прочитан
                # Если response._body уже установлен, значит body уже прочитан
                if not hasattr(params.response, '_body') or params.response._body is None:
                    # Пытаемся прочитать body
                    try:
                        # Используем peek() для безопасного чтения без потребления
                        # Но peek() может быть недоступен, поэтому используем read()
                        body_bytes = await params.response.read()
                        if body_bytes:
                            # Пытаемся распарсить как JSON
                            try:
                                import json
                                response_body = json.loads(body_bytes.decode("utf-8"))
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                # Если не JSON, сохраняем как строку (ограничиваем размер)
                                text = body_bytes.decode("utf-8", errors="replace")
                                response_body = text[:10000] if len(text) <= 10000 else text[:10000] + "... (truncated)"
                            
                            # Восстанавливаем body для оригинального response
                            # Сохраняем прочитанные байты в _body
                            params.response._body = body_bytes
                    except Exception:
                        # Если не удалось прочитать body, продолжаем без него
                        pass
            except Exception:
                # Если не удалось прочитать body, продолжаем без него
                pass
            
            # Маскируем чувствительные данные
            sensitive_headers = ["authorization", "cookie", "x-api-key", "api-key"]
            sanitized_request_headers = {}
            for k, v in trace_config_ctx.headers.items():
                if k.lower() in sensitive_headers:
                    sanitized_request_headers[k] = "***"
                else:
                    sanitized_request_headers[k] = v
            
            sanitized_response_headers = {}
            for k, v in params.response.headers.items():
                if k.lower() in ["set-cookie"]:
                    sanitized_response_headers[k] = "***"
                else:
                    sanitized_response_headers[k] = v
            
            # Логируем запрос в обычный logger (чтобы видеть в консоли)
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="info",
                    message=f"Outgoing HTTP {trace_config_ctx.method} {trace_config_ctx.url}",
                    plugin=self.source,
                    context={
                        "method": trace_config_ctx.method,
                        "url": trace_config_ctx.url,
                    }
                )
            except Exception:
                pass
            
            # Логируем запрос в request_logger используя operation_id
            await self.runtime.service_registry.call(
                "request_logger.log",
                request_id=trace_config_ctx.operation_id,  # Используем operation_id вместо request_id
                level="info",
                message=f"Outgoing HTTP {trace_config_ctx.method} {trace_config_ctx.url}",
                context={
                    "type": "outgoing_request",
                    "source": self.source,
                    "origin": trace_config_ctx.origin,  # "http" или "system"
                    "method": trace_config_ctx.method,
                    "url": trace_config_ctx.url,
                    "headers": sanitized_request_headers,
                    "body": trace_config_ctx.body,
                }
            )
            
            # Сохраняем метаданные запроса и ответа
            request_metadata = {
                "method": trace_config_ctx.method,
                "url": trace_config_ctx.url,
                "path": str(params.response.url.path) if hasattr(params.response, "url") else "",
                "headers": sanitized_request_headers,
                "body": trace_config_ctx.body,
                "direction": "outgoing",  # Исходящий запрос от ядра/плагина
                "origin": trace_config_ctx.origin,  # "http" или "system"
            }
            
            response_metadata = {
                "status_code": params.response.status,
                "headers": sanitized_response_headers,
                "body": response_body,
                "duration_ms": duration_ms,
            }
            
            # Сохраняем метаданные используя operation_id
            await self.runtime.service_registry.call(
                "request_logger.set_request_metadata",
                request_id=trace_config_ctx.operation_id,  # Используем operation_id вместо request_id
                request_metadata=request_metadata,
                response_metadata=response_metadata
            )
            
            # Логируем ответ в обычный logger (чтобы видеть в консоли)
            status = params.response.status
            level = "info" if 200 <= status < 400 else "warning" if 400 <= status < 500 else "error"
            
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level=level,
                    message=f"Outgoing HTTP {trace_config_ctx.method} {trace_config_ctx.url} -> HTTP {status}",
                    plugin=self.source,
                    context={
                        "method": trace_config_ctx.method,
                        "url": trace_config_ctx.url,
                        "status_code": status,
                        "duration_ms": duration_ms,
                    }
                )
            except Exception:
                pass
            
            await self.runtime.service_registry.call(
                "request_logger.log",
                request_id=trace_config_ctx.operation_id,  # Используем operation_id вместо request_id
                level=level,
                message=f"Outgoing HTTP {trace_config_ctx.method} {trace_config_ctx.url} completed",
                context={
                    "type": "outgoing_response",
                    "source": self.source,
                    "origin": trace_config_ctx.origin,  # "http" или "system"
                    "status_code": status,
                    "headers": sanitized_response_headers,
                    "body": response_body,
                    "duration_ms": duration_ms,
                }
            )
        
        async def on_request_exception(session, trace_config_ctx, params):
            """Вызывается при ошибке запроса."""
            if not await self._check_request_logger():
                return
            
            duration_ms = (time.time() - trace_config_ctx.start_time) * 1000
            
            # Логируем ошибку в обычный logger
            try:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"Outgoing HTTP {trace_config_ctx.method} {trace_config_ctx.url} failed: {type(params.exception).__name__}: {str(params.exception)}",
                    plugin=self.source,
                    context={
                        "method": trace_config_ctx.method,
                        "url": trace_config_ctx.url,
                        "error": str(params.exception),
                        "error_type": type(params.exception).__name__,
                    }
                )
            except Exception:
                pass
            
            # Маскируем чувствительные данные
            sensitive_headers = ["authorization", "cookie", "x-api-key", "api-key"]
            sanitized_headers = {}
            for k, v in trace_config_ctx.headers.items():
                if k.lower() in sensitive_headers:
                    sanitized_headers[k] = "***"
                else:
                    sanitized_headers[k] = v
            
            # Сохраняем метаданные запроса и ответа с ошибкой
            request_metadata = {
                "method": trace_config_ctx.method,
                "url": trace_config_ctx.url,
                "path": "",
                "headers": sanitized_headers,
                "body": trace_config_ctx.body,
                "direction": "outgoing",  # Исходящий запрос от ядра/плагина
                "origin": trace_config_ctx.origin,  # "http" или "system"
            }
            
            response_metadata = {
                "status_code": 0,
                "error": str(params.exception),
                "error_type": type(params.exception).__name__,
                "duration_ms": duration_ms,
            }
            
            # Сохраняем метаданные используя operation_id
            await self.runtime.service_registry.call(
                "request_logger.set_request_metadata",
                request_id=trace_config_ctx.operation_id,  # Используем operation_id вместо request_id
                request_metadata=request_metadata,
                response_metadata=response_metadata
            )
            
            await self.runtime.service_registry.call(
                "request_logger.log",
                request_id=trace_config_ctx.operation_id,  # Используем operation_id вместо request_id
                level="error",
                message=f"Outgoing HTTP {trace_config_ctx.method} {trace_config_ctx.url} failed",
                context={
                    "type": "outgoing_request",
                    "source": self.source,
                    "origin": trace_config_ctx.origin,  # "http" или "system"
                    "method": trace_config_ctx.method,
                    "url": trace_config_ctx.url,
                    "headers": sanitized_headers,
                    "body": trace_config_ctx.body,
                    "error": str(params.exception),
                    "error_type": type(params.exception).__name__,
                    "duration_ms": duration_ms,
                }
            )
        
        trace_config.on_request_start.append(on_request_start)
        trace_config.on_request_end.append(on_request_end)
        trace_config.on_request_exception.append(on_request_exception)
        
        return trace_config
    
    async def _check_request_logger(self) -> bool:
        """Проверяет, доступен ли RequestLoggerModule."""
        if self._has_request_logger is None:
            try:
                self._has_request_logger = await self.runtime.service_registry.has_service("request_logger.log")
            except Exception:
                self._has_request_logger = False
        return self._has_request_logger
    
    async def _log_outgoing_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Any = None,
        response_status: Optional[int] = None,
        response_headers: Optional[Dict[str, str]] = None,
        response_body: Any = None,
        duration_ms: float = 0,
        error: Optional[str] = None
    ) -> None:
        """Логирует исходящий HTTP запрос."""
        if not await self._check_request_logger():
            return
        
        # Получаем request_id из контекста (если есть)
        request_id = get_request_id()
        if not request_id:
            # Если нет request_id, создаём новый для этого исходящего запроса
            request_id = str(uuid.uuid4())
        
        try:
            # Маскируем чувствительные данные в заголовках
            sensitive_headers = ["authorization", "cookie", "x-api-key", "api-key"]
            sanitized_headers = {}
            if headers:
                for k, v in headers.items():
                    if k.lower() in sensitive_headers:
                        sanitized_headers[k] = "***"
                    else:
                        sanitized_headers[k] = v
            
            # Логируем запрос
            await self.runtime.service_registry.call(
                "request_logger.log",
                request_id=request_id,
                level="info",
                message=f"Outgoing HTTP {method} {url}",
                context={
                    "type": "outgoing_request",
                    "source": self.source,
                    "method": method,
                    "url": str(url),
                    "headers": sanitized_headers,
                    "body": body if body else None,
                }
            )
            
            # Логируем ответ
            if error:
                await self.runtime.service_registry.call(
                    "request_logger.log",
                    request_id=request_id,
                    level="error",
                    message=f"Outgoing HTTP {method} {url} failed",
                    context={
                        "type": "outgoing_response",
                        "source": self.source,
                        "error": error,
                        "duration_ms": duration_ms,
                    }
                )
            elif response_status is not None:
                sanitized_response_headers = {}
                if response_headers:
                    for k, v in response_headers.items():
                        if k.lower() in ["set-cookie"]:
                            sanitized_response_headers[k] = "***"
                        else:
                            sanitized_response_headers[k] = v
                
                await self.runtime.service_registry.call(
                    "request_logger.log",
                    request_id=request_id,
                    level="info" if 200 <= response_status < 400 else "warning" if 400 <= response_status < 500 else "error",
                    message=f"Outgoing HTTP {method} {url} completed",
                    context={
                        "type": "outgoing_response",
                        "source": self.source,
                        "status_code": response_status,
                        "headers": sanitized_response_headers,
                        "body": response_body if response_body else None,
                        "duration_ms": duration_ms,
                    }
                )
        except Exception:
            # Игнорируем ошибки логирования, чтобы не ломать основной функционал
            pass
    
    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Проксирует request к оригинальному session."""
        return await self._session.request(method, url, **kwargs)
    
    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """GET запрос."""
        return await self._session.get(url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """POST запрос."""
        return await self._session.post(url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """PUT запрос."""
        return await self._session.put(url, **kwargs)
    
    async def patch(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """PATCH запрос."""
        return await self._session.patch(url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """DELETE запрос."""
        return await self._session.delete(url, **kwargs)
    
    async def head(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """HEAD запрос."""
        return await self._session.head(url, **kwargs)
    
    async def options(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """OPTIONS запрос."""
        return await self._session.options(url, **kwargs)
    
    def __getattr__(self, name: str) -> Any:
        """Проксирует все остальные атрибуты к оригинальному session."""
        return getattr(self._session, name)
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._session.close()
    
    async def close(self):
        """Закрыть сессию."""
        await self._session.close()


def create_logged_session(runtime: Any, source: str = "unknown", **session_kwargs) -> LoggedClientSession:
    """
    Создаёт обёрнутый aiohttp.ClientSession с логированием.
    
    Args:
        runtime: экземпляр CoreRuntime
        source: источник запросов (имя плагина/модуля)
        **session_kwargs: параметры для aiohttp.ClientSession
        
    Returns:
        LoggedClientSession обёртка
        
    Example:
        async with create_logged_session(runtime, source="yandex_smart_home") as session:
            async with await session.get("https://api.example.com/data") as resp:
                data = await resp.json()
    """
    return LoggedClientSession(runtime, source, **session_kwargs)
