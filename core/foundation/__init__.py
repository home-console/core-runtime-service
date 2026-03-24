"""
Foundation package - основные компоненты Core Runtime (Step 1-3).

Инфраструктурные модули для runtime, регистрации, конфигурации и управления модулями.
"""

# Step 1-3: Core Infrastructure
from modules.capability.registry import CapabilityRegistry
from core.config import Config

# Foundation utilities
from core.dependency import DependencyResolver
from core.http import HttpRegistry
from core.interfaces import IOperationExecutor, IRemoteExecutor

# from core.capability_protocol import CapabilityProtocol
from core.module import ModuleManager

# from core.event_bus import EventBus
from modules.policy.engine import PolicyEngine
from core.runtime import CoreRuntime
from core.runtime_interface import IPluginLifecycle, IPluginRegistry, IRuntimeModule
from core.runtime_module import RuntimeModule
from core.service import ServiceRegistry
from core.state_engine import StateEngine

__all__ = [
    "CoreRuntime",
    "IRuntimeModule",
    "IPluginRegistry",
    "IPluginLifecycle",
    "RuntimeModule",
    "ServiceRegistry",
    "HttpRegistry",
    "CapabilityRegistry",
    # "CapabilityProtocol",
    "ModuleManager",
    "DependencyResolver",
    # "EventBus",
    "PolicyEngine",
    "StateEngine",
    "Config",
    "IOperationExecutor",
    "IRemoteExecutor",
]
