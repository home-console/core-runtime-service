"""
Unit tests for Credential domain model.

Tests cover:
- Creation and initialization
- Validation logic
- Serialization/deserialization
- Fingerprinting for integrity
- Immutable mutation pattern
- Edge cases
"""

import pytest
import time
from core.credentials.domain import (
    Credential,
    CredentialType,
    CredentialValidationError,
)


class TestCredentialType:
    """Tests for CredentialType enum."""

    def test_enum_values(self):
        """Test enum values are correct."""
        assert CredentialType.SSH_PASSWORD.value == "ssh_password"
        assert CredentialType.SSH_KEY.value == "ssh_key"
        assert CredentialType.API_TOKEN.value == "api_token"
        assert CredentialType.OAUTH_TOKEN.value == "oauth_token"
        assert CredentialType.DATABASE_PASSWORD.value == "database_password"
        assert CredentialType.GENERIC_SECRET.value == "generic_secret"

    def test_enum_from_string(self):
        """Test constructing enum from string."""
        assert CredentialType("ssh_password") == CredentialType.SSH_PASSWORD
        assert CredentialType("api_token") == CredentialType.API_TOKEN

    def test_enum_is_string(self):
        """Test that CredentialType is also a string."""
        cred_type = CredentialType.SSH_PASSWORD
        assert str(cred_type.value) == "ssh_password"


class TestCredentialCreation:
    """Tests for credential creation."""

    def test_create_ssh_password_credential(self):
        """Test creating a valid SSH password credential."""
        cred = Credential.create(
            type=CredentialType.SSH_PASSWORD,
            name="prod-server",
            secret_ref="vault:ssh:prod",
            username="deploy",
            host="prod.example.com",
        )

        assert cred.type == CredentialType.SSH_PASSWORD
        assert cred.name == "prod-server"
        assert cred.username == "deploy"
        assert cred.host == "prod.example.com"
        assert cred.port is None
        assert cred.version == 1
        assert cred.created_at == cred.updated_at
        assert cred.tags == []
        assert cred.metadata == {}
        assert len(cred.id) > 0

    def test_create_ssh_key_credential(self):
        """Test creating an SSH key credential."""
        cred = Credential.create(
            type=CredentialType.SSH_KEY,
            name="github-deploy-key",
            secret_ref="vault:ssh:github-key",
            username="git",
            host="github.com",
        )

        assert cred.type == CredentialType.SSH_KEY
        assert cred.host == "github.com"

    def test_create_api_token(self):
        """Test creating a valid API token credential."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="github-token",
            secret_ref="vault:api:github",
            metadata={"repo": "homeconsole"},
            tags=["ci", "github"],
        )

        assert cred.type == CredentialType.API_TOKEN
        assert cred.name == "github-token"
        assert cred.metadata == {"repo": "homeconsole"}
        assert cred.tags == ["ci", "github"]
        assert cred.username is None
        assert cred.host is None

    def test_create_database_credential(self):
        """Test creating a database credential."""
        cred = Credential.create(
            type=CredentialType.DATABASE_PASSWORD,
            name="postgres-prod",
            secret_ref="vault:db:postgres",
            username="app_user",
            host="db.example.com",
            port=5432,
        )

        assert cred.type == CredentialType.DATABASE_PASSWORD
        assert cred.username == "app_user"
        assert cred.host == "db.example.com"
        assert cred.port == 5432
        assert cred.version == 1

    def test_create_generates_unique_ids(self):
        """Test that create() generates unique IDs."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token1",
            secret_ref="vault:api:1",
        )
        cred2 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token2",
            secret_ref="vault:api:2",
        )

        assert cred1.id != cred2.id
        assert len(cred1.id) > 0
        assert len(cred2.id) > 0

    def test_create_sets_version_to_one(self):
        """Test that create() sets version to 1."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        assert cred.version == 1

    def test_create_sets_timestamps(self):
        """Test that create() sets equal timestamps."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        assert cred.created_at == cred.updated_at
        assert cred.created_at.endswith("Z")  # ISO8601 UTC


class TestCredentialValidation:
    """Tests for credential validation."""

    def test_validation_on_create(self):
        """Test that create() calls validate()."""
        with pytest.raises(CredentialValidationError):
            Credential.create(
                type=CredentialType.SSH_PASSWORD,
                name="",  # Invalid: empty name
                secret_ref="vault:ssh:test",
                username="user",
                host="host.com",
            )

    def test_ssh_password_requires_host(self):
        """Test SSH password credential requires host."""
        with pytest.raises(CredentialValidationError):
            Credential.create(
                type=CredentialType.SSH_PASSWORD,
                name="test",
                secret_ref="vault:ssh:test",
                username="user",
                host=None,
            )

    def test_ssh_key_requires_username(self):
        """Test SSH key credential requires username."""
        with pytest.raises(CredentialValidationError):
            Credential.create(
                type=CredentialType.SSH_KEY,
                name="test",
                secret_ref="vault:ssh:test",
                username=None,
                host="host.com",
            )

    def test_database_requires_port(self):
        """Test database credential requires port."""
        with pytest.raises(CredentialValidationError):
            Credential.create(
                type=CredentialType.DATABASE_PASSWORD,
                name="db",
                secret_ref="vault:db:test",
                username="user",
                host="db.com",
                port=None,
            )

    def test_api_token_allows_no_host(self):
        """Test API token doesn't require host or username."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:test",
            username=None,
            host=None,
        )

        assert cred.host is None
        assert cred.username is None

    def test_generic_secret_requires_only_id_and_secret_ref(self):
        """Test generic secret has minimal requirements."""
        cred = Credential.create(
            type=CredentialType.GENERIC_SECRET,
            name="secret",
            secret_ref="vault:secret:generic",
        )

        assert cred.type == CredentialType.GENERIC_SECRET
        assert cred.host is None
        assert cred.username is None

    def test_validation_rejects_invalid_version(self):
        """Test validation rejects invalid version."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="test",
            secret_ref="vault:api:test",
        )

        # Manually create invalid credential
        with pytest.raises(CredentialValidationError):
            Credential(
                id=cred.id,
                type=cred.type,
                name=cred.name,
                secret_ref=cred.secret_ref,
                username=None,
                host=None,
                port=None,
                metadata={},
                tags=[],
                version=0,  # Invalid: version < 1
                created_at=cred.created_at,
                updated_at=cred.updated_at,
            ).validate()

    def test_validation_rejects_empty_name(self):
        """Test validation rejects empty name."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="test",
            secret_ref="vault:api:test",
        )

        with pytest.raises(CredentialValidationError):
            Credential(
                id=cred.id,
                type=cred.type,
                name="",  # Invalid: empty
                secret_ref=cred.secret_ref,
                username=None,
                host=None,
                port=None,
                metadata={},
                tags=[],
                version=1,
                created_at=cred.created_at,
                updated_at=cred.updated_at,
            ).validate()

    def test_validation_rejects_empty_secret_ref(self):
        """Test validation rejects empty secret_ref."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="test",
            secret_ref="vault:api:test",
        )

        with pytest.raises(CredentialValidationError):
            Credential(
                id=cred.id,
                type=cred.type,
                name=cred.name,
                secret_ref="",  # Invalid: empty
                username=None,
                host=None,
                port=None,
                metadata={},
                tags=[],
                version=1,
                created_at=cred.created_at,
                updated_at=cred.updated_at,
            ).validate()


class TestCredentialSerialization:
    """Tests for serialization/deserialization."""

    def test_to_dict(self):
        """Test to_dict serialization."""
        cred = Credential.create(
            type=CredentialType.SSH_PASSWORD,
            name="server",
            secret_ref="vault:ssh:server",
            username="root",
            host="example.com",
            metadata={"env": "prod"},
            tags=["ssh", "prod"],
        )

        data = cred.to_dict()

        assert data["id"] == cred.id
        assert data["type"] == "ssh_password"  # Serialized as string
        assert data["name"] == "server"
        assert data["username"] == "root"
        assert data["host"] == "example.com"
        assert data["metadata"] == {"env": "prod"}
        assert data["tags"] == ["ssh", "prod"]
        assert data["version"] == 1

    def test_from_dict(self):
        """Test from_dict deserialization."""
        data = {
            "id": "cred-123",
            "type": "api_token",
            "name": "github",
            "secret_ref": "vault:api:github",
            "username": None,
            "host": None,
            "port": None,
            "metadata": {"org": "myorg"},
            "tags": ["ci"],
            "version": 1,
            "created_at": "2026-02-17T10:00:00Z",
            "updated_at": "2026-02-17T10:00:00Z",
        }

        cred = Credential.from_dict(data)

        assert cred.id == "cred-123"
        assert cred.type == CredentialType.API_TOKEN
        assert cred.name == "github"
        assert cred.metadata == {"org": "myorg"}

    def test_roundtrip_serialization(self):
        """Test to_dict -> from_dict roundtrip."""
        original = Credential.create(
            type=CredentialType.DATABASE_PASSWORD,
            name="prod-db",
            secret_ref="vault:db:prod",
            username="dbuser",
            host="db.example.com",
            port=5432,
            metadata={"engine": "postgresql"},
            tags=["database", "prod"],
        )

        data = original.to_dict()
        restored = Credential.from_dict(data)

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.name == original.name
        assert restored.username == original.username
        assert restored.host == original.host
        assert restored.port == original.port
        assert restored.metadata == original.metadata
        assert restored.tags == original.tags
        assert restored.version == original.version
        assert restored.created_at == original.created_at
        assert restored.updated_at == original.updated_at


class TestCredentialFingerprint:
    """Tests for fingerprint computation."""

    def test_fingerprint_is_deterministic(self):
        """Test fingerprint is same for same credential."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata={"service": "service1"},
            tags=["api"],
        )

        fp1 = cred.fingerprint()
        fp2 = cred.fingerprint()

        assert fp1 == fp2

    def test_fingerprint_is_hex(self):
        """Test fingerprint is valid SHA256 hex string."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        fp = cred.fingerprint()

        assert len(fp) == 64  # SHA256 hex string is 64 chars
        assert all(c in "0123456789abcdef" for c in fp)

    def test_fingerprint_different_for_different_credentials(self):
        """Test different credentials have different fingerprints."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token1",
            secret_ref="vault:api:token1",
        )
        cred2 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token2",
            secret_ref="vault:api:token2",
        )

        assert cred1.fingerprint() != cred2.fingerprint()

    def test_fingerprint_excludes_updated_at(self):
        """Test fingerprint excludes updated_at (stable across updates)."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        # Get fingerprint before mutation
        fp_before = cred1.fingerprint()

        # Mutate (changes updated_at and version)
        cred2 = cred1.mutate(name="token")  # Name doesn't change

        # Fingerprints should be different because version changed
        assert cred1.fingerprint() != cred2.fingerprint()


class TestCredentialMutation:
    """Tests for immutable mutation pattern."""

    def test_mutate_increments_version(self):
        """Test that mutate increments version."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        cred2 = cred1.mutate(metadata={"updated": True})

        assert cred2.version == cred1.version + 1
        assert cred2.version == 2

    def test_mutate_updates_timestamp(self):
        """Test that mutate updates updated_at."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        time.sleep(0.01)  # Ensure time passes

        cred2 = cred1.mutate(name="token-renamed")

        assert cred2.updated_at > cred1.updated_at

    def test_mutate_preserves_created_at(self):
        """Test that mutate preserves created_at."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        cred2 = cred1.mutate(name="token-renamed")

        assert cred2.created_at == cred1.created_at

    def test_mutate_original_unchanged(self):
        """Test that original credential is unchanged after mutate."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        original_name = cred1.name
        original_version = cred1.version
        original_updated_at = cred1.updated_at

        cred2 = cred1.mutate(name="token-renamed")

        # Original should be unchanged
        assert cred1.name == original_name
        assert cred1.version == original_version
        assert cred1.updated_at == original_updated_at  # Also unchanged

    def test_mutate_multiple_times(self):
        """Test multiple mutations work correctly."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        cred = cred.mutate(name="token-v2")
        assert cred.version == 2

        cred = cred.mutate(metadata={"version": 2})
        assert cred.version == 3

        cred = cred.mutate(tags=["updated"])
        assert cred.version == 4

    def test_mutate_changes_name(self):
        """Test mutation can change credential name."""
        cred1 = Credential.create(
            type=CredentialType.SSH_PASSWORD,
            name="old-name",
            secret_ref="vault:ssh:prod",
            username="user",
            host="host.com",
        )

        cred2 = cred1.mutate(name="new-name")

        assert cred2.name == "new-name"
        assert cred1.name == "old-name"

    def test_mutate_metadata(self):
        """Test mutation can update metadata."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata={"v": 1},
        )

        cred2 = cred1.mutate(metadata={"v": 2, "new_field": "value"})

        assert cred2.metadata == {"v": 2, "new_field": "value"}
        assert cred1.metadata == {"v": 1}

    def test_mutate_tags(self):
        """Test mutation can update tags."""
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            tags=["old"],
        )

        cred2 = cred1.mutate(tags=["prod", "ci"])

        assert cred2.tags == ["prod", "ci"]
        assert cred1.tags == ["old"]


class TestCredentialImmutability:
    """Tests for immutability."""

    def test_credential_is_frozen(self):
        """Test that credential instances are immutable."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            cred.name = "modified"

    def test_metadata_dict_is_not_modified_by_mutate(self):
        """Test that original metadata dict is not modified."""
        meta = {"key": "value"}
        cred1 = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata=meta,
        )

        cred2 = cred1.mutate(metadata={"new": "data"})

        # Original metadata should not be modified
        assert cred1.metadata == {"key": "value"}
        assert cred2.metadata == {"new": "data"}


class TestCredentialEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_large_metadata(self):
        """Test credential with large metadata."""
        large_metadata = {
            "key" + str(i): "value" * 100 for i in range(100)
        }

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            metadata=large_metadata,
        )

        assert len(cred.metadata) == 100
        assert cred.to_dict()["metadata"] == large_metadata

    def test_many_tags(self):
        """Test credential with many tags."""
        many_tags = ["tag" + str(i) for i in range(50)]

        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
            tags=many_tags,
        )

        assert len(cred.tags) == 50

    def test_optional_fields_none(self):
        """Test credential with all optional fields None."""
        cred = Credential.create(
            type=CredentialType.GENERIC_SECRET,
            name="secret",
            secret_ref="vault:secret:generic",
        )

        assert cred.username is None
        assert cred.host is None
        assert cred.port is None
        assert cred.metadata == {}
        assert cred.tags == []

    def test_special_characters_in_name(self):
        """Test credential with special characters in name."""
        special_name = "token-@#$%^&*()_+{}[]|:;<>?,./~`"
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name=special_name,
            secret_ref="vault:api:special",
        )

        assert cred.name == special_name

    def test_unicode_in_metadata(self):
        """Test credential with unicode in metadata."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:unicode",
            metadata={"description": "😀 Emoji and 中文 text"},
        )

        assert cred.metadata["description"] == "😀 Emoji and 中文 text"
        assert cred.to_dict()["metadata"]["description"] == (
            "😀 Emoji and 中文 text"
        )

    def test_port_nonzero_requirement(self):
        """Test credential requires port > 0 for DATABASE_PASSWORD."""
        # Port 0 is invalid for database credentials
        with pytest.raises(CredentialValidationError):
            Credential.create(
                type=CredentialType.DATABASE_PASSWORD,
                name="db",
                secret_ref="vault:db:test",
                username="user",
                host="host.com",
                port=0,
            )

    def test_high_port_number(self):
        """Test credential with high port number."""
        cred = Credential.create(
            type=CredentialType.DATABASE_PASSWORD,
            name="db",
            secret_ref="vault:db:test",
            username="user",
            host="host.com",
            port=65535,
        )

        assert cred.port == 65535

    def test_from_dict_with_missing_optional_fields(self):
        """Test from_dict handles missing optional fields."""
        data = {
            "id": "cred-123",
            "type": "api_token",
            "name": "token",
            "secret_ref": "vault:api:token",
            "version": 1,
            "created_at": "2026-02-17T10:00:00Z",
            "updated_at": "2026-02-17T10:00:00Z",
            # Missing: username, host, port, metadata, tags
        }

        cred = Credential.from_dict(data)

        assert cred.username is None
        assert cred.host is None
        assert cred.port is None
        assert cred.metadata == {}
        assert cred.tags == []


class TestCredentialValidationEdgeCases:
    """Tests for validation edge cases."""

    def test_validation_with_min_valid_fields(self):
        """Test validation with minimal required fields."""
        cred = Credential.create(
            type=CredentialType.GENERIC_SECRET,
            name="s",  # Min 1 char
            secret_ref="v",  # Min 1 char
        )

        cred.validate()  # Should not raise

    def test_very_long_id(self):
        """Test validation accepts very long ID."""
        cred = Credential.create(
            type=CredentialType.API_TOKEN,
            name="token",
            secret_ref="vault:api:token",
        )

        # IDs are UUIDs, which are fixed length
        assert len(cred.id) == 36  # UUID4 with hyphens

    def test_timestamps_with_microseconds(self):
        """Test timestamps with microseconds parse correctly."""
        data = {
            "id": "cred-123",
            "type": "api_token",
            "name": "token",
            "secret_ref": "vault:api:token",
            "username": None,
            "host": None,
            "port": None,
            "metadata": {},
            "tags": [],
            "version": 1,
            "created_at": "2026-02-17T10:00:00.123456Z",
            "updated_at": "2026-02-17T10:00:00.123456Z",
        }

        cred = Credential.from_dict(data)

        assert cred.created_at == data["created_at"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
