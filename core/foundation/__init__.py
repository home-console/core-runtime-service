"""
Foundation package - основные компоненты Core Runtime (Step 1-3).

Инфраструктурные модули для runtime, регистрации, конфигурации и управления модулями.
"""

# Step 1-3: Core Infrastructure
from core.runtime import CoreRuntime
from core.runtime_interface import IRuntimeModule, IPluginRegistry, IPluginLifecycle
from core.runtime_module import RuntimeModule
from core.service import ServiceRegistry
from core.http import HttpRegistry
from core.capability import CapabilityRegistry
from core.capability_protocol import CapabilityProtocol
from core.module import ModuleManager

# Foundation utilities
from core.dependency import DependencyResolver
from core.event_bus import EventBus
from core.policy import PolicyEngine
from core.state_engine import StateEngine
from core.config import Config
from core.interfaces import IOperationExecutor, IRemoteExecutor

__all__ = [
    "CoreRuntime",
    "IRuntimeModule",
    "IPluginRegistry",
    "IPluginLifecycle",
    "RuntimeModule",
    "ServiceRegistry",
    "HttpRegistry",
    "CapabilityRegistry",
    "CapabilityProtocol",
    "ModuleManager",
    "DependencyResolver",
    "EventBus",
    "PolicyEngine",
    "StateEngine",
    "Config",
    "IOperationExecutor",
    "IRemoteExecutor",
]
