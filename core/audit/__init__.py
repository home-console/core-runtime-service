"""
core.audit — Tamper-evident security audit subsystem.

Module exports:
- SecurityEventType: Enum of event types (created, updated, deleted, etc.)
- SecurityEvent: Immutable audit event dataclass
- AuditBinder: Tamper-evident event persistence with Merkle root protection
- Various factory functions for creating specific event types

Integration:
    from core.audit import AuditBinder, credential_created_event
    
    # In CredentialService
    self.audit_binder = AuditBinder(secure_storage)
    
    event = credential_created_event(
        user_id=user_id,
        credential_id=credential.id,
        fingerprint=credential.fingerprint(),
        name=credential.name
    )
    await self.audit_binder.append(event)
"""

from core.audit.events import (
    SecurityEventType,
    SecurityEvent,
    credential_created_event,
    credential_updated_event,
    credential_deleted_event,
    credential_secret_read_event,
    credential_access_denied_event,
    credential_rotated_event,
)
from core.audit.binder import AuditBinder

__all__ = [
    "SecurityEventType",
    "SecurityEvent",
    "AuditBinder",
    "credential_created_event",
    "credential_updated_event",
    "credential_deleted_event",
    "credential_secret_read_event",
    "credential_access_denied_event",
    "credential_rotated_event",
]
