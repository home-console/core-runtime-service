"""Core/Interfaces - Контракты для основных компонентов

Централизованное место для всех публичных интерфейсов ядра.
"""

# Operation execution
from core.operations.interface import IOperationExecutor
from core.remote_executor_interface import IRemoteExecutor

# Runtime API
from core.runtime_interface import IRuntimeModule, IPluginRegistry, IPluginLifecycle

# Storage
from core.storage_interface import IStorageAdapter, IStorageManager

__all__ = [
    "IOperationExecutor",
    "IRemoteExecutor",
    "IRuntimeModule",
    "IPluginRegistry",
    "IPluginLifecycle",
    "IStorageAdapter",
    "IStorageManager",
]
