"""
Credential Management Module — Step 17.3-17.4

Provides capability-driven credential operations through OperationManager.
Includes full RBAC enforcement (Step 17.4).
No direct HTTP CRUD — all operations are routed through the operation system.
"""

from .module import CredentialModule
from .services import CredentialService
from .policy_enforcer import CredentialRBACEnforcer
from .schemas import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
    CredentialMetadata,
    CredentialWithSecretResponse,
    CredentialOperationResult,
)

__all__ = [
    "CredentialModule",
    "CredentialService",
    "CredentialRBACEnforcer",
    "CreateCredentialRequest",
    "UpdateCredentialRequest",
    "CredentialMetadata",
    "CredentialWithSecretResponse",
    "CredentialOperationResult",
]
