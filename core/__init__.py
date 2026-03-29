"""
Core Runtime - минимальное ядро для plugin-first платформы умного дома.
"""

from core.integration_registry import IntegrationRegistry
from core.messaging.inmemory import InMemoryEventBus as EventBus
from core.module.manager import ModuleManager
from core.runtime.runtime import CoreRuntime
from core.service.registry import ServiceRegistry

from .config import Config
from .logger_helper import error, info, warning
from .runtime_module import RuntimeModule
from .state_engine import StateEngine

__all__ = [
    "Config",
    "CoreRuntime",
    "EventBus",
    "ServiceRegistry",
    "StateEngine",
    "IntegrationRegistry",
    "info",
    "warning",
    "error",
    "ModuleManager",
    "RuntimeModule",
]
