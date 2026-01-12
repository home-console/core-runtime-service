"""
Core Runtime - минимальное ядро для plugin-first платформы умного дома.
"""

from .config import Config
from .console import run_cli
from .event_bus import EventBus
from .http_registry import HttpRegistry
from .module_manager import ModuleManager
from .plugin_manager import PluginManager
from .runtime import CoreRuntime
from .runtime_module import RuntimeModule
from .service_registry import ServiceRegistry
from .storage_factory import create_storage_adapter
from .state_engine import StateEngine
from .storage import Storage
from .storage_mirror import StorageWithStateMirror
from .integration_registry import IntegrationRegistry
from .logger_helper import info, warning, error
from .base_plugin import BasePlugin

__all__ = [
    "Config",
    "CoreRuntime",
    "EventBus",
    "ServiceRegistry",
    "StateEngine",
    "Storage",
    "StorageWithStateMirror",
    "IntegrationRegistry",
    "info",
    "warning",
    "error",
    "PluginManager",
    "HttpRegistry",
    "ModuleManager",
    "PluginManager",
    "RuntimeModule",
    "create_storage_adapter",
]
