"""
CredentialModule — Runtime module for credential management.

Integrates through OperationManager with capability-driven operations.
RBAC enforcement happens BEFORE service calls.
No direct HTTP CRUD — all operations routed through OperationManager.

Tamper-evident audit binding via AuditBinder
Zero-trust secret access with MFA elevation
Self-defending vault with abuse detection
Adaptive risk scoring engine
Trust restoration engine
Unified security decision orchestrator
"""

import base64
import json
import logging
import secrets as secrets_module
from typing import TYPE_CHECKING, Any, Dict, Optional

from core.runtime.runtime_module import RuntimeModule
from modules.security import (
    MFAService,
    CredentialPolicyEngine,
    Role,
    RiskEngine,
    TrustEngine,
    TrustConfigs,
)
from modules.security.mfa.methods import TOTPMethod
from modules.security.mfa.totp import verify_totp
from modules.credentials import CredentialRepository
from modules.credentials.abuse_detection import CredentialAbuseDetector
from modules.credentials.policy_enforcer import CredentialRBACEnforcer
from modules.credentials.schemas import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
)
from modules.credentials.security_orchestrator import CredentialSecurityOrchestrator
from modules.credentials.services import CredentialService

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder


logger = logging.getLogger(__name__)


class PolicyStoreAdapter:
    """Adapter implementing PolicyStore protocol for repository."""

    def __init__(self, repository: CredentialRepository):
        self.repo = repository

    async def get_policy(self, credential_id: str):
        return await self.repo.get_policy(credential_id)


class CredentialModule(RuntimeModule):
    """
    Credential management module with full RBAC enforcement and audit binding.

    Provides 8 operations (credential.create, get, get_with_secret, list,
    update, delete, exists, count) through OperationManager.

    All operations:
    - Are capability-driven (strict authorization)
    - Have RBAC enforcement BEFORE service call
    - Support tamper-evident audit logging (via AuditBinder)
    - Enforce rate limiting
    - Use immutable optimistic locking patterns

    Security Stack (-17.10):
    - -5: RBAC enforcement
    - MFA elevation
    - Abuse detection
    - Risk scoring
    - Trust restoration
    - Unified orchestrator (all 5 layers)
    """

    def __init__(self, runtime: Any):
        """
        Initialize credential module.

        Args:
            runtime: CoreRuntime instance
        """
        super().__init__(runtime)
        self._service: Optional[CredentialService] = None
        self._rbac_enforcer: Optional[CredentialRBACEnforcer] = None
        self._repository: Optional[CredentialRepository] = None
        self._audit_binder: Optional["AuditBinder"] = None
        self._mfa_service: Optional[MFAService] = None
        self._abuse_detector: Optional[CredentialAbuseDetector] = None
        self._risk_engine: Optional[RiskEngine] = None
        self._trust_engine: Optional[TrustEngine] = None
        self._security_orchestrator: Optional[CredentialSecurityOrchestrator] = None

    @property
    def name(self) -> str:
        """Unique module name."""
        return "credentials"

    async def register(self) -> None:
        """
        Register credential operations with OperationManager and ServiceRegistry.

        Creates 8 operations:
        - credential.create (POST)
        - credential.get (GET metadata)
        - credential.get_with_secret (GET with secret - elevated)
        - credential.list (GET all)
        - credential.update (PUT - optimistic locking)
        - credential.delete (DELETE)
        - credential.exists (GET check)
        - credential.count (GET count)

        RBAC Enforcement:
        Each operation checks policies BEFORE calling service layer.

        Audit:
        All operations logged to P0 protected storage ().

        Abuse Detection:
        Secret access validated for behavioral anomalies ().
        """
        if self.runtime is None:
            raise RuntimeError("CredentialsModule requires full runtime (not RuntimeContext)")

        # Initialize repository (StorageManager для core/vault, иначе только secret_store)
        sm = getattr(self.runtime, "storage_manager", None)
        if sm is None:
            sm = getattr(self.runtime, "storage", None)

        self._repository = CredentialRepository(
            storage_manager=sm,
            secret_store=self.runtime.secret_store,
        )

        # Initialize RBAC policy engine and enforcer
        policy_store = PolicyStoreAdapter(self._repository)
        policy_engine = CredentialPolicyEngine(policy_store=policy_store)

        # Initialize audit binder ()
        if hasattr(self.runtime, "secure_storage"):
            from core.audit.binder import AuditBinder

            self._audit_binder = AuditBinder(self.runtime.secure_storage)

        # Initialize abuse detector ()
        self._abuse_detector = CredentialAbuseDetector(
            audit_binder=self._audit_binder,
        )

        # Initialize MFA service ()
        self._mfa_service = MFAService(
            secret_store=self.runtime.secret_store,
            audit_binder=self._audit_binder,
            abuse_detector=self._abuse_detector,
            elevation_ttl_seconds=90,
            max_failed_attempts=5,
            lockout_seconds=300,
        )

        # Create enforcer with audit binder and elevation session manager
        self._rbac_enforcer = CredentialRBACEnforcer(
            policy_engine=policy_engine,
            audit_binder=self._audit_binder,
            elevation_session_manager=self._mfa_service.elevation_session_manager,
        )

        # Initialize risk engine ()
        self._risk_engine = RiskEngine(
            audit_binder=self._audit_binder,
        )

        # Initialize trust engine ()
        self._trust_engine = TrustEngine(
            config=TrustConfigs.BALANCED,
            audit_binder=self._audit_binder,
        )

        # Initialize security decision orchestrator ()
        # Coordinates all 5 security layers into unified decision path
        self._security_orchestrator = CredentialSecurityOrchestrator(
            rbac_enforcer=self._rbac_enforcer,
            mfa_service=self._mfa_service,
            abuse_detector=self._abuse_detector,
            risk_engine=self._risk_engine,
            trust_engine=self._trust_engine,
            audit_binder=self._audit_binder,
        )

        # Initialize service with orchestrator and all security components
        self._service = CredentialService(
            repository=self._repository,
            rbac_enforcer=self._rbac_enforcer,
            audit_binder=self._audit_binder,
            mfa_service=self._mfa_service,
            abuse_detector=self._abuse_detector,
            risk_engine=self._risk_engine,
            trust_engine=self._trust_engine,
            security_orchestrator=self._security_orchestrator,
            audit_logger=self.runtime.audit if hasattr(self.runtime, "audit") else None,
        )

        # Start critical security components in fail-closed mode.
        await self._start_security_components_or_fail()

        # Register all 8 operations through service registry
        await self._register_create_operation()
        await self._register_get_operation()
        await self._register_get_with_secret_operation()
        await self._register_list_operation()
        await self._register_update_operation()
        await self._register_delete_operation()
        await self._register_exists_operation()
        await self._register_count_operation()
        await self._register_mfa_operations()

    async def _register_create_operation(self) -> None:
        """Register credential.create operation (requires credentials.write)."""

        async def create_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]
            request_data = params.get("credential", {})
            secret_bytes = params.get("secret")

            # Validate inputs
            if not request_data or not secret_bytes:
                raise ValueError("credential and secret required")

            # Create and validate request object
            request = CreateCredentialRequest(**request_data)

            # Call service (RBAC enforcement happens inside service)
            metadata = await self._service.create(
                request=request,
                secret=secret_bytes,
                user_id=user_id,
                user_roles=user_roles,
            )

            return metadata.to_dict()

        await self.register_service(
            "credential.create",
            lambda runtime, **kw: create_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_get_operation(self) -> None:
        """Register credential.get operation (requires credentials.read)."""

        async def get_handler(runtime, **params) -> Dict[str, Any]:
            credential_id = params.get("credential_id")
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]

            if not credential_id:
                raise ValueError("credential_id required")

            # RBAC enforcement happens in service
            metadata = await self._service.get(
                credential_id=credential_id,
                user_id=user_id,
                user_roles=user_roles,
            )

            return metadata.to_dict()

        await self.register_service(
            "credential.get",
            lambda runtime, **kw: get_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_get_with_secret_operation(self) -> None:
        """Register credential.get_with_secret operation (requires credentials.secret.read - ELEVATED)."""

        async def get_with_secret_handler(runtime, **params) -> Dict[str, Any]:
            credential_id = params.get("credential_id")
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]

            if not credential_id:
                raise ValueError("credential_id required")

            # RBAC enforcement for elevated access (inside service)
            response = await self._service.get_with_secret(
                credential_id=credential_id,
                user_id=user_id,
                user_roles=user_roles,
            )

            return {
                "metadata": response.metadata.to_dict(),
                "secret": response.secret.hex(),  # Encode as hex for JSON safety
            }

        await self.register_service(
            "credential.get_with_secret",
            lambda runtime, **kw: get_with_secret_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_list_operation(self) -> None:
        """Register credential.list operation (requires credentials.read)."""

        async def list_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]

            # RBAC filtering happens in service
            credentials = await self._service.list(
                user_id=user_id,
                user_roles=user_roles,
            )

            return {
                "credentials": [c.to_dict() for c in credentials],
                "count": len(credentials),
            }

        await self.register_service(
            "credential.list",
            lambda runtime, **kw: list_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_update_operation(self) -> None:
        """Register credential.update operation (requires credentials.write + optimistic locking)."""

        async def update_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]
            request_data = params.get("credential", {})
            secret_bytes = params.get("secret")  # Optional: new secret

            if not request_data:
                raise ValueError("credential required")

            # Create and validate request object
            request = UpdateCredentialRequest(**request_data)

            # RBAC enforcement happens in service
            metadata = await self._service.update(
                request=request,
                secret=secret_bytes,
                user_id=user_id,
                user_roles=user_roles,
            )

            return metadata.to_dict()

        await self.register_service(
            "credential.update",
            lambda runtime, **kw: update_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_delete_operation(self) -> None:
        """Register credential.delete operation (requires credentials.delete - ADMIN only)."""

        async def delete_handler(runtime, **params) -> Dict[str, Any]:
            credential_id = params.get("credential_id")
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]

            if not credential_id:
                raise ValueError("credential_id required")

            # RBAC enforcement happens in service
            await self._service.delete(
                credential_id=credential_id,
                user_id=user_id,
                user_roles=user_roles,
            )

            return {"deleted": True}

        await self.register_service(
            "credential.delete",
            lambda runtime, **kw: delete_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_exists_operation(self) -> None:
        """Register credential.exists operation (requires credentials.read)."""

        async def exists_handler(runtime, **params) -> Dict[str, Any]:
            credential_id = params.get("credential_id")
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]

            if not credential_id:
                raise ValueError("credential_id required")

            # RBAC enforcement happens in service
            exists = await self._service.exists(
                credential_id=credential_id,
                user_id=user_id,
                user_roles=user_roles,
            )

            return {"exists": exists}

        await self.register_service(
            "credential.exists",
            lambda runtime, **kw: exists_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_count_operation(self) -> None:
        """Register credential.count operation (requires credentials.read)."""

        async def count_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            user_roles = [
                Role(r) if isinstance(r, str) else r
                for r in params.get("_user_roles", [])
            ]

            # RBAC filtering happens in service
            count = await self._service.count(
                user_id=user_id,
                user_roles=user_roles,
            )

            return {"count": count}

        await self.register_service(
            "credential.count",
            lambda runtime, **kw: count_handler(runtime, **kw),
            resource="credential",
        )

    async def _register_mfa_operations(self) -> None:
        """Register credential.mfa.* operations (TOTP enroll/elevate, opt-in step-up)."""

        async def status_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            enabled = await self._mfa_service.is_totp_configured(user_id)
            return {"enabled": enabled}

        async def enroll_start_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            secret = base64.b32encode(secrets_module.token_bytes(20)).decode("ascii")
            otpauth_url = (
                f"otpauth://totp/HomeConsole:{user_id}"
                f"?secret={secret}&issuer=HomeConsole&digits=6&period=30"
            )
            return {"secret": secret, "otpauth_url": otpauth_url}

        async def enroll_confirm_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            secret = params.get("secret")
            code = params.get("code")

            if not secret or not code:
                raise ValueError("secret and code required")

            if not verify_totp(secret, code, window=1):
                return {"success": False, "reason": "invalid_code"}

            payload = json.dumps({"secret": secret, "method": "totp"}).encode("utf-8")
            await self.runtime.secret_store.put(f"{TOTPMethod.NAMESPACE}.{user_id}", payload)

            if self._audit_binder:
                from core.audit.events import credential_mfa_enrolled_event

                await self._audit_binder.append(
                    credential_mfa_enrolled_event(user_id=user_id, mfa_method="totp")
                )

            return {"success": True}

        async def disable_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            code = params.get("code")

            if not code:
                raise ValueError("code required")

            if not await self._mfa_service.is_totp_configured(user_id):
                return {"success": False, "reason": "mfa_not_configured"}

            result = await self._mfa_service.verify_totp_code(user_id, code)
            if not result.success:
                return {"success": False, "reason": result.reason}

            await self.runtime.secret_store.delete(f"{TOTPMethod.NAMESPACE}.{user_id}")

            if self._audit_binder:
                from core.audit.events import credential_mfa_disabled_event

                await self._audit_binder.append(
                    credential_mfa_disabled_event(user_id=user_id, mfa_method="totp")
                )

            return {"success": True}

        async def elevate_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            code = params.get("code")
            credential_id = params.get("credential_id", "")

            if not code:
                raise ValueError("code required")

            return await self._mfa_service.verify_and_elevate(
                user_id=user_id,
                mfa_method="totp",
                proof={"code": code},
                credential_id=credential_id,
            )

        await self.register_service(
            "credential.mfa.status",
            lambda runtime, **kw: status_handler(runtime, **kw),
        )
        await self.register_service(
            "credential.mfa.enroll_start",
            lambda runtime, **kw: enroll_start_handler(runtime, **kw),
        )
        await self.register_service(
            "credential.mfa.enroll_confirm",
            lambda runtime, **kw: enroll_confirm_handler(runtime, **kw),
        )
        await self.register_service(
            "credential.mfa.disable",
            lambda runtime, **kw: disable_handler(runtime, **kw),
        )
        await self.register_service(
            "credential.mfa.elevate",
            lambda runtime, **kw: elevate_handler(runtime, **kw),
        )

    async def _start_security_components_or_fail(self) -> None:
        """
        Start background security components in fail-closed mode.

        If any critical component fails to start, registration fails to avoid
        running credentials in degraded security mode.
        """
        started: list[Any] = []
        failures: list[str] = []

        startup_plan = [
            ("abuse_detector", self._abuse_detector, "start", True),
            ("mfa_service", self._mfa_service, "start", True),
            ("risk_engine", self._risk_engine, "start", True),
            ("trust_engine", self._trust_engine, "start", False),
        ]

        for name, instance, method_name, is_async in startup_plan:
            if instance is None:
                failures.append(f"{name}: not initialized")
                break
            try:
                method = getattr(instance, method_name)
                if is_async:
                    await method()
                else:
                    method()
                started.append(instance)
            except Exception as e:
                logger.warning("module._start_security_components_or_fail: unexpected error: %s", e, exc_info=True)
                failures.append(f"{name}: {e}")
                # Fail-closed: don't start later components after first failure.
                break

        if not failures:
            return

        for instance in reversed(started):
            stop_method = getattr(instance, "stop", None)
            if stop_method is None:
                continue
            try:
                result = stop_method()
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.warning(
                    "credentials security rollback failed for %s: %s",
                    type(instance).__name__,
                    e,
                )

        raise RuntimeError(
            "Failed to start credential security components: "
            + "; ".join(failures)
        )
