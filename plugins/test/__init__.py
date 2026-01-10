"""
Тестовые плагины и stub-реализации.

Эти плагины используются для тестирования, демонстрации и разработки,
но не предназначены для production использования.
"""

from .automation_stub_plugin import AutomationStubPlugin
from .example_plugin import ExamplePlugin
from .system_logger_plugin import SystemLoggerPlugin
from .yandex_smart_home_stub import YandexSmartHomeStubPlugin

__all__ = [
    "AutomationStubPlugin",
    "ExamplePlugin",
    "SystemLoggerPlugin",
    "YandexSmartHomeStubPlugin",
]
