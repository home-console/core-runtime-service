"""
API Module — встроенный модуль HTTP API Gateway.

Обязательный модуль системы, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from .module import ApiModule

__all__ = ["ApiModule"]
