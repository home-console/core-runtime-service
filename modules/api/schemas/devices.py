"""Device DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class DeviceStateDto(BaseModel):
    desired: Optional[Dict[str, Any]] = None
    reported: Optional[Dict[str, Any]] = None
    pending: Optional[bool] = None


class DeviceDto(BaseModel):
    id: str
    name: Optional[str] = None
    type: str
    state: DeviceStateDto
    online: Optional[bool] = None
    last_seen: Optional[float] = None
    updated_at: Optional[float] = None
    created_at: Optional[float] = None
    owner_id: Optional[str] = None
    shared_with: Optional[List[str]] = None
    home_id: Optional[str] = None
    room_id: Optional[str] = None
    location: Optional[str] = None
    icon_url: Optional[str] = None


class ExternalDeviceDto(BaseModel):
    external_id: str
    payload: Optional[Dict[str, Any]] = None


class DeviceMappingDto(BaseModel):
    external_id: str
    internal_id: str


# --- Request models ---


class SetDeviceStateRequest(BaseModel):
    state: Optional[Dict[str, Any]] = None
    on: Optional[bool] = None
    power: Optional[str] = None
