"""Plugin DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PluginDto(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    loaded: bool
    started: bool
    error: Optional[str] = None
    services_count: int = 0
    http_count: int = 0
    event_subscriptions: List[str] = []
    execution_mode: Optional[str] = None
    capabilities_provided: List[str] = []
    capabilities_required: List[str] = []
    unresolved_capabilities: List[str] = []


class PluginDetailsDto(PluginDto):
    manifest: Optional[Dict[str, Any]] = None
    on_disk: Optional[bool] = None
    dependencies: Optional[List[str]] = None
    class_path: Optional[str] = None


class PluginsDiscoverDto(BaseModel):
    plugins_dir: str
    manifests: Dict[str, Dict[str, Any]] = {}
    load_order: List[str] = []
    loaded: List[str] = []


# --- Request models ---


class LoadPluginRequest(BaseModel):
    name: Optional[str] = None
    plugins_dir: Optional[str] = None


class EnsureContainerRequest(BaseModel):
    container_name: Optional[str] = None


class AutoLoadRequest(BaseModel):
    plugins_dir: Optional[str] = None
