"""
Core Runtime - минимальное ядро для plugin-first платформы умного дома.
"""

from .config import Config
from core.messaging.event_bus import EventBus
# from .http_registry import HttpRegistry
from core.runtime.module_manager import ModuleManager
from core.runtime.runtime import CoreRuntime
from .runtime_module import RuntimeModule
from .service import ServiceRegistry
from .state_engine import StateEngine
from modules.integrations.registry import IntegrationRegistry
from .logger_helper import info, warning, error
from core.kernel.base_plugin import BasePlugin

# Interfaces
from .interfaces import (
    IOperationExecutor,
    IRemoteExecutor,
    IRuntimeModule,
    IPluginRegistry,
    IPluginLifecycle,
    IStorageAdapter,
    IStorageManager,
)

# Exceptions
from .exceptions import (
    CoreError,
    BadRequestError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
    StorageSecurityError,
    StorageConfigurationError,
    NamespaceViolationError,
)

# Contexts
from .contexts import (
    RuntimeContext,
    SystemContext,
    create_system_context,
    get_operation_id,
    set_operation_id,
)

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
