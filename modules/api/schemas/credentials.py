"""Credential DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CredentialDto(BaseModel):
    id: str
    type: str
    name: str
    secret_ref: str
    username: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    metadata: Dict[str, Any] = {}
    tags: List[str] = []
    version: int = 1
    created_at: str
    updated_at: str
    fingerprint: str


class TerminalSessionStartDto(BaseModel):
    ok: bool = True
    session_id: Optional[str] = None
    error: Optional[str] = None


# --- Request models ---


class CreateCredentialRequest(BaseModel):
    credential: Dict[str, Any]
    secret: str


class UpdateCredentialRequest(BaseModel):
    credential: Dict[str, Any]
    secret: Optional[str] = None
