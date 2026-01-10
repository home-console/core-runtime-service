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
LoggerModule всегда доступен (регистрируется первым в BUILTIN_MODULES),
поэтому fallback'и минимальны - только для случаев до инициализации runtime.

Реальная логика логирования находится в modules/logger/module.py.
"""

import sys
from typing import Optional, Any


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
        except Exception:
            # Если service_registry недоступен - fallback на print
            pass
    
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
