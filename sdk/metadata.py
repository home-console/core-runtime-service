"""
PluginMetadata — публичный контракт метаданных плагина.

Frozen dataclass. Никакой логики. Core читает поля, но не интерпретирует смысл.
"""

from __future__ import annotations

from typing import Optional
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PluginMetadata:
    """Метаданные плагина. Все поля объявляются плагином."""

    name: str
    version: str
    description: str | None = None

    is_integration: bool = False
    integration_flags: list[str] = field(default_factory=list)

    capabilities_provided: list[str] = field(default_factory=list)
    capabilities_required: list[str] = field(default_factory=list)

    # Set True for trusted proxy plugins that register services dynamically
    # (e.g. remote_plugin_proxy). Bypasses namespace enforcement in ServiceRegistryProxy.
    dynamic_service_registration: bool = False
