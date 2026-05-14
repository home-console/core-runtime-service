"""Auth DTO schemas — identity & session contracts."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class UserDto(BaseModel):
    user_id: str
    username: Optional[str] = None
    scopes: List[str] = []
    is_admin: bool = False
    created_at: Optional[float] = None
    source: Optional[str] = None
    needs_initialization: Optional[bool] = None


class SessionDto(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[float] = None
    expires_at: Optional[float] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None


class ApiKeyDto(BaseModel):
    key_id: str
    name: Optional[str] = None
    created_at: Optional[float] = None
    last_used_at: Optional[float] = None
    scopes: List[str] = []


class AuthTokenDto(BaseModel):
    ok: bool = True
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    token_type: Optional[str] = None
    error: Optional[str] = None


class BootstrapStatusDto(BaseModel):
    initialized: bool
    needs_initialization: Optional[bool] = None


class DevCredentialsDto(BaseModel):
    api_base_url: str
    api_key: Optional[str] = None


# --- Request models ---


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=1)
    password: str = Field(min_length=1)
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None


class InitializeRequest(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None
    password: str = Field(min_length=1)


class SetPasswordRequest(BaseModel):
    user_id: str
    new_password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class RevokeSessionRequest(BaseModel):
    session_id: str


class RevokeApiKeyRequest(BaseModel):
    key_id: str


class RotateApiKeyRequest(BaseModel):
    key_id: str


class CreateApiKeyRequest(BaseModel):
    name: Optional[str] = None
    scopes: Optional[List[str]] = None


class CreateUserRequest(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None
    password: str = Field(min_length=1)
    scopes: Optional[List[str]] = None
