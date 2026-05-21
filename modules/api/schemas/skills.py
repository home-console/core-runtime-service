"""Skills DTO schemas (platform skill registry, not agent control plane)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SkillDto(BaseModel):
    id: str
    plugin_name: str
    name: str
    intent: str
    description: Optional[str] = None
    plugin_version: str
    service: Optional[str] = None


class SkillListDto(BaseModel):
    items: List[SkillDto]
    total: int


class SkillInvokeRequest(BaseModel):
    params: Dict[str, Any] = {}


class SkillInvokeResult(BaseModel):
    ok: bool
    skill_id: str
    service: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    code: Optional[str] = None
