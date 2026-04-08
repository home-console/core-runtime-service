"""
Result type — единый контракт для обработки ошибок.

Вместо смешения:
- Исключения (Exception)
- Dict {"ok": False, "error": "..."}
- Строки ("error: message")

Используем типизированный Result:
- Ok(value) — успех
- Err(error_code, message, details) — ошибка

Это устраняет проблему D3:
- D3: Mixed error model (исключения + dict + строки)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar('T')


@dataclass(frozen=True)
class Error:
    """
    Типизированная ошибка.

    Атрибуты:
        code: машинный код ошибки (например, "missing_dependency")
        message: человекочитаемое сообщение
        details: дополнительные детали (опционально)
        component: компонент где произошла ошибка (опционально)
    """
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    component: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразовать в словарь для сериализации.

        Returns:
            Словарь с данными ошибки
        """
        result = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        if self.component:
            result["component"] = self.component
        return result

    def __str__(self) -> str:
        """Человекочитаемое представление."""
        if self.component:
            return f"[{self.component}] {self.code}: {self.message}"
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class Ok(Generic[T]):
    """
    Успешный результат.

    Атрибуты:
        value: значение результата
    """
    value: T

    def is_ok(self) -> bool:
        """Проверить что результат успешный."""
        return True

    def is_err(self) -> bool:
        """Проверить что результат с ошибкой."""
        return False

    def map(self, func) -> "Ok[Any]":
        """
        Применить функцию к значению.

        Args:
            func: функция для преобразования значения

        Returns:
            Новый Ok с преобразованным значением
        """
        return Ok(func(self.value))


@dataclass(frozen=True)
class Err:
    """
    Результат с ошибкой.

    Атрибуты:
        error: ошибка
    """
    error: Error

    def is_ok(self) -> bool:
        """Проверить что результат успешный."""
        return False

    def is_err(self) -> bool:
        """Проверить что результат с ошибкой."""
        return True

    def map(self, func) -> "Err":
        """
        Применить функцию к значению (no-op для Err).

        Args:
            func: функция (игнорируется)

        Returns:
            Тот же Err
        """
        return self


# Type alias для Result
Result = Ok[T] | Err


def ok(value: T) -> Ok[T]:
    """
    Создать успешный результат.

    Args:
        value: значение

    Returns:
        Ok с значением
    """
    return Ok(value)


def err(code: str, message: str, details: Optional[Dict[str, Any]] = None, component: Optional[str] = None) -> Err:
    """
    Создать результат с ошибкой.

    Args:
        code: код ошибки
        message: сообщение
        details: детали (опционально)
        component: компонент (опционально)

    Returns:
        Err с ошибкой
    """
    return Err(Error(code, message, details or {}, component))


def from_exception(exc: Exception, default_code: str = "unexpected_error", component: Optional[str] = None) -> Err:
    """
    Создать Err из исключения.

    Args:
        exc: исключение
        default_code: код ошибки по умолчанию
        component: компонент (опционально)

    Returns:
        Err с ошибкой из исключения
    """
    # Если исключение уже содержит Error, используем его
    if isinstance(exc, Error):
        return Err(exc)

    # Иначе создаём из исключения
    return err(
        code=default_code,
        message=str(exc),
        component=component,
    )


def collect_errors(results: List[Result[Any]]) -> List[Error]:
    """
    Собрать ошибки из списка результатов.

    Args:
        results: список результатов

    Returns:
        Список ошибок
    """
    errors = []
    for result in results:
        if isinstance(result, Err):
            errors.append(result.error)
    return errors


def first_error(results: List[Result[Any]]) -> Optional[Error]:
    """
    Получить первую ошибку из списка результатов.

    Args:
        results: список результатов

    Returns:
        Первая ошибка или None
    """
    for result in results:
        if isinstance(result, Err):
            return result.error
    return None


def all_ok(results: List[Result[Any]]) -> bool:
    """
    Проверить что все результаты успешные.

    Args:
        results: список результатов

    Returns:
        True если все Ok
    """
    return all(isinstance(r, Ok) for r in results)
