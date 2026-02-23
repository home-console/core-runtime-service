"""
Credential Management Module — Step 17.3-17.4

Provides capability-driven credential operations through OperationManager.
Includes full RBAC enforcement (Step 17.4).
No direct HTTP CRUD — all operations are routed through the operation system.

Этот пакет экспортирует два класса RuntimeModule:
- CredentialModule — основная реализация
- CredentialsModule — alias для ModuleManager (module name "credentials")
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


class CredentialsModule(CredentialModule):
    """
    Backward-compatible alias for CredentialModule.

    ModuleManager ищет класс `CredentialsModule` в пакете `modules.credentials`
    для ModuleSpec(name="credentials"), поэтому этот alias позволяет загрузить
    модуль `credentials` без изменения bootstrap.
    """


__all__ = [
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
