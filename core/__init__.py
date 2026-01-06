"""
Core Runtime - минимальное ядро для plugin-first платформы умного дома.
"""

from .runtime import CoreRuntime
from .event_bus import EventBus
from .service_registry import ServiceRegistry
from .state_engine import StateEngine
from .storage import Storage
from .plugin_manager import PluginManager

__all__ = [
    "CoreRuntime",
    "EventBus",
    "ServiceRegistry",
    "StateEngine",
    "Storage",
    "PluginManager",
]
