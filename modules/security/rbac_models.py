"""
RBAC Domain Models for Credential Subsystem

Immutable, serializable models for role-based access control.
No side effects, no mutable state.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(str, Enum):
    """User roles for credential access control."""
    
    ADMIN = "admin"                # Full access, all operations
    OPERATOR = "operator"          # Read/write own credentials
    DEVELOPER = "developer"        # Read/write for development
    READONLY = "readonly"          # Read-only access
    SERVICE = "service"            # Service account access


class CredentialAccessLevel(str, Enum):
    """Granular access levels for credential operations."""
    
    READ_METADATA = "read_metadata"     # Read credential without secret
    READ_SECRET = "read_secret"         # Read decrypted secret (elevated)
    WRITE = "write"                     # Create/update credential
    DELETE = "delete"                   # Delete credential
    ROTATE = "rotate"                   # Rotate secret (future)


@dataclass(frozen=True)
class CredentialPolicy:
    """
    Immutable policy for per-credential access control.
    
    Stored separately from credential metadata in control plane namespace.
    Versioned for audit trail.
    """
    
    # Identity
    credential_id: str
    
    # Ownership
    owner_user_id: str
    
    # Role-based access
    allowed_roles: list[Role] = field(default_factory=list)
    
    # Elevated access (secret read requires these roles)
    secret_read_roles: list[Role] = field(default_factory=list)
    
    # User-specific access (in addition to role-based)
    allowed_users: list[str] = field(default_factory=list)
    
    # Metadata
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
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
        """Deserialize from dictionary."""
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
        """Serialize to dictionary."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "required_roles": [r.value for r in self.required_roles] if self.required_roles else None,
        }
