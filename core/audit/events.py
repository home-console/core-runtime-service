"""
Security Event Models — Tamper-evident audit events for credential subsystem.

Events are immutable, fingerprint-based (no secrets), and stored in append-only
P0 protected storage with Merkle root verification and epoch protection.

Usage:
    event = SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_CREATED,
        user_id="user_123",
        credential_id="cred_456",
        fingerprint="abc123...",
        metadata={"name": "database_password"}
    )
    await audit_binder.append(event)

Events never contain:
    ❌ Secret material
    ❌ Decrypted values
    ❌ PII beyond user_id
    ✅ Fingerprints/hashes instead
    ✅ Operation metadata only
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
from datetime import datetime
from uuid import uuid4


class SecurityEventType(str, Enum):
    """Types of security events tracked for credentials."""
    
    # Credential lifecycle
    CREDENTIAL_CREATED = "credential.created"
    CREDENTIAL_UPDATED = "credential.updated"
    CREDENTIAL_DELETED = "credential.deleted"
    
    # Secret access (most critical)
    CREDENTIAL_SECRET_READ = "credential.secret.read"
    
    # Access control violations
    CREDENTIAL_ACCESS_DENIED = "credential.access.denied"
    
    # Rotation/maintenance
    CREDENTIAL_ROTATED = "credential.rotated"
    CREDENTIAL_EXPIRED = "credential.expired"


@dataclass(frozen=True)
class SecurityEvent:
    """
    Immutable security event for audit trail.
    
    Properties:
    - immutable: frozen=True prevents post-creation modifications
    - no secrets: contains fingerprint, not actual secret material
    - traceable: includes user_id, credential_id, timestamp
    - verifiable: includes fingerprint hash of the credential state
    
    Design: Fingerprint uniquely identifies credential state at time of event
    (sha256(value)) but contains no actual secret material. This allows
    verification that a specific version was accessed without storing secrets.
    """
    
    id: str = field(default_factory=lambda: str(uuid4()))
    """Unique event ID (UUID v4)"""
    
    event_type: SecurityEventType = field(default=SecurityEventType.CREDENTIAL_ACCESS_DENIED)
    """Type of security event"""
    
    user_id: str = field(default="")
    """User who performed the action (or attempted it)"""
    
    credential_id: str = field(default="")
    """Credential affected by the action"""
    
    fingerprint: str = field(default="")
    """
    SHA256 hash of credential value/metadata.
    Identifies state uniquely without storing secret.
    Empty string if access was denied (before read).
    """
    
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    """UTC timestamp when event occurred"""
    
    metadata: dict[str, Any] = field(default_factory=dict)
    """
    Operation metadata (non-sensitive context).
    Examples:
    - {"operation": "create", "name": "db_password"}
    - {"operation": "read", "location": "127.0.0.1", "mfa_used": true}
    - {"operation": "deny", "reason": "insufficient_role", "required": "OPERATOR"}
    """
    
    epoch: Optional[int] = None
    """Epoch at time of audit write (for rollback detection)"""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        # Convert enum to string
        if isinstance(data["event_type"], SecurityEventType):
            data["event_type"] = data["event_type"].value
        return data
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityEvent":
        """Reconstruct from stored dictionary."""
        data_copy = data.copy()
        
        # Convert string to enum
        if isinstance(data_copy.get("event_type"), str):
            data_copy["event_type"] = SecurityEventType(data_copy["event_type"])
        
        return cls(**data_copy)


# Pre-built factory functions for common audit scenarios

def credential_created_event(
    user_id: str,
    credential_id: str,
    fingerprint: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Credential successfully created."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_CREATED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint=fingerprint,
        metadata={"operation": "created", **metadata_kwargs}
    )


def credential_updated_event(
    user_id: str,
    credential_id: str,
    old_fingerprint: str,
    new_fingerprint: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Credential successfully updated."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_UPDATED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint=new_fingerprint,
        metadata={
            "operation": "updated",
            "old_fingerprint": old_fingerprint,
            "new_fingerprint": new_fingerprint,
            **metadata_kwargs
        }
    )


def credential_deleted_event(
    user_id: str,
    credential_id: str,
    fingerprint: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Credential successfully deleted."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_DELETED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint=fingerprint,
        metadata={"operation": "deleted", **metadata_kwargs}
    )


def credential_secret_read_event(
    user_id: str,
    credential_id: str,
    fingerprint: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Secret material was accessed and decrypted."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_SECRET_READ,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint=fingerprint,
        metadata={"operation": "secret_read", **metadata_kwargs}
    )


def credential_access_denied_event(
    user_id: str,
    credential_id: str,
    reason: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Access attempt was denied (RBAC violation)."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_ACCESS_DENIED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",  # No access, no fingerprint
        metadata={"operation": "access_denied", "reason": reason, **metadata_kwargs}
    )


def credential_rotated_event(
    user_id: str,
    credential_id: str,
    old_fingerprint: str,
    new_fingerprint: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Credential was rotated (old secret retired)."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_ROTATED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint=new_fingerprint,
        metadata={
            "operation": "rotated",
            "old_fingerprint": old_fingerprint,
            "new_fingerprint": new_fingerprint,
            **metadata_kwargs
        }
    )
