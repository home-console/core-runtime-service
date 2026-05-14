"""SSH/terminal DTO schemas."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SshSessionDto(BaseModel):
    session_id: str
    credential_id: Optional[str] = None
    host: str
    username: str
    created_at: float
    age_sec: float
    alive: bool
    subscribers: int = 0
    error: Optional[str] = None


# --- Request models ---


class CreateSshSessionRequest(BaseModel):
    """Create SSH PTY session — either by credential_id or by direct connection params."""

    credential_id: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    private_key: Optional[str] = None
