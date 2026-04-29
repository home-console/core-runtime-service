"""
Shared domain: access (RBAC) models.

Важно: этот модуль не должен импортировать ничего из modules.security или modules.credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(str, Enum):
    """User roles for credential access control."""

    ADMIN = "admin"
    OPERATOR = "operator"
    DEVELOPER = "developer"
    READONLY = "readonly"
    SERVICE = "service"


class CredentialAccessLevel(str, Enum):
    """Granular access levels for credential operations."""

    READ_METADATA = "read_metadata"
    READ_SECRET = "read_secret"
    WRITE = "write"
    DELETE = "delete"
    ROTATE = "rotate"


@dataclass(frozen=True)
class CredentialPolicy:
    """Immutable policy for per-credential access control."""

    credential_id: str
    owner_user_id: str
    allowed_roles: list[Role] = field(default_factory=list)
    secret_read_roles: list[Role] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "credential_id": self.credential_id,
            "owner_user_id": self.owner_user_id,
            "allowed_roles": [role.value for role in self.allowed_roles],
            "secret_read_roles": [role.value for role in self.secret_read_roles],
            "allowed_users": self.allowed_users,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CredentialPolicy":
        return cls(
            credential_id=data["credential_id"],
            owner_user_id=data["owner_user_id"],
            allowed_roles=[Role(r) for r in data.get("allowed_roles", [])],
            secret_read_roles=[Role(r) for r in data.get("secret_read_roles", [])],
            allowed_users=data.get("allowed_users", []),
            version=data.get("version", 1),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass(frozen=True)
class AccessDecision:
    """Immutable result of access evaluation."""

    allowed: bool
    reason: str = ""
    required_roles: Optional[list[Role]] = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "required_roles": (
                [r.value for r in self.required_roles] if self.required_roles else None
            ),
        }

