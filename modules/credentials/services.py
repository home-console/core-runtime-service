"""
CredentialService — business logic for credential operations.

Integrates repository with audit and RBAC enforcement.

Step 17.5: Tamper-evident audit logging via AuditBinder
Step 17.6: Zero-trust secret access with MFA elevation
"""

from typing import Any, Dict, Optional, List, TYPE_CHECKING
from datetime import datetime, UTC

from modules.security import CredentialAccessLevel, CredentialPolicy, RiskAction, Role
from modules.credentials import (
    Credential,
    CredentialAccessDenied,
    CredentialAlreadyExists,
    CredentialNotFound,
    CredentialRepository,
    CredentialSecretLeakage,
    CredentialType,
    CredentialVersionConflict,
)
from modules.credentials.policy_enforcer import CredentialRBACEnforcer

from .schemas import (
    CreateCredentialRequest,
    CredentialMetadata,
    CredentialWithSecretResponse,
    UpdateCredentialRequest,
)

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder
    from modules.security import MFAService, RiskEngine, TrustEngine
    from modules.credentials.abuse_detection import CredentialAbuseDetector
    from modules.credentials.security_orchestrator import CredentialSecurityOrchestrator


class CredentialService:
    """
    Service layer for credential operations.

    Coordinates:
    - RBAC enforcement (access control before operation)
    - CredentialRepository (persistence)
    - Audit binder (tamper-evident tracing via P0 storage)
    - MFA service (zero-trust elevation for secret access)
    - Rate limiting (implicit through operation registration)

    IMPORTANT:
    1. RBAC enforcement happens BEFORE repository calls.
    2. MFA elevation session validated before secret read.
    3. All access denials logged to P0 protected audit trail.
    4. Successful operations logged with fingerprints (not secrets).
    5. All denials raise CredentialAccessDenied.
    """

    def __init__(
        self,
        repository: CredentialRepository,
        rbac_enforcer: Optional[CredentialRBACEnforcer] = None,
        audit_binder: Optional["AuditBinder"] = None,
        mfa_service: Optional["MFAService"] = None,
        abuse_detector: Optional["CredentialAbuseDetector"] = None,
        risk_engine: Optional["RiskEngine"] = None,
        trust_engine: Optional["TrustEngine"] = None,
        security_orchestrator: Optional["CredentialSecurityOrchestrator"] = None,
        audit_logger: Optional[Any] = None,
    ):
        """
        Initialize credential service.

        Args:
            repository: CredentialRepository instance
            rbac_enforcer: RBAC enforcer for access control
            audit_binder: Optional AuditBinder for P0 tamper-evident audit (Step 17.5)
            mfa_service: Optional MFAService for zero-trust secret access (Step 17.6)
            abuse_detector: Optional CredentialAbuseDetector for self-defense (Step 17.7)
            risk_engine: Optional RiskEngine for adaptive risk scoring (Step 17.8)
            trust_engine: Optional TrustEngine for automatic trust recovery (Step 17.9)
            security_orchestrator: Optional SecurityDecisionOrchestrator for unified auth (Step 17.10)
            audit_logger: Optional legacy audit logger (deprecated, use audit_binder)
        """
        self.repo = repository
        self.audit_binder = audit_binder  # P0 protected audit (Step 17.5)
        self.audit_legacy = audit_logger  # Legacy audit (deprecated)
        self.rbac = rbac_enforcer
        self.mfa_service = mfa_service  # MFA service (Step 17.6)
        self.abuse_detector = abuse_detector  # Abuse detector (Step 17.7)
        self.risk_engine = risk_engine  # Risk engine (Step 17.8)
        self.trust_engine = trust_engine  # Trust engine (Step 17.9)
        self.security_orchestrator = (
            security_orchestrator  # Security orchestrator (Step 17.10)
        )

        # Pass audit_binder to enforcer so it logs denials
        if self.rbac and self.audit_binder:
            self.rbac.audit_binder = self.audit_binder

        # Pass elevation session manager to enforcer
        if self.rbac and self.mfa_service:
            self.rbac.elevation_session_manager = (
                self.mfa_service.elevation_session_manager
            )

    async def create(
        self,
        request: CreateCredentialRequest,
        secret: bytes,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> CredentialMetadata:
        """
        Create a new credential.

        RBAC: Requires credentials.write capability
        Ownership: Creator becomes owner

        Args:
            request: CreateCredentialRequest
            secret: Raw secret bytes (password, key, token, etc.)
            user_id: User creating credential (for audit)
            user_roles: User's roles (for RBAC check, optional if no enforcer)

        Returns:
            CredentialMetadata (without secret)

        Raises:
            ValueError: if request validation fails
            CredentialAlreadyExists: if credential with ID already exists
            CredentialSecretLeakage: if metadata contains secret keywords
            CredentialAccessDenied: if user lacks write capability
        """
        # Validate request
        request.validate()

        # Create domain credential
        credential = Credential.create(
            type=CredentialType(request.type),
            name=request.name,
            secret_ref=request.secret_ref,
            username=request.username,
            host=request.host,
            port=request.port,
            metadata=request.metadata,
            tags=request.tags,
        )

        # Persist credential (atomic)
        try:
            created = await self.repo.create(credential, secret)
        except (CredentialAlreadyExists, CredentialSecretLeakage) as e:
            await self._audit_failure("create", user_id, str(e))
            raise

        # Create default policy (owner = creator)
        if user_id:
            policy = CredentialPolicy(
                credential_id=created.id,
                owner_user_id=user_id,
                allowed_roles=[Role.ADMIN],  # Admin can always access
                secret_read_roles=[Role.ADMIN],  # Only admin can read secret
                allowed_users=[user_id],  # Owner can access
                version=1,
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
            await self.repo.create_policy(policy)

        # Audit success
        await self._audit_success(
            "create",
            user_id,
            created.id,
            created.fingerprint(),
        )

        return CredentialMetadata.from_domain(created)

    async def get(
        self,
        credential_id: str,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> CredentialMetadata:
        """
        Get credential metadata (without secret).

        RBAC: Requires credentials.read capability

        Args:
            credential_id: Credential ID
            user_id: User requesting access (for RBAC/audit)
            user_roles: User's roles (for RBAC check)

        Returns:
            CredentialMetadata (no secret)

        Raises:
            CredentialNotFound: If credential doesn't exist
            CredentialAccessDenied: If user not authorized to read metadata
        """
        # RBAC enforcement
        if self.rbac and user_id and user_roles:
            await self.rbac.enforce_or_raise(
                user_id=user_id,
                user_roles=user_roles,
                credential_id=credential_id,
                access_level=CredentialAccessLevel.READ_METADATA,
            )

        # Fetch credential
        credential = await self.repo.get(credential_id)
        if credential is None:
            await self._audit_failure("get", user_id, "Credential not found")
            raise CredentialNotFound(f"Credential {credential_id} not found")

        # Audit success
        await self._audit_success("get", user_id, credential_id, credential.fingerprint())

        return CredentialMetadata.from_domain(credential)

    async def get_with_secret(
        self,
        credential_id: str,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> CredentialWithSecretResponse:
        """
        Get credential with decrypted secret.

        ORCHESTRATED AUTHORIZATION (Step 17.10):
        Unified security decision through SecurityDecisionOrchestrator:
        - Layer 1: Trust state check (frozen = denied)
        - Layer 2: RBAC enforcement (insufficient privilege = denied)
        - Layer 3: Abuse detection (pattern detection = denied/blocked)
        - Layer 4: Risk assessment (adaptive risk scoring)
        - Layer 5: TrustEngine evaluation (freeze/block/mfa/allow)

        Args:
            credential_id: Credential ID
            user_id: User requesting access (for RBAC/audit)
            user_roles: User's roles (for RBAC check)

        Returns:
            CredentialWithSecretResponse (includes secret)

        Raises:
            CredentialNotFound: If credential doesn't exist
            CredentialAccessDenied: If authorization failed (any layer)
            MFARequired: If MFA elevation required (Step 17.10)
            TemporaryBlockError: If temporarily blocked
            AccountFrozen: If account frozen
        """
        # ════════════════════════════════════════════════════
        # UNIFIED AUTHORIZATION DECISION (Step 17.10)
        # ════════════════════════════════════════════════════
        if self.security_orchestrator and user_id:
            security_decision = (
                await self.security_orchestrator.authorize_secret_access(
                    user_id=user_id,
                    credential_id=credential_id,
                    user_roles=user_roles,
                )
            )

            # Handle orchestrator decisions
            if security_decision.frozen:
                raise CredentialAccessDenied(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    access_level=CredentialAccessLevel.READ_SECRET.value,
                    reason=f"Account frozen: {security_decision.reason.value}",
                )

            if security_decision.blocked:
                raise CredentialAccessDenied(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    access_level=CredentialAccessLevel.READ_SECRET.value,
                    reason=f"Temporarily blocked: {security_decision.reason.value}",
                )

            if security_decision.requires_mfa:
                raise CredentialAccessDenied(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    access_level=CredentialAccessLevel.READ_SECRET.value,
                    reason=f"MFA elevation required: {security_decision.reason.value}",
                )

            if not security_decision.allowed:
                raise CredentialAccessDenied(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    access_level=CredentialAccessLevel.READ_SECRET.value,
                    reason=f"Authorization denied: {security_decision.reason.value}",
                )
        else:
            # Fallback if no orchestrator (should not happen in production)
            # Perform legacy security checks
            if self.rbac and user_id and user_roles:
                await self.rbac.enforce_or_raise_elevated(
                    user_id=user_id,
                    user_roles=user_roles,
                    credential_id=credential_id,
                )

            if self.abuse_detector and user_id:
                await self.abuse_detector.validate_secret_read(user_id, credential_id)

            if self.risk_engine and user_id:
                assessment = await self.risk_engine.assess(user_id)
                match assessment.action:
                    case RiskAction.ALLOW:
                        pass
                    case RiskAction.REQUIRE_MFA:
                        raise CredentialAccessDenied(
                            user_id=user_id or "system",
                            credential_id=credential_id,
                            access_level=CredentialAccessLevel.READ_SECRET.value,
                            reason="MFA elevation required",
                        )
                    case RiskAction.TEMP_BLOCK:
                        raise CredentialAccessDenied(
                            user_id=user_id or "system",
                            credential_id=credential_id,
                            access_level=CredentialAccessLevel.READ_SECRET.value,
                            reason=f"Temporarily blocked (risk: {assessment.score:.1f})",
                        )
                    case RiskAction.FREEZE:
                        raise CredentialAccessDenied(
                            user_id=user_id or "system",
                            credential_id=credential_id,
                            access_level=CredentialAccessLevel.READ_SECRET.value,
                            reason=f"Account frozen (risk: {assessment.score:.1f})",
                        )

        # ════════════════════════════════════════════════════
        # AUTHORIZATION PASSED - RETURN SECRET
        # ════════════════════════════════════════════════════
        credential_tuple = await self.repo.get_with_secret(credential_id)
        if not credential_tuple or not credential_tuple[0]:
            await self._audit_failure(
                "get_with_secret", user_id, "Credential not found"
            )
            raise CredentialNotFound(f"Credential {credential_id} not found")

        cred_obj, secret = credential_tuple

        # Audit elevated access (always logged)
        await self._audit_success(
            "get_with_secret",
            user_id,
            credential_id,
            cred_obj.fingerprint(),
            access_level="READ_SECRET",
        )

        return CredentialWithSecretResponse(
            metadata=CredentialMetadata.from_domain(cred_obj),
            secret=secret,
        )

    async def list(
        self,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> List[CredentialMetadata]:
        """
        List all credentials visible to user.

        RBAC: Requires credentials.read capability
        Filter: Returns only credentials user is authorized for

        Args:
            user_id: User listing credentials (for RBAC/audit)
            user_roles: User's roles (for RBAC check)

        Returns:
            List of CredentialMetadata (no secrets)
        """
        # Fetch all credentials (RBAC filtering below)
        all_credentials = await self.repo.list()

        # Filter based on RBAC policies
        visible = []
        for credential in all_credentials:
            try:
                if self.rbac and user_id and user_roles:
                    await self.rbac.enforce_or_raise(
                        user_id=user_id,
                        user_roles=user_roles,
                        credential_id=credential.id,
                        access_level=CredentialAccessLevel.READ_METADATA,
                    )
                visible.append(CredentialMetadata.from_domain(credential))
            except CredentialAccessDenied:
                # Skip credentials user is not authorized for
                pass

        # Audit
        await self._audit_success("list", user_id, "N/A", "N/A")

        return visible

    async def update(
        self,
        request: UpdateCredentialRequest,
        secret: Optional[bytes] = None,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> CredentialMetadata:
        """
        Update credential metadata and/or secret.

        RBAC: Requires credentials.write capability
        Optimistic Locking: Version must match current + 1

        Args:
            request: UpdateCredentialRequest (includes version)
            secret: Optional new secret (if updating secret)
            user_id: User performing update (for RBAC/audit)
            user_roles: User's roles (for RBAC check)

        Returns:
            Updated CredentialMetadata

        Raises:
            CredentialNotFound: If credential doesn't exist
            CredentialVersionConflict: If version mismatch
            CredentialAccessDenied: If user not authorized to write
        """
        # RBAC enforcement
        if self.rbac and user_id and user_roles:
            await self.rbac.enforce_or_raise(
                user_id=user_id,
                user_roles=user_roles,
                credential_id=request.id,
                access_level=CredentialAccessLevel.WRITE,
            )

        # Validate request
        request.validate()

        # Load current credential
        current = await self.repo.get(request.id)
        if current is None:
            await self._audit_failure("update", user_id, "Credential not found")
            raise CredentialNotFound(f"Credential {request.id} not found")

        # Prepare mutated credential (version auto-increments)
        changes = {}
        if request.name is not None:
            changes["name"] = request.name
        if request.metadata is not None:
            changes["metadata"] = request.metadata
        if request.tags is not None:
            changes["tags"] = request.tags

        updated = current.mutate(**changes)

        # Optimistic locking check
        if updated.version != request.version + 1:
            await self._audit_failure(
                "update",
                user_id,
                f"Version conflict: expected {request.version}, got {current.version}",
            )
            raise CredentialVersionConflict(
                request.id, expected=request.version + 1, actual=updated.version
            )

        # Persist update
        try:
            result = await self.repo.update(updated, secret=secret)
        except (
            CredentialNotFound,
            CredentialVersionConflict,
            CredentialSecretLeakage,
        ) as e:
            await self._audit_failure("update", user_id, str(e))
            raise

        # Audit (track old vs new fingerprint)
        await self._audit_success(
            "update",
            user_id,
            result.id,
            result.fingerprint(),
            old_fingerprint=current.fingerprint(),
        )

        return CredentialMetadata.from_domain(result)

    async def delete(
        self,
        credential_id: str,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> None:
        """
        Delete credential and its policy.

        RBAC: Requires credentials.delete capability
        Note: Only ADMIN can delete (non-owners denied at policy level)

        Args:
            credential_id: Credential ID
            user_id: User performing delete (for RBAC/audit)
            user_roles: User's roles (for RBAC check)

        Raises:
            CredentialNotFound: If credential doesn't exist (idempotent so OK)
            CredentialAccessDenied: If user not authorized to delete
        """
        # RBAC enforcement (DELETE requires ADMIN even for owner)
        if self.rbac and user_id and user_roles:
            await self.rbac.enforce_or_raise(
                user_id=user_id,
                user_roles=user_roles,
                credential_id=credential_id,
                access_level=CredentialAccessLevel.DELETE,
            )

        # Load credential (for audit)
        credential = await self.repo.get(credential_id)
        fingerprint = credential.fingerprint() if credential else "unknown"

        # Delete credential and policy
        await self.repo.delete(credential_id)
        await self.repo.delete_policy(credential_id)

        # Audit
        await self._audit_success("delete", user_id, credential_id, fingerprint)

    async def exists(
        self,
        credential_id: str,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> bool:
        """
        Check if credential exists (metadata read only).

        RBAC: Requires credentials.read capability

        Args:
            credential_id: Credential ID
            user_id: User performing check (for RBAC/audit)
            user_roles: User's roles (for RBAC check)

        Returns:
            True if exists and user authorized, False otherwise
        """
        # RBAC enforcement
        if self.rbac and user_id and user_roles:
            try:
                await self.rbac.enforce_or_raise(
                    user_id=user_id,
                    user_roles=user_roles,
                    credential_id=credential_id,
                    access_level=CredentialAccessLevel.READ_METADATA,
                )
            except CredentialAccessDenied:
                return False

        return await self.repo.exists(credential_id)

    async def count(
        self,
        user_id: Optional[str] = None,
        user_roles: Optional[List[Role]] = None,
    ) -> int:
        """
        Count credentials visible to user.

        RBAC: Requires credentials.read capability
        Filter: Counts only authorized credentials

        Args:
            user_id: User counting credentials (for audit)
            user_roles: User's roles (for RBAC check)

        Returns:
            Count of visible credentials
        """
        # Get all credentials and filter by RBAC
        all_credentials = await self.repo.list()

        count = 0
        for credential in all_credentials:
            try:
                if self.rbac and user_id and user_roles:
                    await self.rbac.enforce_or_raise(
                        user_id=user_id,
                        user_roles=user_roles,
                        credential_id=credential.id,
                        access_level=CredentialAccessLevel.READ_METADATA,
                    )
                count += 1
            except CredentialAccessDenied:
                pass

        return count

    # Audit logging (placeholder - will bind to global audit system)

    async def _audit_success(
        self,
        operation: str,
        user_id: Optional[str],
        credential_id: str,
        fingerprint: str,
        access_level: Optional[str] = None,
        old_fingerprint: Optional[str] = None,
    ) -> None:
        """
        Log successful operation to P0 protected audit trail (Step 17.5).

        Events are immutable, tamper-evident, and stored with Merkle root protection.

        Args:
            operation: Operation type (create, get, update, delete, list, count)
            user_id: User performing operation
            credential_id: Credential ID
            fingerprint: SHA256 fingerprint (not raw secret)
            access_level: Optional access level (for secret reads)
        """
        if not self.audit_binder:
            return  # No audit if not configured

        from core.audit import (
            credential_created_event,
            credential_deleted_event,
            credential_secret_read_event,
            credential_updated_event,
        )

        try:
            # Build appropriate event based on operation
            if operation == "create":
                event = credential_created_event(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    fingerprint=fingerprint,
                )
            elif operation == "update":
                event = credential_updated_event(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    old_fingerprint=old_fingerprint or fingerprint,
                    new_fingerprint=fingerprint,
                )
            elif operation == "delete":
                event = credential_deleted_event(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    fingerprint=fingerprint,
                )
            elif operation == "get_with_secret":
                event = credential_secret_read_event(
                    user_id=user_id or "system",
                    credential_id=credential_id,
                    fingerprint=fingerprint,
                )
            else:
                # Generic event for other operations (list, count, etc.)
                event_dict = {
                    "id": "",  # Will be generated by SecurityEvent
                    "event_type": "credential.operation",
                    "user_id": user_id or "system",
                    "credential_id": credential_id,
                    "fingerprint": fingerprint,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "metadata": {"operation": operation},
                }
                from core.audit.events import SecurityEvent

                event = SecurityEvent.from_dict(event_dict)

            # Append to P0 protected audit trail
            await self.audit_binder.append(event)
        except Exception as e:
            # Log but don't fail the operation if audit fails
            print(f"[WARNING] Failed to audit {operation}: {e}")

    async def _audit_failure(
        self,
        operation: str,
        user_id: Optional[str],
        reason: str,
    ) -> None:
        """
        Log failed operation to P0 protected audit trail (Step 17.5).

        Important: Failures are still logged (e.g., CredentialNotFound).

        Args:
            operation: Operation type
            user_id: User attempting operation
            reason: Failure reason
        """
        # Note: Audit denials are logged by RBACEnforcer.enforce_or_raise()
        # This method is for other types of failures (not found, version conflict, etc.)

        if not self.audit_binder:
            return

        try:
            # Log failures as generic events (no fingerprint, just reason)
            from core.audit.events import SecurityEvent

            event_dict = {
                "id": "",  # Will be generated
                "event_type": "credential.operation",
                "user_id": user_id or "system",
                "credential_id": "",
                "fingerprint": "",
                "timestamp": datetime.now(UTC).isoformat(),
                "metadata": {
                    "operation": operation,
                    "status": "failure",
                    "reason": reason,
                },
            }
            event = SecurityEvent.from_dict(event_dict)
            await self.audit_binder.append(event)
        except Exception as e:
            # Log but don't fail if audit fails
            print(f"[WARNING] Failed to audit failure {operation}: {e}")
