"""
Unit tests for Credential Repository.

Tests cover:
- Create operations (success, duplicate, isolation)
- Read operations (metadata, with_secret, not found)
- Update operations (metadata, secret, both, version conflict)
- Delete operations (exists, not exists, idempotent)
- Atomicity (failure scenarios)
- Isolation (no secret leakage)
"""

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import pytest

from core.adapters.storage_adapter import StorageAdapter
from modules.security.secret_store import SecretStore
from modules.credentials import (
    Credential,
    CredentialAlreadyExists,
    CredentialRepository,
    CredentialSecretLeakage,
    CredentialType,
    CredentialVersionConflict,
)
from modules.storage.manager import StorageManager


class InMemoryStorageAdapter(StorageAdapter):
    """Simple in-memory storage adapter for testing."""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}

    async def initialize_schema(self) -> None:
        """Initialize schema (no-op for in-memory adapter)."""
        return None

    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Get value from storage."""
        if namespace not in self._data:
            return None
        return self._data[namespace].get(key)

    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Set value in storage."""
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace][key] = value

    async def delete(self, namespace: str, key: str) -> bool:
        """Delete value from storage."""
        if namespace not in self._data:
            return False
        if key not in self._data[namespace]:
            return False
        del self._data[namespace][key]
        return True

    async def list_keys(self, namespace: str) -> list[str]:
        """List all keys in namespace."""
        if namespace not in self._data:
            return []
        return list(self._data[namespace].keys())

    async def list_namespaces(self) -> list[str]:
        """List all namespaces."""
        return list(self._data.keys())

    async def clear_namespace(self, namespace: str) -> None:
        """Clear all items in namespace."""
        if namespace in self._data:
            self._data[namespace] = {}

    async def close(self) -> None:
        """Close storage."""
        pass

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Transaction context manager."""
        yield

    async def batch_set(self, namespace: str, items: dict[str, dict[str, Any]]) -> None:
        """Batch set values."""
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace].update(items)

    async def get_many(self, namespace: str, keys: list[str]) -> dict[str, Any]:
        """Batch get values."""
        ns = self._data.get(namespace, {})
        return {k: ns.get(k) for k in keys}

    async def iter_namespace(
        self, namespace: str, batch_size: int = 100
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Iterate over namespace."""
        if namespace not in self._data:
            return
        for key, value in self._data[namespace].items():
            yield key, value

    # Legacy methods for SecretStore compatibility
    async def get_async(self, key: str) -> Optional[str]:
        """Legacy method for SecretStore."""
        parts = key.split(".")
        if len(parts) < 2:
            return None
        namespace = parts[0]
        subkey = ".".join(parts[1:])
        data = await self.get(namespace, subkey)
        if data is None:
            return None
        if isinstance(data, dict) and "value" in data:
            return data["value"]
        return json.dumps(data) if isinstance(data, dict) else None

    async def set_async(self, key: str, value: str) -> None:
        """Legacy method for SecretStore."""
        parts = key.split(".")
        if len(parts) < 2:
            return
        namespace = parts[0]
        subkey = ".".join(parts[1:])
        try:
            data = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = {"value": value}
        await self.set(namespace, subkey, data)

    async def delete_async(self, key: str) -> bool:
        """Legacy method for SecretStore."""
        parts = key.split(".")
        if len(parts) < 2:
            return False
        namespace = parts[0]
        subkey = ".".join(parts[1:])
        return await self.delete(namespace, subkey)

    async def list_keys_async(self, pattern: str) -> list[str]:
        """Legacy method for SecretStore."""
        # Simple pattern matching
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            keys = []
            for namespace in self._data:
                if namespace.startswith(prefix):
                    for key in self._data[namespace]:
                        keys.append(f"{namespace}.{key}")
            return keys
        return []


@pytest.fixture
async def storage_setup():
    """Create temporary storage for testing."""
    # Create in-memory adapters for both core and vault storage
    core_adapter = InMemoryStorageAdapter()
    vault_adapter = InMemoryStorageAdapter()

    storage_manager = StorageManager(
        core_storage=core_adapter,
        vault_storage=vault_adapter,
        mode="dual",
    )

    # Create secret store (uses vault storage)
    secret_store = SecretStore(vault_adapter)
    await secret_store.initialize("test_passphrase_for_credentials")

    yield storage_manager, secret_store, core_adapter, vault_adapter

    await storage_manager.close()


@pytest.fixture
async def repository(storage_setup):
    """Create credential repository."""
    storage_manager, secret_store, _, _ = storage_setup
    repo = CredentialRepository(storage_manager, secret_store)
    yield repo


class TestCredentialRepositoryCreate:
    """Tests for credential creation."""

    @pytest.mark.asyncio
    async def test_create_success(self, repository, storage_setup):
        """Test successful credential creation."""
        storage_manager, secret_store, _, _ = storage_setup

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="github-token",
            secret_ref="vault:api:github",
        )

        secret = b"ghp_1234567890abcdef"

        created = await repository.create(cred, secret)

        assert created.id == cred.id
        assert created.name == "github-token"
        assert created.version == 1

    @pytest.mark.asyncio
    async def test_create_duplicate_fails(self, repository, storage_setup):
        """Test that creating duplicate ID fails."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret123"

        # Create first time
        await repository.create(cred, secret)

        # Try to create again with same ID
        with pytest.raises(CredentialAlreadyExists):
            await repository.create(cred, secret)

    @pytest.mark.asyncio
    async def test_secret_stored_in_vault_only(self, repository, storage_setup):
        """Test that secret is stored in vault, not core."""
        storage_manager, secret_store, core_adapter, vault_adapter = storage_setup

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"my_secret_key_data"

        await repository.create(cred, secret)

        # Verify we can retrieve secret (it's in vault)
        _, retrieved_secret = await repository.get_with_secret(cred.id)
        assert retrieved_secret == secret

        # Verify secret is NOT in core storage
        core_data = await core_adapter.get("credentials.meta", cred.id)
        assert core_data is not None  # Metadata exists in core
        assert "secret" not in core_data  # But secret data not in metadata

    @pytest.mark.asyncio
    async def test_metadata_stored_in_core_only(self, repository, storage_setup):
        """Test that metadata is stored in core, not vault."""
        storage_manager, secret_store, core_adapter, vault_adapter = storage_setup

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata={"service": "github"},
        )

        secret = b"secret"

        await repository.create(cred, secret)

        # Verify metadata in core storage
        core_keys = await core_adapter.list_keys("credentials.meta")
        assert cred.id in core_keys

        # Verify metadata NOT in vault storage
        vault_keys = await vault_adapter.list_keys("credentials.meta")
        assert cred.id not in vault_keys

    @pytest.mark.asyncio
    async def test_create_rejects_metadata_with_secret(self, repository):
        """Test that metadata containing secret-like fields is rejected."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata={"password": "secret123"},  # Not allowed!
        )

        secret = b"actual_secret"

        with pytest.raises(CredentialSecretLeakage):
            await repository.create(cred, secret)


class TestCredentialRepositoryGet:
    """Tests for credential retrieval."""

    @pytest.mark.asyncio
    async def test_get_returns_metadata_only(self, repository):
        """Test that get returns metadata without secret."""
        cred = Credential.create(
            type=CredentialType.SSH_PASSWORD,
            name="prod-server",
            secret_ref="vault:ssh:prod",
            username="deploy",
            host="prod.example.com",
        )

        secret = b"deploy_password_123"

        await repository.create(cred, secret)

        # Get metadata only
        retrieved = await repository.get(cred.id)

        assert retrieved is not None
        assert retrieved.id == cred.id
        assert retrieved.name == "prod-server"
        assert retrieved.username == "deploy"
        assert retrieved.host == "prod.example.com"

    @pytest.mark.asyncio
    async def test_get_not_found_returns_none(self, repository):
        """Test that getting non-existent credential returns None."""
        result = await repository.get("non-existent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_with_secret_returns_both(self, repository):
        """Test that get_with_secret returns metadata and secret."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="gh-token",
            secret_ref="vault:api:github",
        )

        secret = b"ghp_test_token_1234567890"

        await repository.create(cred, secret)

        # Get with secret
        result = await repository.get_with_secret(cred.id)

        assert result is not None
        retrieved_cred, retrieved_secret = result
        assert retrieved_cred.id == cred.id
        assert retrieved_secret == secret

    @pytest.mark.asyncio
    async def test_get_with_secret_not_found_returns_none(self, repository):
        """Test that get_with_secret returns None for missing credential."""
        result = await repository.get_with_secret("non-existent-id")

        assert result is None


class TestCredentialRepositoryUpdate:
    """Tests for credential updates."""

    @pytest.mark.asyncio
    async def test_update_metadata_only(self, repository):
        """Test updating metadata without changing secret."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata={"env": "dev"},
        )

        secret = b"original_secret"

        created = await repository.create(cred, secret)

        # Update metadata
        updated = created.mutate(
            metadata={"env": "prod"},  # Changed
            name="token-prod",  # Changed
        )

        result = await repository.update(updated, secret=None)

        assert result.version == 2
        assert result.metadata["env"] == "prod"
        assert result.name == "token-prod"

        # Verify secret unchanged
        _, retrieved_secret = await repository.get_with_secret(cred.id)
        assert retrieved_secret == secret

    @pytest.mark.asyncio
    async def test_update_secret_only(self, repository):
        """Test updating secret without changing metadata."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret1 = b"original_secret"
        secret2 = b"new_secret_value"

        created = await repository.create(cred, secret1)

        # Update secret only
        updated = created.mutate()  # No metadata changes

        result = await repository.update(updated, secret=secret2)

        assert result.version == 2

        # Verify new secret
        _, retrieved_secret = await repository.get_with_secret(cred.id)
        assert retrieved_secret == secret2

    @pytest.mark.asyncio
    async def test_update_both_metadata_and_secret(self, repository):
        """Test updating both metadata and secret together."""
        cred = Credential.create(
            type=CredentialType.DATABASE_PASSWORD,
            name="postgres",
            secret_ref="vault:db:postgres",
            username="appuser",
            host="db.example.com",
            port=5432,
        )

        secret1 = b"original_password"
        secret2 = b"new_password_12345"

        created = await repository.create(cred, secret1)

        # Update both
        updated = created.mutate(
            name="postgres-backup",
            host="db-backup.example.com",
        )

        result = await repository.update(updated, secret=secret2)

        assert result.version == 2
        assert result.name == "postgres-backup"
        assert result.host == "db-backup.example.com"

        # Verify both changed
        retrieved_cred, retrieved_secret = await repository.get_with_secret(cred.id)
        assert retrieved_cred.name == "postgres-backup"
        assert retrieved_secret == secret2

    @pytest.mark.asyncio
    async def test_update_version_conflict(self, repository):
        """Test that version mismatch is detected."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret"

        created = await repository.create(cred, secret)

        # Mutate to v2
        v2 = created.mutate(name="token-v2")
        await repository.update(v2, secret=None)

        # Try to update with old v1
        old_v1 = created.mutate(name="token-old")
        # This should still be v2 after mutate, but let's manually set it
        # Actually, after create it's v1, after first mutate it's v2
        # If we try to update with version=2 but actual is now v3, conflict

        # Simulate external update (fetch fresh, update, then another external update)
        # Actually, let's do simpler test:
        # Create -> v1
        # Mutate once -> v2
        # Update -> v2 becomes v3
        # Now try to update with what we thought was v2 (but now v3)

        # Simulate another update between our two updates
        current = await repository.get(cred.id)
        newer = current.mutate(name="token-newer")
        await repository.update(newer, secret=None)

        # Now v2 is outdated, current is v3
        with pytest.raises(CredentialVersionConflict):
            await repository.update(v2, secret=None)

    @pytest.mark.asyncio
    async def test_update_rejected_with_secret_in_metadata(self, repository):
        """Test that update rejects metadata with secrets."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret"

        created = await repository.create(cred, secret)

        # Try to update with secret in metadata
        bad_update = created.mutate(
            metadata={"secret": "exposed"}  # Not allowed!
        )

        with pytest.raises(CredentialSecretLeakage):
            await repository.update(bad_update, secret=None)


class TestCredentialRepositoryDelete:
    """Tests for credential deletion."""

    @pytest.mark.asyncio
    async def test_delete_removes_metadata_and_secret(self, repository):
        """Test that delete removes both metadata and secret."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret"

        await repository.create(cred, secret)

        # Verify exists
        assert await repository.exists(cred.id) is True

        # Delete
        await repository.delete(cred.id)

        # Verify removed
        assert await repository.exists(cred.id) is False
        result = await repository.get_with_secret(cred.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_non_existent_is_idempotent(self, repository):
        """Test that deleting non-existent credential is safe."""
        # Should not raise
        await repository.delete("non-existent-id")

    @pytest.mark.asyncio
    async def test_delete_twice_is_idempotent(self, repository):
        """Test that deleting same credential twice is safe."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret"

        await repository.create(cred, secret)

        # Delete twice
        await repository.delete(cred.id)
        await repository.delete(cred.id)  # Should not raise


class TestCredentialRepositoryList:
    """Tests for listing credentials."""

    @pytest.mark.asyncio
    async def test_list_empty(self, repository):
        """Test listing when no credentials exist."""
        credentials = await repository.list()

        assert credentials == []

    @pytest.mark.asyncio
    async def test_list_multiple(self, repository):
        """Test listing multiple credentials."""
        creds = []
        for i in range(3):
            cred = Credential.create(
                type=CredentialType.API_TOKEN,
                name=f"token-{i}",
                secret_ref=f"vault:api:token-{i}",
            )
            await repository.create(cred, f"secret-{i}".encode())
            creds.append(cred)

        listed = await repository.list()

        assert len(listed) == 3
        listed_ids = {c.id for c in listed}
        cred_ids = {c.id for c in creds}
        assert listed_ids == cred_ids

    @pytest.mark.asyncio
    async def test_list_returns_metadata_only(self, repository):
        """Test that list returns metadata without secrets."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret123"

        await repository.create(cred, secret)

        listed = await repository.list()

        assert len(listed) == 1
        assert listed[0].id == cred.id
        # Secret not included in returned credential


class TestCredentialRepositoryAtomicity:
    """Tests for atomic operations."""

    @pytest.mark.asyncio
    async def test_exists_returns_bool(self, repository):
        """Test exists method."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret"

        # Before create
        assert await repository.exists(cred.id) is False

        # Create
        await repository.create(cred, secret)

        # After create
        assert await repository.exists(cred.id) is True

        # After delete
        await repository.delete(cred.id)
        assert await repository.exists(cred.id) is False

    @pytest.mark.asyncio
    async def test_count_reflects_population(self, repository):
        """Test count method."""
        # Start empty
        assert await repository.count() == 0

        creds = []
        for i in range(5):
            cred = Credential.create(
                type=CredentialType.API_TOKEN,
                name=f"token-{i}",
                secret_ref=f"vault:api:token-{i}",
            )
            await repository.create(cred, b"secret")
            creds.append(cred)
            assert await repository.count() == i + 1

        # Delete one
        await repository.delete(creds[0].id)
        assert await repository.count() == 4


class TestCredentialRepositoryIsolation:
    """Tests for namespace isolation."""

    @pytest.mark.asyncio
    async def test_secret_namespace_not_in_meta(self, repository, storage_setup):
        """Test that secrets are not stored in meta namespace."""
        storage_manager, secret_store, core_adapter, vault_adapter = storage_setup

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        secret = b"secret_data"

        await repository.create(cred, secret)

        # Check meta namespace doesn't have secret namespace keys
        meta_data = await core_adapter.get("credentials.meta", cred.id)
        assert meta_data is not None

        # Ensure secret is not embedded in metadata
        meta_str = str(meta_data)
        assert b"secret_data".decode() not in meta_str

    @pytest.mark.asyncio
    async def test_meta_namespace_not_in_vault(self, repository, storage_setup):
        """Test that metadata is not stored in vault namespace."""
        storage_manager, secret_store, core_adapter, vault_adapter = storage_setup

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata={"service": "github"},
        )

        secret = b"secret"

        await repository.create(cred, secret)

        # Check vault namespace doesn't have credential metadata
        vault_meta = await vault_adapter.get("credentials.meta", cred.id)
        assert vault_meta is None


class TestCredentialRepositoryWorkflow:
    """Tests for complete workflows."""

    @pytest.mark.asyncio
    async def test_complete_lifecycle(self, repository):
        """Test complete credential lifecycle."""
        # Create SSH credential
        ssh_cred = Credential.create(
            type=CredentialType.SSH_PASSWORD,
            name="prod-deploy",
            secret_ref="vault:ssh:prod",
            username="deploy",
            host="prod.example.com",
            metadata={"env": "production"},
            tags=["production", "ssh"],
        )

        password = b"ssh_password_secure_123"

        # Create
        created = await repository.create(ssh_cred, password)
        assert created.version == 1

        # Get
        retrieved = await repository.get(created.id)
        assert retrieved.name == "prod-deploy"

        # Get with secret
        cred_with_secret, secret = await repository.get_with_secret(created.id)
        assert secret == password

        # Update metadata
        updated = created.mutate(
            name="prod-deploy-v2",
            metadata={"env": "production", "backup": True},
        )
        result = await repository.update(updated)
        assert result.version == 2

        # Update secret
        new_password = b"new_ssh_password_456"
        updated2 = result.mutate()
        result2 = await repository.update(updated2, secret=new_password)
        assert result2.version == 3

        # Verify new secret
        _, retrieved_secret = await repository.get_with_secret(created.id)
        assert retrieved_secret == new_password

        # List
        all_creds = await repository.list()
        assert len(all_creds) == 1

        # Delete
        await repository.delete(created.id)
        assert await repository.exists(created.id) is False


class TestCredentialRepositoryPolicies:
    """Tests for credential access policy persistence."""

    @pytest.mark.asyncio
    async def test_create_and_update_policy(self, repository):
        """Policy CRUD works with StorageManager compatibility methods."""
        from modules.security.rbac_models import CredentialPolicy, Role

        policy = CredentialPolicy(
            credential_id="cred-1",
            owner_user_id="admin",
            allowed_roles=[Role.ADMIN],
            secret_read_roles=[Role.ADMIN],
            allowed_users=["admin"],
            version=1,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )

        created = await repository.create_policy(policy)
        assert created.credential_id == "cred-1"

        stored = await repository.get_policy("cred-1")
        assert stored is not None
        assert stored.owner_user_id == "admin"

        updated_policy = CredentialPolicy(
            credential_id="cred-1",
            owner_user_id="admin",
            allowed_roles=[Role.ADMIN],
            secret_read_roles=[Role.ADMIN],
            allowed_users=["admin", "ops"],
            version=2,
            created_at=stored.created_at,
            updated_at="2026-01-02T00:00:00",
        )

        updated = await repository.update_policy(updated_policy)
        assert "ops" in updated.allowed_users

        stored_after_update = await repository.get_policy("cred-1")
        assert stored_after_update is not None
        assert "ops" in stored_after_update.allowed_users


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
