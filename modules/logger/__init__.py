"""
Logger Module - встроенный модуль логирования.

Обязательный инфраструктурный модуль, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.
"""

from .module import LoggerModule

__all__ = ["LoggerModule"]
