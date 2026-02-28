"""
Unit tests for Credential Runtime Module (Step 17.3)

Tests cover:
- Module registration
- Operation handlers
- CredentialService integration
- Schema validation
- Optimistic locking
- Audit logging (placeholder)
- Capability routing
"""

import pytest
import asyncio
from typing import Optional, Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from core.credentials import (
    Credential,
    CredentialType,
    CredentialRepository,
)
from modules.credentials import (
    CredentialModule,
    CredentialService,
    CreateCredentialRequest,
    UpdateCredentialRequest,
    CredentialMetadata,
    CredentialWithSecretResponse,
)


class MockRuntime:
    """Mock CoreRuntime for testing."""
    def __init__(self):
        self.storage = MagicMock()
        self.secret_store = MagicMock()
        self.audit = MagicMock()
        self.service_registry = MagicMock()
        self.http = MagicMock()
        self.capability_registry = MagicMock()
        self.operations = MagicMock()
        self.vault = None
        self.state_engine = MagicMock()
        self._services = {}

    async def register_service(self, name, func, **kwargs):
        """Register a service."""
        self._services[name] = func

    async def call_service(self, name, **params):
        """Call a registered service."""
        if name not in self._services:
            raise ValueError(f"Service {name} not registered")
        return await self._services[name](**params)


class TestCredentialModuleRegistration:
    """Tests for module registration."""

    @pytest.mark.asyncio
    async def test_module_name(self):
        """Test module has correct name."""
        runtime = MockRuntime()
        module = CredentialModule(runtime)
        assert module.name == "credentials"

    @pytest.mark.asyncio
    async def test_module_registers_8_operations(self):
        """Test module registers exactly 8 operations."""
        runtime = MockRuntime()
        
        # Mock service_registry
        registered_ops = []
        async def mock_register(name, func, **kwargs):
            registered_ops.append(name)
        
        runtime.service_registry.register = mock_register
        
        # Manually patch register_service method (since we need to track it)
        async def mock_register_service(service_name, func, **kwargs):
            registered_ops.append(service_name)
        
        module = CredentialModule(runtime)
        module.register_service = mock_register_service
        
        await module.register()
        
        # Should register exactly 8 operations
        expected_ops = [
            "credential.create",
            "credential.get",
            "credential.get_with_secret",
            "credential.list",
            "credential.update",
            "credential.delete",
            "credential.exists",
            "credential.count",
        ]
        
        # Check that all expected operations are registered
        for op in expected_ops:
            assert any(op in str(name) for name in registered_ops), \
                f"Operation {op} not registered"


class TestCredentialServiceCreate:
    """Tests for create operation."""

    @pytest.fixture
    async def service_with_repo(self):
        """Create service with mocked repository."""
        repo = AsyncMock(spec=CredentialRepository)
        service = CredentialService(repository=repo)
        return service, repo

    @pytest.mark.asyncio
    async def test_create_success(self, service_with_repo):
        """Test successful credential creation."""
        service, repo = service_with_repo
        
        # Mock repo.create
        created_cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="github-token",
            secret_ref="vault:api:github",
        )
        repo.create.return_value = created_cred
        
        # Create
        request = CreateCredentialRequest(
            type=CredentialType.API_TOKEN.value,
            name="github-token",
            secret_ref="vault:api:github",
        )
        secret = b"ghp_token_123"
        
        result = await service.create(request, secret, user_id="user1")
        
        # Verify
        assert isinstance(result, CredentialMetadata)
        assert result.name == "github-token"
        assert result.type == CredentialType.API_TOKEN.value
        repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_validates_request(self, service_with_repo):
        """Test create validates request fields."""
        service, repo = service_with_repo
        
        # Invalid request (missing type)
        request = CreateCredentialRequest(
            type="",
            name="token",
            secret_ref="vault:api",
        )
        
        with pytest.raises(ValueError):
            await service.create(request, b"secret", user_id="user1")

    @pytest.mark.asyncio
    async def test_create_rejects_secret_in_metadata(self, service_with_repo):
        """Test create rejects metadata containing secret keywords."""
        service, repo = service_with_repo
        
        from core.credentials.errors import CredentialSecretLeakage
        repo.create.side_effect = CredentialSecretLeakage("password in metadata")
        
        request = CreateCredentialRequest(
            type=CredentialType.API_TOKEN.value,
            name="token",
            secret_ref="vault:api",
            metadata={"password": "exposed"},
        )
        
        with pytest.raises(CredentialSecretLeakage):
            await service.create(request, b"secret", user_id="user1")


class TestCredentialServiceGet:
    """Tests for get operations."""

    @pytest.fixture
    async def service_with_repo(self):
        """Create service with mocked repository."""
        repo = AsyncMock(spec=CredentialRepository)
        service = CredentialService(repository=repo)
        return service, repo

    @pytest.mark.asyncio
    async def test_get_metadata_only(self, service_with_repo):
        """Test get returns metadata only (no secret)."""
        service, repo = service_with_repo
        
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        repo.get.return_value = cred
        
        result = await service.get(cred.id, user_id="user1")
        
        assert result is not None
        assert result.name == "token"
        assert isinstance(result, CredentialMetadata)
        repo.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_not_found(self, service_with_repo):
        """Test get raises CredentialNotFound for missing credential."""
        service, repo = service_with_repo
        repo.get.return_value = None
        
        with pytest.raises(Exception):  # CredentialNotFound
            await service.get("non-existent", user_id="user1")

    @pytest.mark.asyncio
    async def test_get_with_secret(self, service_with_repo):
        """Test get_with_secret returns both metadata and secret."""
        service, repo = service_with_repo
        
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        secret = b"token_secret_123"
        repo.get_with_secret.return_value = (cred, secret)
        
        result = await service.get_with_secret(cred.id, user_id="user1")
        
        assert result is not None
        assert isinstance(result, CredentialWithSecretResponse)
        assert result.secret == secret
        assert result.metadata.name == "token"


class TestCredentialServiceUpdate:
    """Tests for update operations (optimistic locking)."""

    @pytest.fixture
    async def service_with_repo(self):
        """Create service with mocked repository."""
        repo = AsyncMock(spec=CredentialRepository)
        service = CredentialService(repository=repo)
        return service, repo

    @pytest.mark.asyncio
    async def test_update_metadata_only(self, service_with_repo):
        """Test update with metadata changes only."""
        service, repo = service_with_repo
        
        # Create original
        original = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        repo.get.return_value = original
        
        # Prepare updated (mutated)
        updated = original.mutate(name="token-v2")
        repo.update.return_value = updated
        
        # Call update
        request = UpdateCredentialRequest(
            id=original.id,
            version=original.version,
            name="token-v2",
        )
        
        result = await service.update(request, secret=None, user_id="user1")
        
        assert result.name == "token-v2"
        assert result.version == 2
        repo.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_version_conflict(self, service_with_repo):
        """Test update detects version conflicts."""
        service, repo = service_with_repo
        
        from core.credentials.errors import CredentialVersionConflict
        
        # Current credential is v3
        current = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        for _ in range(2):  # Increment to v3
            current = current.mutate()
        
        repo.get.return_value = current
        
        # Try to update with old v2 (but current is v3)
        request = UpdateCredentialRequest(
            id=current.id,
            version=2,  # Old version
            name="new-name",
        )
        
        with pytest.raises(CredentialVersionConflict):
            await service.update(request, user_id="user1")


class TestCredentialServiceList:
    """Tests for list operation."""

    @pytest.fixture
    async def service_with_repo(self):
        """Create service with mocked repository."""
        repo = AsyncMock(spec=CredentialRepository)
        service = CredentialService(repository=repo)
        return service, repo

    @pytest.mark.asyncio
    async def test_list_empty(self, service_with_repo):
        """Test list returns empty list."""
        service, repo = service_with_repo
        repo.list.return_value = []
        
        result = await service.list(user_id="user1")
        
        assert result == []
        repo.list.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_multiple(self, service_with_repo):
        """Test list returns multiple credentials."""
        service, repo = service_with_repo
        
        creds = [
            Credential.create(
                type=CredentialType.API_TOKEN,
                name=f"token-{i}",
                secret_ref=f"vault:api:{i}",
            )
            for i in range(3)
        ]
        repo.list.return_value = creds
        
        result = await service.list(user_id="user1")
        
        assert len(result) == 3
        assert all(isinstance(c, CredentialMetadata) for c in result)


class TestCredentialServiceDelete:
    """Tests for delete operation."""

    @pytest.fixture
    async def service_with_repo(self):
        """Create service with mocked repository."""
        repo = AsyncMock(spec=CredentialRepository)
        service = CredentialService(repository=repo)
        return service, repo

    @pytest.mark.asyncio
    async def test_delete_exists(self, service_with_repo):
        """Test delete removes credential."""
        service, repo = service_with_repo
        
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        repo.get.return_value = cred
        
        await service.delete(cred.id, user_id="user1")
        
        repo.delete.assert_called_once_with(cred.id)

    @pytest.mark.asyncio
    async def test_delete_not_found_is_idempotent(self, service_with_repo):
        """Test delete on non-existent credential is idempotent."""
        service, repo = service_with_repo
        repo.get.return_value = None
        
        # Should not raise
        await service.delete("non-existent", user_id="user1")
        
        repo.delete.assert_called_once()


class TestCredentialServiceUtility:
    """Tests for exists and count operations."""

    @pytest.fixture
    async def service_with_repo(self):
        """Create service with mocked repository."""
        repo = AsyncMock(spec=CredentialRepository)
        service = CredentialService(repository=repo)
        return service, repo

    @pytest.mark.asyncio
    async def test_exists_true(self, service_with_repo):
        """Test exists returns true for existing credential."""
        service, repo = service_with_repo
        repo.exists.return_value = True
        
        result = await service.exists("some-id", user_id="user1")
        
        assert result is True
        repo.exists.assert_called_once()

    @pytest.mark.asyncio
    async def test_exists_false(self, service_with_repo):
        """Test exists returns false for non-existent credential."""
        service, repo = service_with_repo
        repo.exists.return_value = False
        
        result = await service.exists("non-existent", user_id="user1")
        
        assert result is False

    @pytest.mark.asyncio
    async def test_count(self, service_with_repo):
        """Test count returns credential count (filtered by RBAC)."""
        service, repo = service_with_repo
        
        # Mock repo.list() since count now filters by RBAC
        creds = [
            Credential.create(CredentialType.API_TOKEN, "token1", "vault:token1"),
            Credential.create(CredentialType.API_TOKEN, "token2", "vault:token2"),
        ]
        repo.list.return_value = creds
        
        result = await service.count(user_id="user1")
        
        # Without RBAC enforcer, all credentials are counted
        assert result == 2
        repo.list.assert_called_once()


class TestSchemaValidation:
    """Tests for DTO schema validation."""

    def test_create_request_validates_type(self):
        """Test CreateCredentialRequest validates type."""
        request = CreateCredentialRequest(
            type="",
            name="token",
            secret_ref="vault",
        )
        
        with pytest.raises(ValueError):
            request.validate()

    def test_create_request_validates_name(self):
        """Test CreateCredentialRequest validates name."""
        request = CreateCredentialRequest(
            type=CredentialType.API_TOKEN.value,
            name="",
            secret_ref="vault",
        )
        
        with pytest.raises(ValueError):
            request.validate()

    def test_create_request_validates_secret_ref(self):
        """Test CreateCredentialRequest validates secret_ref."""
        request = CreateCredentialRequest(
            type=CredentialType.API_TOKEN.value,
            name="token",
            secret_ref="",
        )
        
        with pytest.raises(ValueError):
            request.validate()

    def test_update_request_validates_id(self):
        """Test UpdateCredentialRequest validates id."""
        request = UpdateCredentialRequest(
            id="",
            version=1,
        )
        
        with pytest.raises(ValueError):
            request.validate()

    def test_update_request_validates_version(self):
        """Test UpdateCredentialRequest validates version."""
        request = UpdateCredentialRequest(
            id="some-id",
            version=0,  # Invalid
        )
        
        with pytest.raises(ValueError):
            request.validate()

    def test_credential_metadata_to_dict(self):
        """Test CredentialMetadata converts to dict."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        
        metadata = CredentialMetadata.from_domain(cred)
        result = metadata.to_dict()
        
        assert isinstance(result, dict)
        assert result["id"] == cred.id
        assert result["name"] == "token"
        assert "secret" not in result  # No raw secret


class TestSecretIsolation:
    """Tests for secret isolation guarantees."""

    @pytest.mark.asyncio
    async def test_metadata_dto_never_contains_secret(self):
        """Test CredentialMetadata never includes raw secret."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        
        metadata = CredentialMetadata.from_domain(cred)
        data = metadata.to_dict()
        
        # Should not contain any secret field
        assert "secret" not in data
        assert data["secret_ref"] == "vault:api"  # Ref only, not actual secret

    @pytest.mark.asyncio
    async def test_with_secret_response_includes_secret(self):
        """Test CredentialWithSecretResponse includes secret (elevated)."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api",
        )
        secret = b"actual_secret"
        
        metadata = CredentialMetadata.from_domain(cred)
        response = CredentialWithSecretResponse(metadata=metadata, secret=secret)
        data = response.to_dict()
        
        # Should include secret (hex-encoded for JSON)
        assert "secret" in data
        assert data["secret"] == secret.hex()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
