"""
Core Runtime - минимальное ядро для plugin-first платформы умного дома.
"""

from .config import Config
from .console import run_cli
from core.messaging.event_bus import EventBus
from .http_registry import HttpRegistry
from core.runtime.module_manager import ModuleManager
from core.runtime.runtime import CoreRuntime
from .runtime_module import RuntimeModule
from .service_registry import ServiceRegistry
from .state_engine import StateEngine
from .storage import Storage
from .storage_mirror import StorageWithStateMirror
from .storage_port import StorageStack
from .integration_registry import IntegrationRegistry
from .logger_helper import info, warning, error
from core.kernel.base_plugin import BasePlugin

__all__ = [
    "Config",
    "CoreRuntime",
    "EventBus",
    "ServiceRegistry",
    "StateEngine",
    "Storage",
    "StorageWithStateMirror",
    "StorageStack",
    "IntegrationRegistry",
    "info",
    "warning",
    "error",
    "HttpRegistry",
    "ModuleManager",
    "RuntimeModule",
]
