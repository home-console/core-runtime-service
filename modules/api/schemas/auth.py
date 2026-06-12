"""Auth DTO schemas — identity & session contracts."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class UserDto(BaseModel):
    """Admin-side user DTO. Используется в /api/v1/admin/auth/users и
    смежных endpoint'ах, где нужна полная карточка пользователя со scopes/
    created_at. НЕ путать с :class:`AuthMeResponse` — у /auth/me другой
    контракт под frontend AuthUser interface."""

    user_id: str
    username: Optional[str] = None
    scopes: List[str] = []
    is_admin: bool = False
    created_at: Optional[float] = None
    source: Optional[str] = None
    needs_initialization: Optional[bool] = None


class AuthMeResponse(BaseModel):
    """Контракт GET /api/v1/auth/me — матчит frontend AuthUser interface
    (`platform-home-console/packages/auth-core/src/types.ts`):

        interface AuthUser { id: string; email: string; role?: string; name?: string }

    Намеренно отдельный DTO от UserDto: для фронта нужен компактный профиль
    текущего юзера (id/email/name/role), а admin endpoints отдают полную
    карточку (user_id/scopes/is_admin/created_at)."""

    id: str
    email: str
    role: Optional[str] = None
    name: Optional[str] = None


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
