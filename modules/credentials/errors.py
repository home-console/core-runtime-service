"""
Credential Repository errors.

Custom exceptions for repository operations.
"""

from core.storage_layer import StorageSecurityError


class CredentialRepositoryError(StorageSecurityError):
    """Base exception for credential repository operations."""

    pass


class CredentialNotFound(CredentialRepositoryError):
    """Raised when credential is not found."""

    pass


class CredentialAlreadyExists(CredentialRepositoryError):
    """Raised when trying to create a credential with existing ID."""

    pass


class CredentialVersionConflict(CredentialRepositoryError):
    """Raised when optimistic lock version conflict detected on update."""

    def __init__(self, credential_id: str, expected: int, actual: int):
        self.credential_id = credential_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Version conflict for credential {credential_id}: "
            f"expected v{expected}, found v{actual}"
        )


class CredentialSecretLeakage(CredentialRepositoryError):
    """Raised when secret appears in metadata (security violation)."""

    pass


class CredentialAccessDenied(CredentialRepositoryError):
    """Raised when RBAC policy denies access to credential."""

    def __init__(
        self, user_id: str, credential_id: str, access_level: str, reason: str = ""
    ):
        self.user_id = user_id
        self.credential_id = credential_id
        self.access_level = access_level
        self.reason = reason
        super().__init__(
            f"Access denied for user {user_id} to credential {credential_id}: "
            f"{access_level} - {reason}"
        )
