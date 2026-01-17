"""
RequestLoggerModule — модуль для хранения полных логов каждого запроса.

Хранит логи всех HTTP запросов и вызовов сервисов с привязкой к request_id.
Логи хранятся в памяти с ограничением по размеру (последние N запросов).
"""

import uuid
import time
from typing import Any, Dict, List, Optional
from collections import deque
from datetime import datetime

from core.runtime_module import RuntimeModule


class RequestLoggerModule(RuntimeModule):
    """
    Модуль для хранения полных логов каждого запроса.
    
    Хранит логи в памяти с ограничением по размеру.
    Предоставляет сервисы для записи и чтения логов.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "request_logger"

    def __init__(self, runtime: Any):
        """Инициализация модуля."""
        super().__init__(runtime)
        # Хранилище логов: operation_id -> список логов
        # operation_id = request_id для HTTP запросов, или новый UUID для system операций
        self._request_logs: Dict[str, List[Dict[str, Any]]] = {}
        # Хранилище метаданных запросов: operation_id -> метаданные (метод, URL, заголовки, тело, ответ)
        self._request_metadata: Dict[str, Dict[str, Any]] = {}
        # Очередь operation_id для ограничения размера (FIFO)
        # Для обратной совместимости используем старое имя переменной
        self._request_ids_queue: deque = deque(maxlen=1000)  # Храним последние 1000 операций
        # Максимальное количество логов на операцию
        self._max_logs_per_request = 1000

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Регистрирует сервисы для записи и чтения логов.
        """
        # Регистрируем сервисы
        await self.runtime.service_registry.register(
            "request_logger.log",
            self._log_service
        )
        await self.runtime.service_registry.register(
            "request_logger.get_request_logs",
            self._get_request_logs_service
        )
        await self.runtime.service_registry.register(
            "request_logger.list_requests",
            self._list_requests_service
        )
        await self.runtime.service_registry.register(
            "request_logger.clear_logs",
            self._clear_logs_service
        )
        await self.runtime.service_registry.register(
            "request_logger.set_request_metadata",
            self._set_request_metadata_service
        )
        await self.runtime.service_registry.register(
            "request_logger.create_http_session",
            self._create_http_session_service
        )

    async def start(self) -> None:
        """Запуск модуля."""
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="RequestLogger module started",
                module="request_logger"
            )
        except Exception:
            pass

    async def stop(self) -> None:
        """Остановка модуля."""
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="RequestLogger module stopped",
                module="request_logger"
            )
        except Exception:
            pass

        # Отменяем регистрацию сервисов
        try:
            await self.runtime.service_registry.unregister("request_logger.log")
            await self.runtime.service_registry.unregister("request_logger.get_request_logs")
            await self.runtime.service_registry.unregister("request_logger.list_requests")
            await self.runtime.service_registry.unregister("request_logger.clear_logs")
        except Exception:
            pass

        # Очищаем хранилище
        self._request_logs.clear()
        self._request_metadata.clear()
        self._request_ids_queue.clear()

    async def _log_service(
        self,
        request_id: str,
        level: str,
        message: str,
        **context: Any
    ) -> None:
        """
        Сервис для записи лога в контексте операции.
        
        Args:
            request_id: уникальный идентификатор операции (operation_id)
                       Для HTTP запросов это request_id, для system операций - operation_id
            level: уровень логирования (debug, info, warning, error)
            message: сообщение
            **context: дополнительный контекст
        """
        # request_id теперь может быть operation_id (для обратной совместимости API)
        operation_id = request_id
        
        # Создаём запись лога
        log_entry = {
            "timestamp": time.time(),
            "datetime": datetime.utcnow().isoformat() + "Z",
            "level": (level or "info").lower(),
            "message": message,
            "context": context or {},
        }

        # Добавляем лог к операции
        if operation_id not in self._request_logs:
            # Новая операция - добавляем в очередь
            self._request_logs[operation_id] = []
            self._request_ids_queue.append(operation_id)
            
            # Если превышен лимит операций, удаляем старые
            if len(self._request_ids_queue) > 1000:
                old_operation_id = self._request_ids_queue.popleft()
                if old_operation_id in self._request_logs:
                    del self._request_logs[old_operation_id]
                if old_operation_id in self._request_metadata:
                    del self._request_metadata[old_operation_id]

        # Добавляем лог к операции
        logs = self._request_logs[operation_id]
        logs.append(log_entry)
        
        # Если превышен лимит логов на операцию, удаляем старые
        if len(logs) > self._max_logs_per_request:
            logs[:] = logs[-self._max_logs_per_request:]

    async def _get_request_logs_service(self, request_id: str) -> Dict[str, Any]:
        """
        Сервис для получения всех логов операции.
        
        Args:
            request_id: уникальный идентификатор операции (operation_id)
                       Для HTTP запросов это request_id, для system операций - operation_id
            
        Returns:
            Словарь с информацией об операции и списком логов
        """
        # request_id теперь может быть operation_id (для обратной совместимости API)
        operation_id = request_id
        
        logs = self._request_logs.get(operation_id, [])
        metadata = self._request_metadata.get(operation_id, {})
        
        return {
            "request_id": operation_id,  # Возвращаем operation_id как request_id для обратной совместимости
            "logs_count": len(logs),
            "logs": logs,
            "request": metadata.get("request", {}),
            "response": metadata.get("response", {}),
        }

    async def _list_requests_service(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Сервис для получения списка операций.
        
        Args:
            limit: максимальное количество операций
            offset: смещение для пагинации
            
        Returns:
            Словарь со списком операций и метаданными
        """
        # Получаем список operation_id в обратном порядке (новые первыми)
        # Для обратной совместимости используем старое имя переменной
        request_ids = list(reversed(self._request_ids_queue))
        
        # Применяем пагинацию
        paginated_ids = request_ids[offset:offset + limit]
        
        # Собираем информацию о каждом запросе
        requests_info = []
        for req_id in paginated_ids:
            logs = self._request_logs.get(req_id, [])
            metadata = self._request_metadata.get(req_id, {})
            request_info = metadata.get("request", {})
            response_info = metadata.get("response", {})
            
            # Включаем операции даже если нет метаданных, но есть логи
            # (для system операций может не быть request_metadata)
            if logs:
                first_log = logs[0] if logs else {}
                last_log = logs[-1] if logs else {}
                # Определяем direction и origin
                # Сначала проверяем метаданные запроса
                direction = request_info.get("direction")
                origin = request_info.get("origin")
                
                # Если origin не найден в метаданных, ищем в контексте логов
                # (для system операций origin устанавливается в контексте логов)
                if not origin:
                    for log in logs:
                        log_context = log.get("context", {})
                        if "origin" in log_context:
                            origin = log_context.get("origin")
                            break
                    # Если все еще не найден, используем значение по умолчанию
                    if not origin:
                        origin = "http"  # По умолчанию "http" для обратной совместимости
                
                if not direction:
                    # Пытаемся определить из контекста логов
                    for log in logs:
                        log_context = log.get("context", {})
                        # Исходящие - это запросы от ядра/плагинов (type: outgoing_request, source не frontend)
                        if log_context.get("type") == "outgoing_request" and log_context.get("source") != "frontend":
                            direction = "outgoing"
                            break
                        # Входящие - это запросы на бэкенд (от фронтенда или через middleware)
                        elif log_context.get("type") == "incoming_request" or log_context.get("source") == "frontend":
                            direction = "incoming"
                            break
                    # По умолчанию: если origin="system", то direction="outgoing", иначе "incoming"
                    if not direction:
                        if origin == "system":
                            direction = "outgoing"
                        else:
                            direction = "incoming"
                
                requests_info.append({
                    "request_id": req_id,
                    "method": request_info.get("method"),
                    "path": request_info.get("path"),
                    "status_code": response_info.get("status_code"),
                    "started_at": first_log.get("datetime") if first_log else None,
                    "finished_at": last_log.get("datetime") if last_log else None,
                    "duration_ms": response_info.get("duration_ms"),
                    "logs_count": len(logs),
                    "has_errors": any(log.get("level") == "error" for log in logs),
                    "direction": direction,
                    "origin": origin,  # Добавляем origin для различения HTTP и system операций
                })
        
        return {
            "total": len(request_ids),
            "limit": limit,
            "offset": offset,
            "requests": requests_info,
        }

    async def _create_http_session_service(self, source: str = "unknown", **session_kwargs) -> Any:
        """
        Сервис для создания обёрнутого aiohttp.ClientSession с логированием.
        
        Args:
            source: источник запросов (имя плагина/модуля)
            **session_kwargs: параметры для aiohttp.ClientSession
            
        Returns:
            LoggedClientSession обёртка
        """
        from modules.request_logger.http_client import create_logged_session
        return create_logged_session(self.runtime, source, **session_kwargs)

    async def _set_request_metadata_service(
        self,
        request_id: str,
        request_metadata: Dict[str, Any],
        response_metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Сервис для сохранения метаданных запроса и ответа.
        
        Args:
            request_id: уникальный идентификатор операции (operation_id)
                       Для HTTP запросов это request_id, для system операций - operation_id
            request_metadata: метаданные запроса (method, url, headers, body, origin)
            response_metadata: метаданные ответа (status_code, headers, body)
        """
        # request_id теперь может быть operation_id (для обратной совместимости API)
        operation_id = request_id
        
        if operation_id not in self._request_metadata:
            self._request_metadata[operation_id] = {}
        
        self._request_metadata[operation_id]["request"] = request_metadata
        if response_metadata:
            self._request_metadata[operation_id]["response"] = response_metadata

    async def _clear_logs_service(self) -> Dict[str, Any]:
        """
        Сервис для очистки всех логов.
        
        Returns:
            Подтверждение очистки
        """
        count = len(self._request_logs)
        self._request_logs.clear()
        self._request_metadata.clear()
        self._request_ids_queue.clear()
        
        return {
            "cleared": count,
            "message": f"Cleared {count} request logs",
        }
