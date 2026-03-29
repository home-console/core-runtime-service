"""
DTO schemas for Credential operations.

Strict data transfer objects that isolate API from domain model.
No raw secrets in metadata DTOs.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from modules.credentials import CredentialType


@dataclass
class CreateCredentialRequest:
    """Request to create a new credential."""

    type: str  # CredentialType enum value
    name: str
    secret_ref: str
    username: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate request fields."""
        if not self.type:
            raise ValueError("type is required")
        if not self.name or not self.name.strip():
            raise ValueError("name is required and non-empty")
        if not self.secret_ref or not self.secret_ref.strip():
            raise ValueError("secret_ref is required and non-empty")

        # Validate type
        try:
            CredentialType(self.type)
        except ValueError:
            raise ValueError(f"Invalid credential type: {self.type}")


@dataclass
class UpdateCredentialRequest:
    """Request to update an existing credential."""

    id: str
    version: int
    name: Optional[str] = None
    type: Optional[str] = None
    username: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    tags: Optional[list[str]] = None

    def validate(self) -> None:
        """Validate request fields."""
        if not self.id or not self.id.strip():
            raise ValueError("id is required and non-empty")
        if self.version < 1:
            raise ValueError("version must be >= 1")


@dataclass
class CredentialMetadata:
    """Credential metadata (no secret)."""

    id: str
    type: str
    name: str
    secret_ref: str
    username: Optional[str]
    host: Optional[str]
    port: Optional[int]
    version: int
    created_at: str
    updated_at: str
    fingerprint: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_domain(cls, credential) -> "CredentialMetadata":
        """Convert domain Credential to metadata DTO."""
        return cls(
            id=credential.id,
            type=credential.type.value,
            name=credential.name,
            secret_ref=credential.secret_ref,
            username=credential.username,
            host=credential.host,
            port=credential.port,
            metadata=credential.metadata,
            tags=credential.tags,
            version=credential.version,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
            fingerprint=credential.fingerprint(),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON response."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "secret_ref": self.secret_ref,
            "username": self.username,
            "host": self.host,
            "port": self.port,
            "metadata": self.metadata,
            "tags": self.tags,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "fingerprint": self.fingerprint,
        }


@dataclass
class CredentialWithSecretResponse:
    """Credential with secret (elevated privilege)."""

    metadata: CredentialMetadata
    secret: bytes

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict (careful: includes secret)."""
        return {
            "metadata": self.metadata.to_dict(),
            "secret": self.secret.hex(),  # Hex-encoded for JSON
        }


@dataclass
class CredentialOperationResult:
    """Result of credential operation."""

    success: bool
    message: str
    credential_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON response."""
        result = {
            "success": self.success,
            "message": self.message,
        }
        if self.credential_id:
            result["credential_id"] = self.credential_id
        if self.metadata:
            result["metadata"] = self.metadata
        if self.error_code:
            result["error_code"] = self.error_code
        return result
