"""Credential Management Module — -17.4.

Provides capability-driven credential operations through OperationManager.
This package is now the canonical home for credential domain code.
"""

from .domain import Credential, CredentialType, CredentialValidationError
from .errors import (
    CredentialRepositoryError,
    CredentialNotFound,
    CredentialAlreadyExists,
    CredentialVersionConflict,
    CredentialSecretLeakage,
    CredentialAccessDenied,
)
from .repository import CredentialRepository

from .module import CredentialModule

# Explicit entrypoint for module discovery
__runtime_module_class__ = CredentialModule
from .policy_enforcer import CredentialRBACEnforcer
from .schemas import (
    CreateCredentialRequest,
    CredentialMetadata,
    CredentialOperationResult,
    CredentialWithSecretResponse,
    UpdateCredentialRequest,
)
from .services import CredentialService


__all__ = [
    "Credential",
    "CredentialType",
    "CredentialValidationError",
    "CredentialRepository",
    "CredentialRepositoryError",
    "CredentialNotFound",
    "CredentialAlreadyExists",
    "CredentialVersionConflict",
    "CredentialSecretLeakage",
    "CredentialAccessDenied",
    "CredentialModule",
    "CredentialService",
    "CredentialRBACEnforcer",
    "CreateCredentialRequest",
    "UpdateCredentialRequest",
    "CredentialMetadata",
    "CredentialWithSecretResponse",
    "CredentialOperationResult",
]
