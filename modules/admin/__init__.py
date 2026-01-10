"""
Admin Module — встроенный модуль административных endpoints.

Обязательный модуль системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from .module import AdminModule

__all__ = ["AdminModule"]
