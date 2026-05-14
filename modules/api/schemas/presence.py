"""Presence DTO schemas."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PresenceStatusDto(BaseModel):
    ok: bool = True
    home: Optional[bool] = None
