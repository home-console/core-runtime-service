"""
Credential domain model module.

Clean, isolated domain objects with no storage dependencies.
"""

from core.credentials.domain import (
    CredentialType,
    Credential,
    CredentialValidationError,
)
from core.credentials.errors import (
    CredentialRepositoryError,
    CredentialNotFound,
    CredentialAlreadyExists,
    CredentialVersionConflict,
    CredentialSecretLeakage,
    CredentialAccessDenied,
)
from core.credentials.repository import (
    CredentialRepository,
)

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
]
