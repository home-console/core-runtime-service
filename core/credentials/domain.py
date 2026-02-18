"""
Credential Domain Model

Clean, immutable domain object for credentials.
No storage, no vault integration, no side effects.

Supports:
- Immutable dataclass (frozen)
- Type-specific validation
- Deterministic serialization
- Fingerprinting for integrity
- Safe mutation (immutable pattern)
- Versioning
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any
from datetime import datetime, timezone
import uuid
import json
from hashlib import sha256


class CredentialValidationError(ValueError):
    """Raised when credential validation fails."""

    pass


class CredentialType(str, Enum):
    """Types of credentials supported by the system."""

    SSH_PASSWORD = "ssh_password"
    SSH_KEY = "ssh_key"
    API_TOKEN = "api_token"
    OAUTH_TOKEN = "oauth_token"
    DATABASE_PASSWORD = "database_password"
    GENERIC_SECRET = "generic_secret"


@dataclass(frozen=True)
class Credential:
    """
    Immutable domain model for a credential.

    Represents a single credential with metadata, versioning, and auditable stamps.
    All operations return new instances (immutable pattern).

    Fields:
        id: UUID4 string identifier
        type: Credential type (SSH, API, DB, etc.)
        name: Human-readable name
        secret_ref: Reference key in vault (where actual secret is stored)
        username: Username (required for SSH/DB)
        host: Hostname (required for SSH/DB)
        port: Port number (required for DATABASE)
        metadata: Arbitrary metadata dict
        tags: List of string tags
        version: Optimistic version counter (starts at 1)
        created_at: ISO8601 UTC timestamp
        updated_at: ISO8601 UTC timestamp
        rotation_policy: Optional rotation policy for lifecycle management
    """

    id: str
    type: CredentialType
    name: str
    secret_ref: str
    username: Optional[str]
    host: Optional[str]
    port: Optional[int]
    metadata: dict[str, Any]
    tags: list[str]
    version: int
    created_at: str  # ISO8601 UTC
    updated_at: str  # ISO8601 UTC
    rotation_policy: Optional[dict[str, Any]] = None  # RotationPolicy as dict

    def validate(self) -> None:
        """
        Validate credential fields.

        Checks:
        - All required fields are non-empty
        - Timestamps are valid ISO8601 and ordered
        - Type-specific constraints are met
        - Version is positive

        Raises:
            CredentialValidationError: if validation fails
        """
        # Common validations
        if not self.id or not isinstance(self.id, str):
            raise CredentialValidationError("id must be non-empty string")

        if not self.name or not isinstance(self.name, str):
            raise CredentialValidationError("name must be non-empty string")

        if self.version < 1:
            raise CredentialValidationError("version must be >= 1")

        if not self.secret_ref or not isinstance(self.secret_ref, str):
            raise CredentialValidationError("secret_ref must be non-empty string")

        # Validate type
        if not isinstance(self.type, CredentialType):
            raise CredentialValidationError("type must be CredentialType")

        # Validate timestamps (ISO8601 format)
        try:
            created = datetime.fromisoformat(
                self.created_at.replace("Z", "+00:00")
            )
            updated = datetime.fromisoformat(
                self.updated_at.replace("Z", "+00:00")
            )

            if updated < created:
                raise CredentialValidationError(
                    "updated_at cannot be before created_at"
                )
        except ValueError as e:
            raise CredentialValidationError(
                f"Invalid ISO8601 timestamp: {e}"
            )

        # Type-specific validations
        if self.type in (
            CredentialType.SSH_PASSWORD,
            CredentialType.SSH_KEY,
        ):
            if not self.host:
                raise CredentialValidationError(
                    f"{self.type.value} requires host"
                )
            if not self.username:
                raise CredentialValidationError(
                    f"{self.type.value} requires username"
                )

        if self.type == CredentialType.DATABASE_PASSWORD:
            if not self.host:
                raise CredentialValidationError(
                    "DATABASE_PASSWORD requires host"
                )
            if not self.port or self.port <= 0:
                raise CredentialValidationError(
                    "DATABASE_PASSWORD requires port > 0"
                )

        # Validate metadata and tags
        if not isinstance(self.metadata, dict):
            raise CredentialValidationError("metadata must be a dict")

        if not isinstance(self.tags, list) or not all(
            isinstance(t, str) for t in self.tags
        ):
            raise CredentialValidationError("tags must be list of strings")

    @classmethod
    def create(
        cls,
        type: CredentialType,
        name: str,
        secret_ref: str,
        username: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        rotation_policy: Optional[dict[str, Any]] = None,
    ) -> "Credential":
        """
        Create a new credential with defaults.

        Generates UUID, sets version to 1, and timestamps to current UTC time.
        Runs validation before returning.

        Args:
            type: credential type
            name: human-readable name
            secret_ref: reference key in vault
            username: username (required for SSH/DB)
            host: hostname (required for SSH/DB)
            port: port number (required for DATABASE)
            metadata: arbitrary metadata (default: {})
            tags: list of tags (default: [])
            rotation_policy: rotation policy dict (optional)

        Returns:
            New Credential instance

        Raises:
            CredentialValidationError: if validation fails
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        credential = cls(
            id=str(uuid.uuid4()),
            type=type,
            name=name,
            secret_ref=secret_ref,
            username=username,
            host=host,
            port=port,
            metadata=metadata or {},
            tags=tags or [],
            version=1,
            created_at=now,
            updated_at=now,
            rotation_policy=rotation_policy,
        )

        credential.validate()
        return credential

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary.

        Converts type enum to string value. No secrets are included
        (only secret_ref pointer).

        Returns:
            Dictionary with all fields, type as string value
        """
        return {
            "id": self.id,
            "type": self.type.value,
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
            "rotation_policy": self.rotation_policy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Credential":
        """
        Deserialize from dictionary.

        Parses type enum from string. Validates on construction.

        Args:
            data: dictionary with credential fields

        Returns:
            Credential instance

        Raises:
            CredentialValidationError: if validation fails
        """
        # Parse type enum
        type_value = data.get("type")
        if isinstance(type_value, str):
            try:
                cred_type = CredentialType(type_value)
            except ValueError:
                raise CredentialValidationError(
                    f"Invalid credential type: {type_value}"
                )
        else:
            cred_type = type_value

        credential = cls(
            id=data.get("id"),
            type=cred_type,
            name=data.get("name"),
            secret_ref=data.get("secret_ref"),
            username=data.get("username"),
            host=data.get("host"),
            port=data.get("port"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            version=data.get("version", 1),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            rotation_policy=data.get("rotation_policy"),
        )

        credential.validate()
        return credential

    def fingerprint(self) -> str:
        """
        Compute SHA256 fingerprint for integrity checking.

        Excludes updated_at so the fingerprint remains stable
        across updates. Useful for audit chains and change detection.

        Uses canonical JSON (sorted keys, no whitespace) for
        deterministic results.

        Returns:
            Hex-encoded SHA256 hash
        """
        # Create dict without updated_at for determinism
        fp_data = {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "secret_ref": self.secret_ref,
            "username": self.username,
            "host": self.host,
            "port": self.port,
            "metadata": self.metadata,
            "tags": sorted(self.tags),
            "version": self.version,
            "created_at": self.created_at,
        }

        # Canonical JSON: sorted keys, no whitespace
        json_str = json.dumps(
            fp_data, sort_keys=True, separators=(",", ":")
        )
        hash_obj = sha256(json_str.encode("utf-8"))
        return hash_obj.hexdigest()

    def mutate(self, **changes) -> "Credential":
        """
        Create a new credential with updates (immutable pattern).

        Returns new instance with:
        - Applied changes
        - Version incremented
        - updated_at set to now
        - created_at preserved

        Original credential is unchanged.

        Args:
            **changes: fields to update

        Returns:
            New Credential instance with version incremented

        Raises:
            CredentialValidationError: if validation fails
        """
        # Get current values
        data = self.to_dict()

        # Apply changes
        data.update(changes)

        # Increment version if not explicitly set
        if "version" not in changes:
            data["version"] = self.version + 1

        # Update timestamp if not explicitly set
        if "updated_at" not in changes:
            now = datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
            data["updated_at"] = now

        # Preserve creation time
        data["created_at"] = self.created_at

        # Create new credential
        return Credential.from_dict(data)
