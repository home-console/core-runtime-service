"""
Helper для system-level операций с четкими границами (operation boundaries).

Использует operation_id из request_logger для группировки логов.
"""

import uuid
from contextlib import asynccontextmanager
from typing import Optional, Any

from modules.request_logger.middleware import get_operation_id, set_operation_id


@asynccontextmanager
async def operation(name: str, source: str, runtime: Optional[Any] = None):
    """
    Async context manager для system-level операций.
    
    При входе:
    - Если operation_id не установлен → создает новый UUID и set_operation_id()
    - Записывает лог "operation.start"
    
    При успешном выходе:
    - Записывает лог "operation.ok"
    
    При ошибке:
    - Записывает лог "operation.error" с exception message
    - Пробрасывает исключение дальше
    
    Args:
        name: имя операции (например, "yandex.check_online")
        source: источник операции (например, "yandex_smart_home")
        runtime: экземпляр CoreRuntime (опционально, для логирования)
    
    Example:
        async with operation("yandex.check_online", "yandex_smart_home", runtime):
            await check_devices_online()
    """
    # ВСЕГДА создаем новый operation_id для system операций
    # Даже если operation() вызывается внутри HTTP запроса,
    # system операция должна иметь свой собственный operation_id с origin="system"
    new_operation_id = str(uuid.uuid4())
    
    # Сохраняем текущий operation_id (может быть от HTTP запроса)
    previous_operation_id = get_operation_id()
    
    # Устанавливаем новый operation_id для этой system операции
    set_operation_id(new_operation_id)
    operation_id = new_operation_id
    
    # Логируем начало операции
    if runtime:
        try:
            # Создаем request_metadata для system операций (чтобы origin был доступен в метаданных)
            try:
                has_request_logger = await runtime.service_registry.has_service("request_logger.set_request_metadata")
                if has_request_logger:
                    await runtime.service_registry.call(
                        "request_logger.set_request_metadata",
                        request_id=operation_id,
                        request_metadata={
                            "method": "SYSTEM",
                            "url": f"system://{source}/{name}",
                            "path": f"/system/{source}/{name}",
                            "direction": "outgoing",
                            "origin": "system",  # Явно помечаем как system операцию
                        }
                    )
            except Exception:
                pass  # Игнорируем ошибки создания метаданных
            
            # Специальные сообщения для oauth.refresh_token
            if name == "oauth.refresh_token":
                message = "Refreshing OAuth token"
            else:
                message = "operation.start"
            await runtime.service_registry.call(
                "logger.log",
                level="info",
                message=message,
                plugin=source,
                operation_id=operation_id,  # Явно передаем operation_id как отдельный параметр
                operation_name=name,
                source=source,
                origin="system",  # Явно помечаем как system операцию
            )
        except Exception:
            pass
    
    try:
        yield operation_id
        # Успешное завершение
        if runtime:
            try:
                # Специальные сообщения для oauth.refresh_token
                if name == "oauth.refresh_token":
                    message = "OAuth token refreshed"
                else:
                    message = "operation.ok"
                await runtime.service_registry.call(
                    "logger.log",
                    level="info",
                    message=message,
                    plugin=source,
                    operation_id=operation_id,  # Явно передаем operation_id как отдельный параметр
                    operation_name=name,
                    source=source,
                    origin="system",  # Явно помечаем как system операцию
                )
            except Exception:
                pass
    except Exception as e:
        # Ошибка при выполнении операции
        if runtime:
            try:
                # Специальные сообщения для oauth.refresh_token
                if name == "oauth.refresh_token":
                    message = "OAuth token refresh failed"
                else:
                    message = "operation.error"
                await runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=message,
                    plugin=source,
                    operation_id=operation_id,  # Явно передаем operation_id как отдельный параметр
                    operation_name=name,
                    source=source,
                    error=str(e),
                    error_type=type(e).__name__,
                    origin="system",  # Явно помечаем как system операцию
                )
            except Exception:
                pass
        # Пробрасываем исключение дальше
        raise
    finally:
        # Восстанавливаем предыдущий operation_id (например, от HTTP запроса)
        # Это важно, чтобы логи после operation() снова группировались с HTTP запросом
        if previous_operation_id:
            set_operation_id(previous_operation_id)
