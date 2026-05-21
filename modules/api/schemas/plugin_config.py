"""Plugin UI config and scoped service invoke (server-driven UI)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PluginConfigDto(BaseModel):
    plugin_name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class SetPluginConfigRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


class PluginServiceInvokeRequest(BaseModel):
    service: str
    kwargs: Dict[str, Any] = Field(default_factory=dict)


class PluginServiceInvokeResult(BaseModel):
    ok: bool
    plugin_name: str
    service: str
    result: Optional[Any] = None
    error: Optional[str] = None
    code: Optional[str] = None
