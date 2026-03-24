"""IntegrationRegistry — in-memory catalog of integrations."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set


class IntegrationFlag(Enum):
    """Integration flags from plugin manifests."""

    REQUIRES_OAUTH = "requires_oauth"
    REQUIRES_CONFIG = "requires_config"
    BETA = "beta"
    EXPERIMENTAL = "experimental"


@dataclass
class IntegrationInfo:
    """Integration metadata entry."""

    id: str
    name: str
    plugin_name: str
    flags: Set[IntegrationFlag]
    description: str = ""
    type: str = "integration"


class IntegrationRegistry:
    """In-memory integration registry for admin/API discovery."""

    def __init__(self) -> None:
        self._integrations: Dict[str, IntegrationInfo] = {}

    def register(
        self,
        integration_id: str,
        name: str,
        plugin_name: str,
        flags: Optional[Set[IntegrationFlag]] = None,
        description: str = "",
        integration_type: Optional[str] = None,
    ) -> None:
        if flags is None:
            flags = set()
        type_val = (integration_type or "integration").strip() or "integration"
        self._integrations[integration_id] = IntegrationInfo(
            id=integration_id,
            name=name,
            plugin_name=plugin_name,
            flags=flags,
            description=description,
            type=type_val,
        )

    def unregister(self, integration_id: str) -> None:
        self._integrations.pop(integration_id, None)

    def get(self, integration_id: str) -> Optional[IntegrationInfo]:
        return self._integrations.get(integration_id)

    def list(self) -> List[IntegrationInfo]:
        return list(self._integrations.values())

    def list_by_plugin(self, plugin_name: str) -> List[IntegrationInfo]:
        return [
            info
            for info in self._integrations.values()
            if info.plugin_name == plugin_name
        ]

    def clear(self) -> None:
        self._integrations.clear()

    def has_integration(self, integration_id: str) -> bool:
        return integration_id in self._integrations
