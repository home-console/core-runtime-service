"""
Credential Repository

Secure persistence layer for credentials with:
- Dual-mode storage (metadata in core, secrets in vault)
- Optimistic locking
- Atomic operations
- Namespace enforcement
"""

from typing import Optional

from modules.security import CredentialPolicy, SecretStore
from modules.credentials.domain import Credential
from modules.credentials.errors import (
    CredentialAlreadyExists,
    CredentialNotFound,
    CredentialSecretLeakage,
    CredentialVersionConflict,
)
from modules.storage.manager import StorageManager

METADATA_NAMESPACE = "credentials.meta"
SECRET_NAMESPACE = "secrets.store"
POLICY_NAMESPACE = "credentials.policy"


def _make_secret_key(credential_id: str) -> str:
    return credential_id


def _validate_metadata_not_contains_secret(metadata: dict) -> None:
    secret_keywords = {"password", "secret", "key", "token", "credential"}

    for field_name in metadata.keys():
        field_lower = field_name.lower()
        if any(keyword in field_lower for keyword in secret_keywords):
            raise CredentialSecretLeakage(
                f"Metadata contains suspected secret field: {field_name}"
            )


class CredentialRepository:
    """
    Secure repository for credential storage and retrieval.

    Separates:
    - Metadata (hostname, username, type, tags) -> core storage
    - Secrets (passwords, keys, tokens) -> vault storage
    """

    def __init__(self, storage_manager: StorageManager, secret_store: SecretStore):
        self._storage = storage_manager
        self._secrets = secret_store

    async def create(self, credential: Credential, secret: bytes) -> Credential:
        if self._secrets is None:
            raise RuntimeError(
                "Secret store is not configured. Credentials cannot be stored. "
                "Start core-runtime with SecretStore (e.g. passphrase/vault) to enable credential create."
            )

        _validate_metadata_not_contains_secret(credential.metadata)

        existing = await self._storage.get(
            METADATA_NAMESPACE, credential.id, target="core"
        )
        if existing is not None:
            raise CredentialAlreadyExists(f"Credential {credential.id} already exists")

        try:
            await self._secrets.put(_make_secret_key(credential.id), secret)
            metadata = credential.to_dict()
            await self._storage.set(
                METADATA_NAMESPACE, credential.id, metadata, target="core"
            )
            return credential
        except Exception:
            try:
                await self._secrets.delete(_make_secret_key(credential.id))
            except Exception:
                pass
            raise

    async def get(self, credential_id: str) -> Optional[Credential]:
        metadata = await self._storage.get(
            METADATA_NAMESPACE, credential_id, target="core"
        )
        if metadata is None:
            return None
        return Credential.from_dict(metadata)

    async def get_with_secret(
        self, credential_id: str
    ) -> Optional[tuple[Credential, bytes]]:
        if self._secrets is None:
            raise RuntimeError(
                "Secret store is not configured. Cannot retrieve credential secret."
            )

        credential = await self.get(credential_id)
        if credential is None:
            return None

        secret_bytes = await self._secrets.get(_make_secret_key(credential_id))
        if secret_bytes is None:
            raise CredentialNotFound(
                f"Secret for credential {credential_id} not found in vault"
            )

        return credential, secret_bytes

    async def update(
        self, credential: Credential, secret: Optional[bytes] = None
    ) -> Credential:
        if self._secrets is None:
            raise RuntimeError(
                "Secret store is not configured. Cannot update credential secret."
            )

        _validate_metadata_not_contains_secret(credential.metadata)

        current = await self.get(credential.id)
        if current is None:
            raise CredentialNotFound(f"Credential {credential.id} not found")

        expected_version = current.version + 1
        if credential.version != expected_version:
            raise CredentialVersionConflict(
                credential.id,
                expected=current.version,
                actual=credential.version,
            )

        try:
            if secret is not None:
                await self._secrets.put(_make_secret_key(credential.id), secret)

            metadata = credential.to_dict()
            await self._storage.set(
                METADATA_NAMESPACE, credential.id, metadata, target="core"
            )
            return credential
        except Exception:
            raise

    async def delete(self, credential_id: str) -> None:
        try:
            await self._storage.delete(METADATA_NAMESPACE, credential_id, target="core")
            if self._secrets is not None:
                await self._secrets.delete(_make_secret_key(credential_id))
        except Exception:
            pass

    async def list(self) -> list[Credential]:
        keys = await self._storage.list_keys(METADATA_NAMESPACE, target="core")
        credentials = []
        for key in keys:
            credential = await self.get(key)
            if credential is not None:
                credentials.append(credential)
        return credentials

    async def exists(self, credential_id: str) -> bool:
        credential = await self.get(credential_id)
        return credential is not None

    async def count(self) -> int:
        credentials = await self.list()
        return len(credentials)

    async def create_policy(self, policy: CredentialPolicy) -> CredentialPolicy:
        existing = await self.get_policy(policy.credential_id)
        if existing is not None:
            raise CredentialAlreadyExists(
                f"Policy already exists for credential {policy.credential_id}"
            )

        if hasattr(self._storage, "create"):
            await self._storage.create(
                POLICY_NAMESPACE, policy.credential_id, policy.to_dict(), target="core"
            )
        else:
            await self._storage.set(
                POLICY_NAMESPACE, policy.credential_id, policy.to_dict(), target="core"
            )
        return policy

    async def get_policy(self, credential_id: str) -> Optional[CredentialPolicy]:
        try:
            policy_dict = await self._storage.get(
                POLICY_NAMESPACE, credential_id, target="core"
            )
            if policy_dict is None:
                return None
            return CredentialPolicy.from_dict(policy_dict)
        except Exception:
            return None

    async def update_policy(self, policy: CredentialPolicy) -> CredentialPolicy:
        existing = await self.get_policy(policy.credential_id)
        if existing is None:
            raise CredentialNotFound(
                f"Policy not found for credential {policy.credential_id}"
            )

        if hasattr(self._storage, "update"):
            await self._storage.update(
                POLICY_NAMESPACE, policy.credential_id, policy.to_dict(), target="core"
            )
        else:
            await self._storage.set(
                POLICY_NAMESPACE, policy.credential_id, policy.to_dict(), target="core"
            )
        return policy

    async def delete_policy(self, credential_id: str) -> None:
        try:
            await self._storage.delete(POLICY_NAMESPACE, credential_id, target="core")
        except CredentialNotFound:
            pass
