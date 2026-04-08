"""
Logger Helper - простой wrapper для логирования в core компонентах.

ВАЖНО: Этот helper ТОЛЬКО для core компонентов (runtime, module_manager, event_bus).
Плагины НЕ должны использовать этот helper!

Плагины должны использовать напрямую:
    await runtime.service_registry.call("logger.log", level="info", message="...", plugin="...")

Это работает для:
- Встроенных плагинов (plugins/*)
- Внешних плагинов через SDK
- Remote plugins

Почему не logger_helper для плагинов:
- Плагины не должны зависеть от внутренних helper'ов core
- Внешние плагины через SDK не имеют доступа к logger_helper
- service_registry.call("logger.log") - это публичный API, доступный всем

Использует встроенный LoggerModule через service_registry.
LoggerModule всегда доступен (приложение регистрирует его первым в APP_MODULES),
поэтому fallback'и минимальны - только для случаев до инициализации runtime.

Реальная логика логирования находится в modules/logger/module.py.
"""

import logging
import sys
from typing import Optional, Any

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from core.exception_groups import LOGGING_HELPER_ERRORS

_stdlog = logging.getLogger(__name__)


async def log(runtime: Optional[Any], level: str, message: str, **context: Any) -> None:
    """
    Записать лог сообщение через LoggerModule.
    
    Args:
        runtime: экземпляр CoreRuntime (если None - используется print как fallback)
        level: уровень логирования (debug, info, warning, error)
        message: сообщение
        **context: дополнительный контекст
    """
    # Нормализуем уровень
    level = (level or "info").lower()
    if level not in ("debug", "info", "warning", "error"):
        level = "info"
    
    # Если runtime доступен - используем LoggerModule через service_registry
    if runtime is not None:
        try:
            # LoggerModule всегда доступен (регистрируется первым)
            await runtime.service_registry.call(
                "logger.log",
                level=level,
                message=message,
                **context
            )
            return
        except STORAGE_BOUNDARY_ERRORS:
            _stdlog.debug(
                "log(): logger.log failed (storage boundary), using stderr fallback",
                exc_info=True,
            )
        except LOGGING_HELPER_ERRORS:
            _stdlog.debug(
                "log(): logger.log failed, using stderr fallback",
                exc_info=True,
            )
    
    # Fallback только для случаев до инициализации runtime
    log_message = f"[{level.upper()}] {message}"
    if context:
        log_message += f" {context}"
    print(log_message, file=sys.stderr)


async def debug(runtime: Optional[Any], message: str, **context: Any) -> None:
    """Логировать debug сообщение."""
    await log(runtime, "debug", message, **context)


async def info(runtime: Optional[Any], message: str, **context: Any) -> None:
    """Логировать info сообщение."""
    await log(runtime, "info", message, **context)


async def warning(runtime: Optional[Any], message: str, **context: Any) -> None:
    """Логировать warning сообщение."""
    await log(runtime, "warning", message, **context)


async def error(runtime: Optional[Any], message: str, **context: Any) -> None:
    """Логировать error сообщение."""
    await log(runtime, "error", message, **context)
