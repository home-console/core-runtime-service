from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from core.runtime.runtime_context import RuntimeContext


@dataclass(frozen=True)
class PluginRuntimeFacade:
    """
    Минимальный совместимый facade вместо полного CoreRuntime.

    SECURITY: не содержит plugin_manager/module_manager/orchestration и т.п.
    """

    # Common surfaces used by existing plugins
    storage: Any
    service_registry: Any
    http: Any
    operations: Any
    state: Any
    event_bus: Any
    capabilities: Any
    vault: Optional[Any] = None
    config: Optional[Any] = None
    agent_manager: Optional[Any] = None
    agent_registry: Optional[Any] = None

    def create_context(self) -> RuntimeContext:
        return RuntimeContext(
            storage=self.storage,
            vault=self.vault,
            services=self.service_registry,
            http=self.http,
            capabilities=self.capabilities,
            operations=self.operations,
            state=self.state,
        )
