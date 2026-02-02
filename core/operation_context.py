"""
Operation context — точка расширения для observability/correlation (operation_id).

Core не реализует хранение operation_id и не импортирует modules.
Модуль request_logger (или другой) регистрирует провайдер при старте;
Core только вызывает провайдер, если он установлен.
Если провайдер не установлен — get_operation_id() возвращает None, set_operation_id() не делает ничего.
"""

from typing import Optional, Protocol


class OperationContextProvider(Protocol):
    """Минимальный интерфейс для получения/установки operation_id в текущем контексте."""

    def get_operation_id(self) -> Optional[str]: ...
    def set_operation_id(self, value: str) -> None: ...


_provider: Optional[OperationContextProvider] = None


def set_operation_context_provider(provider: Optional[OperationContextProvider]) -> None:
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
