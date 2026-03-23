from __future__ import annotations

from typing import Any, Optional

from core.config import Config
from core.runtime import CoreRuntime
from core.runtime.module_manager import ModuleSpec
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
    ModuleSpec("agent", required=False),
    ModuleSpec("credentials", required=False),
    ModuleSpec("execution", required=True),
    ModuleSpec("integrations", required=True),
    ModuleSpec("devices", required=True),
    ModuleSpec("automation", required=False),
    ModuleSpec("presence", required=True),
    ModuleSpec("product_api", required=False),
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
    runtime = CoreRuntime(
        storage_port=storage_port,
        config=config,
        vault_port=vault_port,
        state_engine=state_engine,
    )
    runtime.storage_manager = storage_manager
    runtime.event_validation_middleware_factory = EventValidationMiddleware
    runtime.plugin_storage_proxy_cls = StorageProxy
    runtime.plugin_service_proxy_cls = ServiceProxy
    runtime.plugin_default_allowed_services = list(DEFAULT_ALLOWED_SERVICES)

    specs = module_specs or parse_module_specs(config)
    await runtime.module_manager.register_module_specs(runtime, specs)
    return runtime
