"""Inspector DTO schemas — admin introspection API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .devices import DeviceDto, DeviceMappingDto


class RuntimeInfoDto(BaseModel):
    version: Optional[str] = None
    started_at: Optional[str] = None
    uptime: Optional[float] = None
    error: Optional[str] = None


class DashboardSummaryDto(BaseModel):
    plugins: int = 0
    services: int = 0
    http_endpoints: int = 0
    state_keys: int = 0
    executions: Optional[int] = None
    schedules: Optional[int] = None
    devices: Optional[int] = None


class ServiceDto(BaseModel):
    service_name: str
    plugin_name: str


class HttpEndpointInfoDto(BaseModel):
    method: str
    path: str
    service: str
    description: Optional[str] = None
    plugin: Optional[str] = None


class WsEndpointInfoDto(BaseModel):
    path: str
    service: str
    description: Optional[str] = None


class RuntimeEventSubscriberDto(BaseModel):
    plugin: str
    handler: str


class RuntimeEventDto(BaseModel):
    event_name: str
    subscribers: List[RuntimeEventSubscriberDto] = []


class IntegrationFlowActionDto(BaseModel):
    type: str
    params: Optional[Dict[str, Any]] = None
    label: Optional[str] = None


class IntegrationFlowDto(BaseModel):
    id: str
    provider: Optional[str] = None
    state: str
    message: Optional[str] = None
    actions: List[IntegrationFlowActionDto] = []
    qr_url: Optional[str] = None
    qr_svg: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class InventorySnapshotDto(BaseModel):
    items: List[DeviceDto] = []
    mappings: List[DeviceMappingDto] = []
    external: Optional[Dict[str, List[Any]]] = None


class SystemHealthDto(BaseModel):
    status: str
    uptime: Optional[float] = None
    memory_mb: Optional[float] = None
    cpu_percent: Optional[float] = None
    storage_ok: Optional[bool] = None
    details: Optional[Dict[str, Any]] = None


class OperationTypeDto(BaseModel):
    type: str
    description: Optional[str] = None
