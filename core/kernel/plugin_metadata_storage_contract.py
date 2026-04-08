from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


PLUGIN_METADATA_NAMESPACE = "plugins.metadata"
PLUGIN_METADATA_SCHEMA_VERSION = 1


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x)]
    if isinstance(value, tuple):
        return [str(x) for x in value if str(x)]
    return []


@dataclass(frozen=True)
class PluginMetadataRecord:
    schema_version: int
    name: str
    version: str
    class_path: str
    execution_mode: str
    container_config: Any | None
    capabilities_provided: list[str]
    capabilities_required: list[str]
    dependencies: list[str]
    loaded: bool
    loaded_at: float | None
    unloaded_at: float | None

    @classmethod
    def from_metadata(cls, plugin_name: str, metadata: Any, *, now: float) -> "PluginMetadataRecord":
        return cls(
            schema_version=PLUGIN_METADATA_SCHEMA_VERSION,
            name=str(getattr(metadata, "name", plugin_name) or plugin_name),
            version=str(getattr(metadata, "version", "0.0.0") or "0.0.0"),
            class_path=str(getattr(metadata, "class_path", "") or ""),
            execution_mode=str(getattr(metadata, "execution_mode", "in_process") or "in_process"),
            container_config=getattr(metadata, "container_config", None),
            capabilities_provided=_as_str_list(getattr(metadata, "capabilities_provided", None)),
            capabilities_required=_as_str_list(getattr(metadata, "capabilities_required", None)),
            dependencies=_as_str_list(getattr(metadata, "dependencies", None)),
            loaded=True,
            loaded_at=float(now),
            unloaded_at=None,
        )

    @classmethod
    def from_storage_dict(cls, plugin_name: str, value: dict[str, Any]) -> "PluginMetadataRecord":
        schema_version_raw = value.get("schema_version", 0)
        try:
            schema_version = int(schema_version_raw)
        except (TypeError, ValueError):
            schema_version = 0

        # v0: legacy dict without schema_version.
        if schema_version <= 0:
            schema_version = PLUGIN_METADATA_SCHEMA_VERSION

        loaded_at = value.get("loaded_at")
        unloaded_at = value.get("unloaded_at")
        try:
            loaded_at_f = float(loaded_at) if loaded_at is not None else None
        except (TypeError, ValueError):
            loaded_at_f = None
        try:
            unloaded_at_f = float(unloaded_at) if unloaded_at is not None else None
        except (TypeError, ValueError):
            unloaded_at_f = None

        return cls(
            schema_version=schema_version,
            name=str(value.get("name") or plugin_name),
            version=str(value.get("version") or "0.0.0"),
            class_path=str(value.get("class_path") or ""),
            execution_mode=str(value.get("execution_mode") or "in_process"),
            container_config=value.get("container_config"),
            capabilities_provided=_as_str_list(value.get("capabilities_provided")),
            capabilities_required=_as_str_list(value.get("capabilities_required")),
            dependencies=_as_str_list(value.get("dependencies")),
            loaded=bool(value.get("loaded", False)),
            loaded_at=loaded_at_f,
            unloaded_at=unloaded_at_f,
        )

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "name": self.name,
            "version": self.version,
            "class_path": self.class_path,
            "execution_mode": self.execution_mode,
            "container_config": self.container_config,
            "capabilities_provided": list(self.capabilities_provided),
            "capabilities_required": list(self.capabilities_required),
            "dependencies": list(self.dependencies),
            "loaded": bool(self.loaded),
            "loaded_at": self.loaded_at,
            "unloaded_at": self.unloaded_at,
        }

