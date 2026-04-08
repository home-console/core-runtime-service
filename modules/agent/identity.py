"""
Agent Identity Model — Ed25519 keys and Agent IDs.

Each agent gets:
- Private key (Ed25519, stored in SecretStore)
- Public key (shareable, used for verification)
- Agent ID (deterministic hash of public key)
"""

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Dict, cast

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import logging
logger = logging.getLogger(__name__)


@dataclass
class AgentPublicKey:
    """Agent public key (shareable)."""

    key_pem: str
    algorithm: str = "Ed25519"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentPublicKey":
        return cls(**data)


@dataclass
class AgentIdentity:
    """Agent identity with keys."""

    agent_id: str
    agent_name: str
    public_key: AgentPublicKey
    created_at: str
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "public_key": self.public_key.to_dict(),
            "created_at": self.created_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentIdentity":
        data = data.copy()
        data["public_key"] = AgentPublicKey.from_dict(data["public_key"])
        return cls(**data)


class AgentKeyManager:
    """Generate and manage agent Ed25519 key pairs."""

    @staticmethod
    def generate_key_pair() -> tuple[bytes, bytes]:
        """Generate Ed25519 key pair."""
        private_key = ed25519.Ed25519PrivateKey.generate()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        return private_pem, public_pem

    @staticmethod
    def compute_agent_id(public_key_pem: bytes) -> str:
        """Compute deterministic Agent ID from public key."""
        hash_obj = hashlib.sha256(public_key_pem)
        return hash_obj.hexdigest()[:16]

    @staticmethod
    def sign_message(message: bytes, private_key_pem: bytes) -> bytes:
        """Sign a message with agent private key."""
        private_key = cast(
            ed25519.Ed25519PrivateKey,
            serialization.load_pem_private_key(
                private_key_pem,
                password=None,
                backend=default_backend(),
            ),
        )
        return private_key.sign(message)

    @staticmethod
    def verify_signature(
        message: bytes,
        signature: bytes,
        public_key_pem: bytes,
    ) -> bool:
        """Verify a message signature."""
        try:
            public_key = cast(
                ed25519.Ed25519PublicKey,
                serialization.load_pem_public_key(
                    public_key_pem,
                    backend=default_backend(),
                ),
            )
            public_key.verify(signature, message)
            return True
        except Exception as e:
            logger.warning("identity.verify_signature: failed, returning False: %s", e, exc_info=True)
            return False


class AgentIdentityFactory:
    """Factory for creating agent identities."""

    @staticmethod
    def create_identity(
        agent_name: str,
        created_at: str,
    ) -> tuple[AgentIdentity, bytes]:
        private_pem, public_pem = AgentKeyManager.generate_key_pair()
        agent_id = AgentKeyManager.compute_agent_id(public_pem)

        public_key = AgentPublicKey(
            key_pem=public_pem.decode("utf-8"),
            algorithm="Ed25519",
            created_at=created_at,
        )

        identity = AgentIdentity(
            agent_id=agent_id,
            agent_name=agent_name,
            public_key=public_key,
            created_at=created_at,
            version=1,
        )

        return identity, private_pem
