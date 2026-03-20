"""Credential Management Module — Step 17.3-17.4.

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
from .policy_enforcer import CredentialRBACEnforcer
from .schemas import (
    CreateCredentialRequest,
    CredentialMetadata,
    CredentialOperationResult,
    CredentialWithSecretResponse,
    UpdateCredentialRequest,
)
from .services import CredentialService


class CredentialsModule(CredentialModule):
    """
    Backward-compatible alias for CredentialModule.

    ModuleManager ищет класс `CredentialsModule` в пакете `modules.credentials`
    для ModuleSpec(name="credentials"), поэтому этот alias позволяет загрузить
    модуль `credentials` без изменения bootstrap.
    """


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
    "CredentialsModule",
    "CredentialService",
    "CredentialRBACEnforcer",
    "CreateCredentialRequest",
    "UpdateCredentialRequest",
    "CredentialMetadata",
    "CredentialWithSecretResponse",
    "CredentialOperationResult",
]
