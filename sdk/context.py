"""
PluginRuntime — контракт среды выполнения плагина (Protocol).

Только typing/Protocol. Никакой реализации.
Плагин получает opaque объект, удовлетворяющий этому контракту.
"""

from typing import Any, Protocol


class PluginRuntime(Protocol):
    """
    Контракт runtime, передаваемого плагину.
    Core предоставляет объект, совместимый с этим протоколом.
    """

    service_registry: Any
    event_bus: Any
    storage: Any
    state: Any
    operations: Any
