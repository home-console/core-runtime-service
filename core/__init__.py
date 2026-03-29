"""
Core Runtime - минимальное ядро для plugin-first платформы умного дома.

Импорты здесь намеренно ленивые, чтобы не создавать циклы при загрузке
подмодулей вроде core.runtime.runtime_context и core.module.
"""

from importlib import import_module


def __getattr__(name: str):
    if name == "Config":
        return import_module("core.runtime.config").Config
    if name == "CoreRuntime":
        return import_module("core.runtime.runtime").CoreRuntime
    if name == "EventBus":
        return import_module("core.messaging").InMemoryEventBus
    if name == "ServiceRegistry":
        return import_module("core.service.registry").ServiceRegistry
    if name == "StateEngine":
        return import_module("core.runtime.state_engine").StateEngine
    if name == "IntegrationRegistry":
        return import_module("core.kernel.integration_registry").IntegrationRegistry
    if name == "ModuleManager":
        return import_module("core.module").ModuleManager
    if name == "RuntimeModule":
        return import_module("core.runtime.runtime_module").RuntimeModule
    if name in {"info", "warning", "error"}:
        logger_module = import_module("core.observability.logger_helper")
        return getattr(logger_module, name)
    raise AttributeError(f"module 'core' has no attribute {name!r}")
