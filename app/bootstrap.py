from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from app.orchestration import DockerOrchestrationBackend, NullOrchestrationBackend, OrchestrationService
from app.runtime_monitoring import collect_runtime_health, collect_runtime_metrics
from core.runtime.config import Config
from core.module import ModuleSpec
from core.runtime import CoreRuntime
from modules.capability.security import (
    check_capability_namespace_permission as check_module_capability_namespace_permission,
    trust_level_to_privilege as module_trust_level_to_privilege,
)
from modules.policy.engine import PolicyEngine as ModulePolicyEngine
from modules.policy.service_policy import (
    build_service_acl_wrapper as build_module_service_acl_wrapper,
    create_default_policy_engine as create_module_service_policy_engine,
)
from modules.events.validation import EventValidationMiddleware
from modules.plugins.isolation import (
    DEFAULT_ALLOWED_SERVICES,
    ServiceProxy,
    StorageProxy,
)


APP_MODULES: list[ModuleSpec] = [
    ModuleSpec("logger", required=True),
    ModuleSpec("request_logger", required=True),
    ModuleSpec("retry_policy", required=True),
    ModuleSpec("idempotency", required=True),
    ModuleSpec("api", required=True),
    ModuleSpec("admin", required=True),
    ModuleSpec("auth", required=True),
    ModuleSpec("operations", required=True),
    ModuleSpec("marketplace", required=False, dependencies=["operations"]),
    ModuleSpec("agent", required=False),
    ModuleSpec("credentials", required=False),
    ModuleSpec("execution", required=True, dependencies=["operations"]),
    ModuleSpec("integrations", required=True),
    ModuleSpec("devices", required=True),
    ModuleSpec("automation", required=False),
    ModuleSpec("presence", required=True),
    ModuleSpec("product_api", required=False),
]

DEFAULT_CRITICAL_STATE_PREFIXES: list[str] = [
    "plugins.",
    "agent.",
    "ca.",
    "runtime.snapshots",
]


def parse_module_specs(config: Config) -> list[ModuleSpec]:
    raw = getattr(config, "modules_config", None)
    if not raw:
        return APP_MODULES

    specs: list[ModuleSpec] = []
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        if ":" in token:
            name, _, required_raw = token.partition(":")
            required = required_raw.strip().lower() not in (
                "false",
                "0",
                "no",
                "optional",
            )
            specs.append(ModuleSpec(name.strip(), required=required))
        else:
            specs.append(ModuleSpec(token, required=True))
    return specs or APP_MODULES


async def build_runtime(
    *,
    storage_port: Any,
    config: Config,
    vault_port: Optional[Any] = None,
    state_engine: Optional[Any] = None,
    storage_manager: Optional[Any] = None,
    module_specs: Optional[list[ModuleSpec]] = None,
) -> CoreRuntime:
    # Orchestration service создаётся в app-layer (не в ядре)
    backend_name = getattr(config, "orchestration_backend", "docker")
    if backend_name == "none":
        orchestration_service = OrchestrationService(NullOrchestrationBackend())
    else:
        orchestration_service = OrchestrationService(DockerOrchestrationBackend())

    runtime = CoreRuntime(
        storage_port=storage_port,
        config=config,
        vault_port=vault_port,
        state_engine=state_engine,
        policy_engine=ModulePolicyEngine(),
        service_policy_engine_factory=create_module_service_policy_engine,
        service_acl_wrapper_builder=build_module_service_acl_wrapper,
        capability_namespace_permission_checker=check_module_capability_namespace_permission,
        trust_level_to_privilege_mapper=module_trust_level_to_privilege,
        orchestration_service=orchestration_service,
    )
    # App-level policy: какие namespaces гидратировать при старте.
    async def _state_hydration_namespaces() -> list[str]:
        all_namespaces = await runtime.storage.list_namespaces()
        return [
            ns
            for ns in all_namespaces
            if any(ns.startswith(prefix) for prefix in DEFAULT_CRITICAL_STATE_PREFIXES)
        ]

    runtime.set_state_hydration_callback(_state_hydration_namespaces)
    runtime.storage_manager = storage_manager
    runtime.event_validation_middleware_factory = EventValidationMiddleware
    runtime.plugin_storage_proxy_cls = StorageProxy
    runtime.plugin_service_proxy_cls = ServiceProxy
    runtime.plugin_default_allowed_services = list(DEFAULT_ALLOWED_SERVICES)
    runtime.monitor.health_check_delegate = collect_runtime_health
    runtime.monitor.metrics_collector_delegate = collect_runtime_metrics

    specs = module_specs or parse_module_specs(config)
    await runtime.module_manager.register_module_specs(runtime, specs)
    return runtime


async def auto_load_plugins_if_enabled(runtime: CoreRuntime, config: Config) -> None:
    """
    App-level policy for plugin auto-discovery.

    Core runtime does not decide plugin discovery strategy.
    """
    should_auto_load_plugins = bool(
        getattr(config, "auto_load_plugins", config is not None)
    )
    if not should_auto_load_plugins:
        return
    if os.getenv("TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"):
        return

    loaded_plugins = await runtime.plugin_manager.list_plugins()
    if loaded_plugins:
        return

    plugins_dir_str = getattr(config, "plugins_dir", None)
    plugins_dir = Path(plugins_dir_str).expanduser() if plugins_dir_str else None
    await runtime.plugin_manager.auto_load_plugins(plugins_dir=plugins_dir)


def resolve_module_specs_for_profile(
    profile_name: str | None,
    config: Config,
) -> list[ModuleSpec]:
    """
    Определить список модулей с учётом профиля и RUNTIME_MODULES ENV.

    Приоритет (от высшего к низшему):
    1. RUNTIME_MODULES в ENV — если задан, всегда используется как есть
    2. RUNTIME_PROFILE — если задан, берёт модули из профиля
    3. APP_MODULES — дефолт

    Returns:
        Отсортированный список ModuleSpec (ModuleDependencySorter уже применён)
    """
    # Local import to avoid app.bootstrap <-> app.profiles cycle at import time.
    from app.profiles import resolve_module_specs_for_profile as _resolve

    return _resolve(profile_name, config)
