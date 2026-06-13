"""Inspector DTO schemas — admin introspection API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .devices import DeviceDto


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
    mounted_path: Optional[str] = None
    service: str
    plugin: Optional[str] = None
    description: Optional[str] = None
    websocket: bool = False
    tags: List[str] = []


class WsEndpointInfoDto(BaseModel):
    path: str
    mounted_path: Optional[str] = None
    service: str
    description: Optional[str] = None
    tags: List[str] = []


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
    state: str
    provider: Optional[str] = None
    name: Optional[str] = None
    plugin_name: Optional[str] = None
    integration_type: Optional[str] = None
    message: Optional[str] = None
    actions: List[IntegrationFlowActionDto] = []
    qr_url: Optional[str] = None
    qr_svg: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class InventorySnapshotDto(BaseModel):
    items: List[DeviceDto] = []


class SystemHealthDto(BaseModel):
    status: str
    details: Optional[Dict[str, Any]] = None


class OperationTypeDto(BaseModel):
    type: str
    description: Optional[str] = None
