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
from datetime import datetime, UTC
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
    
    # MFA authentication (zero-trust secret access)
    CREDENTIAL_MFA_REQUIRED = "credential.mfa.required"
    """Challenge: Elevation required for secret access"""
    
    CREDENTIAL_MFA_FAILED = "credential.mfa.failed"
    """Failed MFA verification (invalid TOTP code, WebAuthn failure, etc.)"""
    
    CREDENTIAL_MFA_ELEVATED = "credential.mfa.elevated"
    """Success: User passed MFA, elevation session created"""
    
    CREDENTIAL_ELEVATION_EXPIRED = "credential.elevation.expired"
    """Session TTL exceeded; re-authentication required"""
    
    # Self-defending vault (abuse detection)
    CREDENTIAL_ABUSE_DETECTED = "credential.abuse.detected"
    """Behavioral anomaly (spike, burst, brute force)"""
    
    CREDENTIAL_USER_FROZEN = "credential.user.frozen"
    """User account frozen due to abuse (requires manual intervention)"""
    
    CREDENTIAL_ELEVATION_REVOKED = "credential.elevation.revoked"
    """Elevation session revoked due to detected abuse"""
    
    # Risk scoring (adaptive defense)
    CREDENTIAL_RISK_EVENT = "credential.risk.event"
    """Activity contributing to user's risk score"""
    
    # Trust management
    TRUST_STATE_CHANGED = "trust.state.changed"
    """User's trust state transitioned"""
    
    TRUST_RESTORED = "trust.restored"
    """User's trust fully restored to NORMAL"""
    
    TRUST_FROZEN = "trust.frozen"
    """User account frozen due to critical risk"""
    
    TRUST_UNFROZEN = "trust.unfrozen"
    """User account unfrozen after freeze period expired"""
    
    TRUST_COOLDOWN_STARTED = "trust.cooldown.started"
    """User entered cooldown period"""
    
    TRUST_COOLDOWN_EXPIRED = "trust.cooldown.expired"
    """User's cooldown period expired and trust level adjusted"""


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
    
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
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


# MFA-related factory functions (zero-trust secret access)

def credential_mfa_required_event(
    user_id: str,
    credential_id: str,
    mfa_method: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: MFA challenge sent for secret elevation."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_MFA_REQUIRED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",  # No access yet
        metadata={
            "operation": "mfa_required",
            "mfa_method": mfa_method,
            **metadata_kwargs
        }
    )


def credential_mfa_failed_event(
    user_id: str,
    credential_id: str,
    mfa_method: str,
    reason: str = "verification_failed",
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: MFA verification failed (invalid code, expired, etc.)."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_MFA_FAILED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",  # No access (failed)
        metadata={
            "operation": "mfa_failed",
            "mfa_method": mfa_method,
            "reason": reason,
            **metadata_kwargs
        }
    )


def credential_mfa_elevated_event(
    user_id: str,
    credential_id: str,
    mfa_method: str,
    elevation_level: str = "secret_read",
    ttl_seconds: int = 90,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: User passed MFA, elevation session created."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_MFA_ELEVATED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",  # Session, not secret access yet
        metadata={
            "operation": "mfa_elevated",
            "mfa_method": mfa_method,
            "elevation_level": elevation_level,
            "ttl_seconds": ttl_seconds,
            **metadata_kwargs
        }
    )


def credential_elevation_expired_event(
    user_id: str,
    credential_id: str,
    elevation_level: str = "secret_read",
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Elevation session TTL exceeded."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_ELEVATION_EXPIRED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",
        metadata={
            "operation": "elevation_expired",
            "elevation_level": elevation_level,
            **metadata_kwargs
        }
    )


# Self-defending vault factory functions (abuse detection & response)

def credential_abuse_detected_event(
    user_id: str,
    credential_id: str,
    reason: str,
    action: str = "none",
    threshold_value: float = 0.0,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Behavioral anomaly detected (spike, burst, brute force)."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_ABUSE_DETECTED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",
        metadata={
            "operation": "abuse_detected",
            "reason": reason,
            "action": action,
            "threshold_value": threshold_value,
            **metadata_kwargs
        }
    )


def credential_user_frozen_event(
    user_id: str,
    reason: str,
    frozen_until: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: User account frozen due to detected abuse."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_USER_FROZEN,
        user_id=user_id,
        credential_id="",
        fingerprint="",
        metadata={
            "operation": "user_frozen",
            "reason": reason,
            "frozen_until": frozen_until,
            **metadata_kwargs
        }
    )


def credential_elevation_revoked_event(
    user_id: str,
    credential_id: str,
    reason: str,
    elevation_level: str = "secret_read",
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Elevation session revoked due to detected abuse."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_ELEVATION_REVOKED,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="",
        metadata={
            "operation": "elevation_revoked",
            "reason": reason,
            "elevation_level": elevation_level,
            **metadata_kwargs
        }
    )


# Risk scoring factory function

def credential_risk_event(
    user_id: str,
    event_type: str,
    risk_weight: float,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Activity logged to risk score."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_RISK_EVENT,
        user_id=user_id,
        credential_id="",
        fingerprint="",
        metadata={
            "operation": "risk_event",
            "event_type": event_type,
            "risk_weight": risk_weight,
            **metadata_kwargs
        }
    )


# Trust management factory functions

def trust_state_changed_event(
    user_id: str,
    event: str,
    risk_score: float,
    new_level: str,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: User's trust state changed."""
    return SecurityEvent(
        event_type=SecurityEventType.TRUST_STATE_CHANGED,
        user_id=user_id,
        credential_id="",
        fingerprint="",
        metadata={
            "operation": "trust_state_changed",
            "event": event,
            "risk_score": risk_score,
            "new_level": new_level,
            **metadata_kwargs
        }
    )


def trust_restored_event(
    user_id: str,
    previous_risk: float,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: User's trust fully restored to NORMAL."""
    return SecurityEvent(
        event_type=SecurityEventType.TRUST_RESTORED,
        user_id=user_id,
        credential_id="",
        fingerprint="",
        metadata={
            "operation": "trust_restored",
            "previous_risk": previous_risk,
            **metadata_kwargs
        }
    )


def trust_frozen_event(
    user_id: str,
    risk_score: float,
    reason: str = "",
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: User account frozen due to critical risk."""
    return SecurityEvent(
        event_type=SecurityEventType.TRUST_FROZEN,
        user_id=user_id,
        credential_id="",
        fingerprint="",
        metadata={
            "operation": "trust_frozen",
            "risk_score": risk_score,
            "reason": reason,
            **metadata_kwargs
        }
    )


def trust_unfrozen_event(
    user_id: str,
    reason: str = "Freeze period expired",
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: User account unfrozen."""
    return SecurityEvent(
        event_type=SecurityEventType.TRUST_UNFROZEN,
        user_id=user_id,
        credential_id="",
        fingerprint="",
        metadata={
            "operation": "trust_unfrozen",
            "reason": reason,
            **metadata_kwargs
        }
    )

def credential_access_allowed_event(
    user_id: str,
    credential_id: str,
    risk_score: float = 0.0,
    events: list = None,
    **metadata_kwargs: Any
) -> SecurityEvent:
    """Event: Secret access allowed (all security checks passed)."""
    return SecurityEvent(
        event_type=SecurityEventType.CREDENTIAL_SECRET_READ,
        user_id=user_id,
        credential_id=credential_id,
        fingerprint="authorized",
        metadata={
            "operation": "secret_access_allowed",
            "risk_score": risk_score,
            "security_events": events or [],
            **metadata_kwargs
        }
    )
