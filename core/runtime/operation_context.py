"""
Operation context — точка расширения для observability/correlation (operation_id).

Core не реализует хранение operation_id и не импортирует modules.
Модуль request_logger (или другой) регистрирует провайдер при старте;
Core только вызывает провайдер, если он установлен.
Если провайдер не установлен — get_operation_id() возвращает None, set_operation_id() не делает ничего.
"""

import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional, Protocol


class OperationContextProvider(Protocol):
    """Минимальный интерфейс для получения/установки operation_id в текущем контексте."""

    def get_operation_id(self) -> Optional[str]: ...
    def set_operation_id(self, value: str) -> None: ...


_provider: Optional[OperationContextProvider] = None


def set_operation_context_provider(
    provider: Optional[OperationContextProvider],
) -> None:
    """Установить провайдер контекста операций (вызывается модулем при start/stop)."""
    global _provider
    _provider = provider


def get_operation_context_provider() -> Optional[OperationContextProvider]:
    """Получить текущий провайдер (для тестов или диагностики)."""
    return _provider


def get_operation_id() -> Optional[str]:
    """
    Получить operation_id из текущего контекста выполнения.
    Если провайдер не установлен — возвращает None.
    """
    if _provider is None:
        return None
    return _provider.get_operation_id()


def set_operation_id(value: str) -> None:
    """
    Установить operation_id в текущий контекст выполнения.
    Если провайдер не установлен — ничего не делает.
    """
    if _provider is not None:
        _provider.set_operation_id(value)


@asynccontextmanager
async def operation(name: str, source: str, runtime: Optional[Any] = None):
    """
    Async context manager для system-level операций.

    При входе:
    - Создаёт новый UUID operation_id и устанавливает его через set_operation_id()
    - Записывает лог "operation.start"

    При успешном выходе:
    - Записывает лог "operation.ok"

    При ошибке:
    - Записывает лог "operation.error" с exception message
    - Пробрасывает исключение дальше

    Args:
        name: имя операции (например, "example.op")
        source: источник операции (имя плагина/модуля)
        runtime: экземпляр CoreRuntime (опционально, для логирования)

    Example:
        async with operation("example.op", "example_plugin", runtime):
            await do_work()
    """
    new_operation_id = str(uuid.uuid4())
    previous_operation_id = get_operation_id()
    set_operation_id(new_operation_id)
    operation_id = new_operation_id

    if runtime:
        try:
            try:
                has_request_logger = await runtime.service_registry.has_service(
                    "request_logger.set_request_metadata"
                )
                if has_request_logger:
                    await runtime.service_registry.call(
                        "request_logger.set_request_metadata",
                        request_id=operation_id,
                        request_metadata={
                            "method": "SYSTEM",
                            "url": f"system://{source}/{name}",
                            "path": f"/system/{source}/{name}",
                            "direction": "outgoing",
                            "origin": "system",
                        },
                    )
            except Exception:
                pass
            await runtime.service_registry.call(
                "logger.log",
                level="info",
                message="operation.start",
                plugin=source,
                operation_id=operation_id,
                operation_name=name,
                source=source,
                origin="system",
            )
        except Exception:
            pass

    try:
        yield operation_id
        if runtime:
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="info",
                    message="operation.ok",
                    plugin=source,
                    operation_id=operation_id,
                    operation_name=name,
                    source=source,
                    origin="system",
                )
            except Exception:
                pass
    except Exception as e:
        if runtime:
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message="operation.error",
                    plugin=source,
                    operation_id=operation_id,
                    operation_name=name,
                    source=source,
                    error=str(e),
                    error_type=type(e).__name__,
                    origin="system",
                )
            except Exception:
                pass
        raise
    finally:
        if previous_operation_id:
            set_operation_id(previous_operation_id)
