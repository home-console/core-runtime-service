"""
Audit Binder — Tamper-evident credential security event persistence.

Binds credential subsystem events to global P0 storage (Merkle root + epochs).

Key Properties:
- Immutable: Events are written once, never modified
- Tamper-evident: Merkle root detects any tampering
- Rollback-proof: Epoch tracking detects database rollback
- Forensic: Hash chain links events for integrity verification
- Secure: No secret material stored, only fingerprints

Usage:
    from core.audit.binder import AuditBinder
    from core.audit.events import credential_created_event

    binder = AuditBinder(secure_storage)

    event = credential_created_event(
        user_id="user_123",
        credential_id="cred_456",
        fingerprint="sha256_hash_...",
        name="database_password"
    )

    event_id = await binder.append(event)
"""

from typing import Any, AsyncIterator, Optional

from core.audit.events import SecurityEvent, SecurityEventType


class AuditBinder:
    """
    Binds security events to tamper-evident P0 storage.

    Architecture:
    ```
    CredentialService
        ↓ (calls)
    AuditBinder.append(event)
        ↓ (wraps)
    SecureStorageWrapper.append("_audit.security", event.to_dict())
        ↓ (triggers)
    P0 Hardening:
        - Epoch bump (rollback detection)
        - Merkle root recalculation (tamper detection)
        - Append-only audit log (hash chain)
        - Atomic transaction (consistency)
    ```

    Namespace: _audit.security
    - Append-only: Each event has unique UUID key
    - Critical: Protected by secure_set/append semantics
    - Tamper-evident: Merkle root detection at startup
    - Rollback-proof: Epoch mismatch detection
    """

    NAMESPACE = "_audit.security"

    def __init__(self, secure_storage: Any):
        """
        Initialize AuditBinder with secure storage.

        Args:
            secure_storage: SecureStorageWrapper instance (must be initialized)
        """
        self._storage = secure_storage

    async def append(self, event: SecurityEvent) -> str:
        """
        Append security event to immutable audit trail.

        The event is:
        1. Converted to dictionary (immutable serialization)
        2. Encrypted with epoch (rollback protection)
        3. Added to Merkle tree (tamper detection)
        4. Hash-chained in audit log (forensic linkage)
        5. Committed atomically (consistency guarantee)

        Args:
            event: SecurityEvent to persist

        Returns:
            event.id (confirmation that append succeeded)

        Raises:
            StorageCorruptionError: If storage is tampered
            StorageRollbackDetected: If epoch regression detected
        """
        # Ensure event has ID
        if not event.id:
            raise ValueError("SecurityEvent must have non-empty id")

        # Update epoch in event before storing
        meta = await self._storage.get("_system.meta", "global_epoch")
        if meta:
            epoch = meta.get("epoch", 0)
            # Create a new event with epoch set
            event_dict = event.to_dict()
            event_dict["epoch"] = epoch
        else:
            event_dict = event.to_dict()

        # Append to secure storage (triggers P0 hardening)
        return await self._storage.append(self.NAMESPACE, event_dict)

    async def get(self, event_id: str) -> Optional[SecurityEvent]:
        """
        Retrieve a specific audit event by ID.

        Args:
            event_id: The event ID

        Returns:
            SecurityEvent or None if not found
        """
        data = await self._storage.get(self.NAMESPACE, event_id)
        if data:
            return SecurityEvent.from_dict(data)
        return None

    async def list_events(
        self, credential_id: Optional[str] = None
    ) -> AsyncIterator[SecurityEvent]:
        """
        List all audit events, optionally filtered by credential_id.

        Args:
            credential_id: If provided, only return events for this credential

        Yields:
            SecurityEvent instances in chronological order
        """
        # Get all event keys
        event_keys = await self._storage.list_keys(self.NAMESPACE)

        # Load and filter events
        for key in sorted(event_keys):  # Sort for chronological order
            data = await self._storage.get(self.NAMESPACE, key)
            if data:
                event = SecurityEvent.from_dict(data)

                # Filter by credential_id if specified
                if credential_id is None or event.credential_id == credential_id:
                    yield event

    async def count_events(self, credential_id: Optional[str] = None) -> int:
        """
        Count total audit events, optionally for specific credential.

        Args:
            credential_id: If provided, count only events for this credential

        Returns:
            Number of matching events
        """
        count = 0
        async for _ in self.list_events(credential_id):
            count += 1
        return count

    async def get_events_for_credential(
        self, credential_id: str
    ) -> list[SecurityEvent]:
        """
        Get all events for a specific credential.

        Useful for forensic investigation of a single credential's lifecycle.

        Args:
            credential_id: The credential to examine

        Returns:
            List of SecurityEvent in chronological order
        """
        events = []
        async for event in self.list_events(credential_id):
            events.append(event)
        return events

    async def get_secret_access_log(self, credential_id: str) -> list[SecurityEvent]:
        """
        Get all SECRET_READ events for a credential.

        Critical for compliance reporting: "Who accessed this secret when?"

        Args:
            credential_id: The credential to examine

        Returns:
            List of CREDENTIAL_SECRET_READ events only
        """
        events = []
        async for event in self.list_events(credential_id):
            if event.event_type == SecurityEventType.CREDENTIAL_SECRET_READ:
                events.append(event)
        return events

    async def get_access_violations(
        self, credential_id: Optional[str] = None
    ) -> list[SecurityEvent]:
        """
        Get all ACCESS_DENIED events.

        Critical for security incident response: "Who tried to access what?"

        Args:
            credential_id: If provided, only violations for this credential

        Returns:
            List of CREDENTIAL_ACCESS_DENIED events
        """
        violations = []
        async for event in self.list_events(credential_id):
            if event.event_type == SecurityEventType.CREDENTIAL_ACCESS_DENIED:
                violations.append(event)
        return violations

    async def audit_trail_for_user(self, user_id: str) -> list[SecurityEvent]:
        """
        Get all events initiated by a specific user.

        Args:
            user_id: The user to investigate

        Returns:
            List of all SecurityEvent where user_id matches
        """
        events = []
        event_keys = await self._storage.list_keys(self.NAMESPACE)

        for key in sorted(event_keys):
            data = await self._storage.get(self.NAMESPACE, key)
            if data and data.get("user_id") == user_id:
                events.append(SecurityEvent.from_dict(data))

        return events
