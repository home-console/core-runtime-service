"""Integration DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

class IntegrationDto(BaseModel):
    id: str
    provider: str
    status: str
    connected_at: Optional[str] = None
    disconnected_at: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
