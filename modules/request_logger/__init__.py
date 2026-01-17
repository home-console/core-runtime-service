"""
Request Logger Module - модуль для хранения полных логов каждого запроса.

Хранит логи всех HTTP запросов и вызовов сервисов с привязкой к request_id.
"""

from .module import RequestLoggerModule

__all__ = ["RequestLoggerModule"]
