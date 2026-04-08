"""
Operation context — точка расширения для observability/correlation (operation_id).

Core не реализует хранение operation_id и не импортирует modules.
Модуль request_logger (или другой) регистрирует провайдер при старте;
Core только вызывает провайдер, если он установлен.
Если провайдер не установлен — get_operation_id() возвращает None, set_operation_id() не делает ничего.

Operation logging вынесен в OperationLogger интерфейс — core не знает про logger.log сервисы.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from core.exception_groups import LOGGING_HELPER_ERRORS

_op_ctx_log = logging.getLogger(__name__)


class OperationContextProvider(Protocol):
    """Минимальный интерфейс для получения/установки operation_id в текущем контексте."""

    def get_operation_id(self) -> Optional[str]: ...
    def set_operation_id(self, value: str) -> None: ...


class OperationLogger(Protocol):
    """
    Интерфейс для логирования операций.
    
    Выносится в app-layer — core не знает про конкретные сервисы логирования.
    """
    
    async def log_operation_start(
        self,
        operation_id: str,
        operation_name: str,
        source: str,
    ) -> None:
        """Логировать начало операции."""
        ...
    
    async def log_operation_ok(
        self,
        operation_id: str,
        operation_name: str,
        source: str,
    ) -> None:
        """Логировать успешное завершение операции."""
        ...
    
    async def log_operation_error(
        self,
        operation_id: str,
        operation_name: str,
        source: str,
        error: str,
        error_type: str,
    ) -> None:
        """Логировать ошибку операции."""
        ...


@dataclass
class OperationContext:
    """
    Per-runtime operation context holder.

    This avoids module-level globals leaking between tests/runtimes/plugins.
    """

    _provider: Optional[OperationContextProvider] = None
    _logger: Optional[OperationLogger] = None

    def set_provider(self, provider: Optional[OperationContextProvider]) -> None:
        self._provider = provider

    def get_provider(self) -> Optional[OperationContextProvider]:
        return self._provider

    def set_logger(self, logger: Optional[OperationLogger]) -> None:
        self._logger = logger

    def get_operation_id(self) -> Optional[str]:
        if self._provider is None:
            return None
        return self._provider.get_operation_id()

    def set_operation_id(self, value: str) -> None:
        if self._provider is not None:
            self._provider.set_operation_id(value)

    @asynccontextmanager
    async def operation(self, name: str, source: str, runtime: Optional[Any] = None):
        new_operation_id = str(uuid.uuid4())
        previous_operation_id = self.get_operation_id()
        self.set_operation_id(new_operation_id)
        operation_id = new_operation_id

        if self._logger is not None:
            try:
                await self._logger.log_operation_start(
                    operation_id=operation_id,
                    operation_name=name,
                    source=source,
                )
            except (RuntimeError, TypeError, AttributeError, ValueError) as e:
                _op_ctx_log.debug("Failed to log operation.start: %s", e, exc_info=True)
            except LOGGING_HELPER_ERRORS as e:
                _op_ctx_log.debug("Failed to log operation.start (unexpected): %s", e, exc_info=True)

        try:
            yield operation_id
            if self._logger is not None:
                try:
                    await self._logger.log_operation_ok(
                        operation_id=operation_id,
                        operation_name=name,
                        source=source,
                    )
                except (RuntimeError, TypeError, AttributeError, ValueError) as e:
                    _op_ctx_log.debug("Failed to log operation.ok: %s", e, exc_info=True)
                except LOGGING_HELPER_ERRORS as e:
                    _op_ctx_log.debug("Failed to log operation.ok (unexpected): %s", e, exc_info=True)
        except LOGGING_HELPER_ERRORS as e:
            if self._logger is not None:
                try:
                    await self._logger.log_operation_error(
                        operation_id=operation_id,
                        operation_name=name,
                        source=source,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                except (RuntimeError, TypeError, AttributeError, ValueError):
                    _op_ctx_log.debug(
                        "operation_context.operation: log_operation_error failed (boundary)",
                        exc_info=True,
                    )
                except LOGGING_HELPER_ERRORS:
                    _op_ctx_log.debug(
                        "operation_context.operation: log_operation_error failed (unexpected)",
                        exc_info=True,
                    )
            raise
        finally:
            if previous_operation_id:
                self.set_operation_id(previous_operation_id)


# Process-global default context for the module-level `operation()` context manager.
# Plugins and modules should use RuntimeContext.operation_context for per-runtime isolation.
_DEFAULT_CONTEXT: OperationContext = OperationContext()


@asynccontextmanager
async def operation(name: str, source: str, runtime: Optional[Any] = None):
    """
    Async context manager для system-level операций.

    При входе:
    - Создаёт новый UUID operation_id и устанавливает его через set_operation_id()
    - Записывает лог "operation.start" (если OperationLogger установлен)

    При успешном выходе:
    - Записывает лог "operation.ok"

    При ошибке:
    - Записывает лог "operation.error" с exception message
    - Пробрасывает исключение дальше

    Args:
        name: имя операции (например, "example.op")
        source: источник операции (имя плагина/модуля)
        runtime: экземпляр CoreRuntime (опционально, для обратной совместимости)

    Example:
        async with operation("example.op", "example_plugin", runtime):
            await do_work()
    """
    async with _DEFAULT_CONTEXT.operation(name, source, runtime):
        yield _DEFAULT_CONTEXT.get_operation_id() or ""
