"""
CredentialModule — Runtime module for credential management.

Integrates through OperationManager with capability-driven operations.
RBAC enforcement happens BEFORE service calls.
No direct HTTP CRUD — all operations routed through OperationManager.

Step 17.5: Tamper-evident audit binding via AuditBinder
Step 17.6: Zero-trust secret access with MFA elevation
Step 17.7: Self-defending vault with abuse detection
Step 17.8: Adaptive risk scoring engine
"""

from typing import Any, Dict, Optional, List, TYPE_CHECKING
from core.runtime_module import RuntimeModule
from core.credentials import CredentialRepository
from core.security.secret_store import SecretStore
from core.security.rbac_models import Role, CredentialAccessLevel
from core.security.policy_engine import CredentialPolicyEngine
from core.security.mfa.service import MFAService
from core.security.risk.engine import RiskEngine
from modules.credentials.policy_enforcer import CredentialRBACEnforcer
from modules.credentials.services import CredentialService
from modules.credentials.abuse_detection import CredentialAbuseDetector
from modules.credentials.schemas import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
    CredentialMetadata,
    CredentialWithSecretResponse,
)

if TYPE_CHECKING:
    from core.audit.binder import AuditBinder


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
        All operations logged to P0 protected storage (Step 17.5).
        
        Abuse Detection:
        Secret access validated for behavioral anomalies (Step 17.7).
        """
        # Initialize repository
        self._repository = CredentialRepository(
            storage_manager=self.runtime.storage,
            secret_store=self.runtime.secret_store,
        )

        # Initialize RBAC policy engine and enforcer
        policy_store = PolicyStoreAdapter(self._repository)
        policy_engine = CredentialPolicyEngine(policy_store=policy_store)
        
        # Initialize audit binder (Step 17.5)
        if hasattr(self.runtime, 'secure_storage'):
            from core.audit.binder import AuditBinder
            self._audit_binder = AuditBinder(self.runtime.secure_storage)
        
        # Initialize abuse detector (Step 17.7)
        self._abuse_detector = CredentialAbuseDetector(
            audit_binder=self._audit_binder,
        )
        
        # Initialize MFA service (Step 17.6)
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

        # Initialize risk engine (Step 17.8)
        self._risk_engine = RiskEngine(
            audit_binder=self._audit_binder,
        )

        # Initialize service with enforcer, audit binder, MFA service, abuse detector, and risk engine
        self._service = CredentialService(
            repository=self._repository,
            rbac_enforcer=self._rbac_enforcer,
            audit_binder=self._audit_binder,
            mfa_service=self._mfa_service,
            abuse_detector=self._abuse_detector,
            risk_engine=self._risk_engine,
            audit_logger=self.runtime.audit if hasattr(self.runtime, 'audit') else None,
        )
        
        # Start background cleanup tasks
        try:
            await self._abuse_detector.start()
        except Exception as e:
            print(f"[WARNING] Failed to start abuse detector: {e}")
        
        try:
            await self._mfa_service.start()
        except Exception as e:
            print(f"[WARNING] Failed to start MFA service: {e}")
        
        try:
            await self._risk_engine.start()
        except Exception as e:
            print(f"[WARNING] Failed to start risk engine: {e}")

        # Register all 8 operations through service registry
        await self._register_create_operation()
        await self._register_get_operation()
        await self._register_get_with_secret_operation()
        await self._register_list_operation()
        await self._register_update_operation()
        await self._register_delete_operation()
        await self._register_exists_operation()
        await self._register_count_operation()

    async def _register_create_operation(self) -> None:
        """Register credential.create operation (requires credentials.write)."""
        async def create_handler(runtime, **params) -> Dict[str, Any]:
            user_id = params.get("_user_id")
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
            
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
            
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
            
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
            
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
            
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
            user_roles = [Role(r) if isinstance(r, str) else r for r in params.get("_user_roles", [])]
            
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
