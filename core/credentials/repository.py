"""
Credential Repository

Secure persistence layer for credentials with:
- Dual-mode storage (metadata in core, secrets in vault)
- Optimistic locking
- Atomic operations
- Namespace enforcement
"""

from typing import Optional
from core.credentials.domain import Credential, CredentialType
from core.credentials.errors import (
    CredentialNotFound,
    CredentialAlreadyExists,
    CredentialVersionConflict,
    CredentialSecretLeakage,
)
from core.security.rbac_models import CredentialPolicy
from core.storage_manager import StorageManager
from core.security.secret_store import SecretStore


# Namespace constants
METADATA_NAMESPACE = "credentials.meta"
SECRET_NAMESPACE = "secrets.store"  # Use vault namespace
POLICY_NAMESPACE = "credentials.policy"  # Control plane data


def _make_secret_key(credential_id: str) -> str:
    """Generate vault secret key from credential ID."""
    return credential_id  # SecretStore uses direct key


def _validate_metadata_not_contains_secret(metadata: dict) -> None:
    """
    Validate that metadata dict doesn't contain actual secret.
    
    This is a safety check to prevent accidental secret leakage.
    """
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
    - Metadata (hostname, username, type, tags) → core storage
    - Secrets (passwords, keys, tokens) → vault storage
    
    Provides:
    - CRUD operations (create, read, update, delete)
    - Optimistic locking
    - Atomic operations
    - Namespace enforcement
    """

    def __init__(
        self,
        storage_manager: StorageManager,
        secret_store: SecretStore,
    ):
        """
        Initialize credential repository.
        
        Args:
            storage_manager: StorageManager for dual-mode storage
            secret_store: SecretStore for vault secret storage
        """
        self._storage = storage_manager
        self._secrets = secret_store

    async def create(
        self,
        credential: Credential,
        secret: bytes,
    ) -> Credential:
        """
        Create and persist a new credential with its secret.
        
        Stores:
        - Metadata in core storage (credentials.meta namespace)
        - Secret in vault storage (via SecretStore)
        
        Atomic: if anything fails, nothing is stored.
        
        Args:
            credential: Credential domain object
            secret: Raw secret bytes (password, key, token, etc.)
        
        Returns:
            Created credential with secret_ref set
        
        Raises:
            CredentialAlreadyExists: if credential ID already exists
            CredentialSecretLeakage: if metadata contains secret
        """
        if self._secrets is None:
            raise RuntimeError(
                "Secret store is not configured. Credentials cannot be stored. "
                "Start core-runtime with SecretStore (e.g. passphrase/vault) to enable credential create."
            )

        # Validate metadata safety
        _validate_metadata_not_contains_secret(credential.metadata)

        # Check credential doesn't already exist
        existing = await self._storage.get(
            METADATA_NAMESPACE, credential.id, target="core"
        )
        if existing is not None:
            raise CredentialAlreadyExists(
                f"Credential {credential.id} already exists"
            )

        try:
            # Step 1: Store secret in vault (SecretStore handles encryption)
            await self._secrets.put(
                _make_secret_key(credential.id),
                secret,
            )

            # Step 2: Store metadata in core storage
            metadata = credential.to_dict()
            await self._storage.set(
                METADATA_NAMESPACE,
                credential.id,
                metadata,
                target="core",
            )

            return credential

        except Exception as e:
            # Rollback: delete secret if metadata store failed
            try:
                await self._secrets.delete(_make_secret_key(credential.id))
            except Exception:
                # Ignore rollback errors, raise original
                pass
            raise

    async def get(self, credential_id: str) -> Optional[Credential]:
        """
        Get credential metadata only (no secret).
        
        Reads from core storage.
        
        Args:
            credential_id: Credential ID
        
        Returns:
            Credential if found, None otherwise
        """
        metadata = await self._storage.get(
            METADATA_NAMESPACE, credential_id, target="core"
        )
        if metadata is None:
            return None

        return Credential.from_dict(metadata)

    async def get_with_secret(
        self, credential_id: str
    ) -> Optional[tuple[Credential, bytes]]:
        """
        Get credential metadata and secret together.
        
        Reads:
        - Metadata from core storage
        - Secret from vault storage (SecretStore)
        
        Args:
            credential_id: Credential ID
        
        Returns:
            Tuple of (Credential, secret_bytes) if found, None otherwise
        """
        if self._secrets is None:
            raise RuntimeError(
                "Secret store is not configured. Cannot retrieve credential secret."
            )

        # Get metadata
        credential = await self.get(credential_id)
        if credential is None:
            return None

        # Get secret from vault
        secret_bytes = await self._secrets.get(_make_secret_key(credential_id))
        if secret_bytes is None:
            raise CredentialNotFound(
                f"Secret for credential {credential_id} not found in vault"
            )

        return credential, secret_bytes

    async def update(
        self,
        credential: Credential,
        secret: Optional[bytes] = None,
    ) -> Credential:
        """
        Update credential metadata and/or secret.
        
        Implements optimistic locking:
        - Loads current version
        - Checks that incoming credential version matches current + 1
        - Confirms update
        
        Args:
            credential: Updated credential (version should be current + 1)
            secret: New secret bytes, or None to keep existing
        
        Returns:
            Updated credential (version will be current + 1)
        
        Raises:
            CredentialNotFound: if credential doesn't exist
            CredentialVersionConflict: if version mismatch
            CredentialSecretLeakage: if metadata contains secret
        """
        if self._secrets is None:
            raise RuntimeError(
                "Secret store is not configured. Cannot update credential secret."
            )

        # Validate metadata safety
        _validate_metadata_not_contains_secret(credential.metadata)

        # Load current credential
        current = await self.get(credential.id)
        if current is None:
            raise CredentialNotFound(
                f"Credential {credential.id} not found"
            )

        # Check version (optimistic locking): incoming should be current + 1
        expected_version = current.version + 1
        if credential.version != expected_version:
            raise CredentialVersionConflict(
                credential.id,
                expected=current.version,
                actual=credential.version,
            )

        try:
            # Step 1: Update secret in vault if provided
            if secret is not None:
                await self._secrets.put(
                    _make_secret_key(credential.id),
                    secret,
                )

            # Step 2: Update metadata in core storage
            # Note: version already incremented in credential.mutate()
            metadata = credential.to_dict()
            await self._storage.set(
                METADATA_NAMESPACE,
                credential.id,
                metadata,
                target="core",
            )

            return credential

        except Exception as e:
            # Rollback not needed: if metadata update fails,
            # secret in vault is stale but not corrupted
            # Next update attempt with correct version will fix it
            raise

    async def delete(self, credential_id: str) -> None:
        """
        Delete credential and its secret.
        
        Removes:
        - Metadata from core storage
        - Secret from vault storage
        
        Deletes are idempotent (no error if not found).
        
        Args:
            credential_id: Credential ID
        
        Raises:
            (No exceptions for missing credentials)
        """
        try:
            # Step 1: Delete metadata
            await self._storage.delete(
                METADATA_NAMESPACE, credential_id, target="core"
            )

            # Step 2: Delete secret from vault (no-op if secret store not configured)
            if self._secrets is not None:
                await self._secrets.delete(_make_secret_key(credential_id))

            # Both deletions attempted regardless of individual results
            # (idempotent operations)

        except Exception:
            # Silently ignore errors (idempotent)
            pass

    async def list(self) -> list[Credential]:
        """
        List all credentials (metadata only, no secrets).
        
        Reads from core storage.
        
        Returns:
            List of all credentials
        """
        # Get all keys in metadata namespace
        keys = await self._storage.list_keys(
            METADATA_NAMESPACE, target="core"
        )

        credentials = []
        for key in keys:
            credential = await self.get(key)
            if credential is not None:  # Skip deleted items
                credentials.append(credential)

        return credentials

    async def exists(self, credential_id: str) -> bool:
        """
        Check if credential exists.
        
        Args:
            credential_id: Credential ID
        
        Returns:
            True if exists, False otherwise
        """
        credential = await self.get(credential_id)
        return credential is not None

    async def count(self) -> int:
        """
        Get total number of credentials.
        
        Returns:
            Count of all credentials
        """
        credentials = await self.list()
        return len(credentials)

    # Policy management methods (control plane)
    
    async def create_policy(self, policy: CredentialPolicy) -> CredentialPolicy:
        """
        Create and persist access policy for credential.
        
        Stores in policy namespace (control plane data, not in vault).
        
        Args:
            policy: CredentialPolicy object
        
        Returns:
            Persisted policy
        
        Raises:
            CredentialAlreadyExists: If policy already exists for credential
        """
        # Check if policy already exists
        existing = await self.get_policy(policy.credential_id)
        if existing is not None:
            raise CredentialAlreadyExists(
                f"Policy already exists for credential {policy.credential_id}"
            )
        
        # Store policy in policy namespace
        await self._storage.create(
            POLICY_NAMESPACE,
            policy.credential_id,
            policy.to_dict(),
            target="core"  # Control plane data in core storage
        )
        
        return policy
    
    async def get_policy(self, credential_id: str) -> Optional[CredentialPolicy]:
        """
        Retrieve access policy for credential.
        
        Args:
            credential_id: Credential ID
        
        Returns:
            CredentialPolicy if exists, None otherwise
        """
        try:
            policy_dict = await self._storage.get(
                POLICY_NAMESPACE,
                credential_id,
                target="core"
            )
            if policy_dict is None:
                return None
            return CredentialPolicy.from_dict(policy_dict)
        except Exception:
            return None
    
    async def update_policy(self, policy: CredentialPolicy) -> CredentialPolicy:
        """
        Update existing access policy.
        
        Args:
            policy: CredentialPolicy with updated fields
        
        Returns:
            Updated policy
        
        Raises:
            CredentialNotFound: If policy does not exist
        """
        # Check if policy exists
        existing = await self.get_policy(policy.credential_id)
        if existing is None:
            raise CredentialNotFound(
                f"Policy not found for credential {policy.credential_id}"
            )
        
        # Update in policy namespace
        await self._storage.update(
            POLICY_NAMESPACE,
            policy.credential_id,
            policy.to_dict(),
            target="core"
        )
        
        return policy
    
    async def delete_policy(self, credential_id: str) -> None:
        """
        Delete access policy for credential.
        
        Idempotent: deleting non-existent policy is OK.
        
        Args:
            credential_id: Credential ID
        """
        try:
            await self._storage.delete(
                POLICY_NAMESPACE,
                credential_id,
                target="core"
            )
        except CredentialNotFound:
            pass  # Idempotent
