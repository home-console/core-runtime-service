"""
Step 15: Agent Enrollment Flow — Token-based enrollment with TTL.

Flow:
1. Core generates enrollment token (one-time use)
2. Agent provides enrollment token + agent_name
3. Core verifies token authenticity
4. Core generates agent identity + private key
5. Core stores private key in SecretStore
6. Agent receives signed identity
7. Agent uses identity for mTLS connections
"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional

from .identity import AgentIdentity, AgentIdentityFactory


class EnrollmentTokenStatus(str, Enum):
    """Status of enrollment token."""

    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class EnrollmentToken:
    """Enrollment token for agent enrollment."""

    token_id: str
    token_secret: str
    token_hash: str
    agent_name: str
    status: str = EnrollmentTokenStatus.ACTIVE
    created_at: str = ""
    expires_at: str = ""
    used_at: Optional[str] = None
    used_by_agent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnrollmentToken":
        return cls(**data)

    def is_valid(self) -> bool:
        if self.status != EnrollmentTokenStatus.ACTIVE:
            return False
        expires = datetime.fromisoformat(self.expires_at)
        now = datetime.now(timezone.utc)
        return expires > now


class EnrollmentTokenFactory:
    """Factory for creating enrollment tokens."""

    TOKEN_LENGTH = 32
    TTL_SECONDS = 3600

    @staticmethod
    def generate_token(
        agent_name: str,
        created_at: str,
        ttl_seconds: int = TTL_SECONDS,
    ) -> EnrollmentToken:
        token_id = secrets.token_hex(8)
        token_secret = secrets.token_urlsafe(EnrollmentTokenFactory.TOKEN_LENGTH)
        token_hash = hashlib.sha256(token_secret.encode()).hexdigest()
        created = datetime.fromisoformat(created_at)
        expires = created + timedelta(seconds=ttl_seconds)

        return EnrollmentToken(
            token_id=token_id,
            token_secret=token_secret,
            token_hash=token_hash,
            agent_name=agent_name,
            status=EnrollmentTokenStatus.ACTIVE,
            created_at=created_at,
            expires_at=expires.isoformat(),
        )

    @staticmethod
    def verify_token(
        provided_secret: str,
        stored_hash: str,
    ) -> bool:
        import secrets as sec_module

        provided_hash = hashlib.sha256(provided_secret.encode()).hexdigest()
        return sec_module.compare_digest(provided_hash, stored_hash)


class AgentEnrollmentManager:
    """Manages agent enrollment process."""

    def __init__(self, secret_store, identity_factory=None):
        self._secret_store = secret_store
        self._identity_factory = identity_factory or AgentIdentityFactory
        self._pending_tokens: Dict[str, EnrollmentToken] = {}
        self._enrolled_agents: Dict[str, AgentIdentity] = {}
        self._hmac_secret_key = "agent:enrollment:hmac_secret"
        self._token_hash_prefix = "agent:enrollment_token:"

    async def _get_hmac_key(self) -> bytes:
        key = await self._secret_store.get(self._hmac_secret_key)
        if key is not None:
            return key

        new_key = secrets.token_bytes(32)
        await self._secret_store.put(self._hmac_secret_key, new_key)
        return new_key

    async def create_enrollment_token(
        self,
        agent_name: str,
        created_at: str,
    ) -> EnrollmentToken:
        if not agent_name:
            raise ValueError("agent_name required")

        token = EnrollmentTokenFactory.generate_token(agent_name, created_at)
        self._pending_tokens[token.token_id] = token
        return token

    async def generate_enrollment_token(self, agent_name: str) -> str:
        if not agent_name:
            raise ValueError("agent_name required")

        now = datetime.now(timezone.utc).isoformat()
        token = EnrollmentTokenFactory.generate_token(
            agent_name=agent_name,
            created_at=now,
            ttl_seconds=600,
        )

        payload = {
            "token_id": token.token_id,
            "agent_name": token.agent_name,
            "expires_at": token.expires_at,
        }
        payload_json = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        hmac_key = await self._get_hmac_key()
        signature = hmac.new(hmac_key, payload_json, hashlib.sha256).digest()

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        signed_token = f"{_b64url(payload_json)}.{_b64url(signature)}"

        token.token_secret = signed_token
        token.token_hash = hashlib.sha256(signed_token.encode("utf-8")).hexdigest()
        self._pending_tokens[token.token_id] = token

        hash_key = f"{self._token_hash_prefix}{token.token_id}"
        await self._secret_store.put(hash_key, token.token_hash.encode("utf-8"))

        return signed_token

    async def validate_enrollment_token(self, enrollment_token: str) -> str:
        if not enrollment_token:
            raise ValueError("enrollment_token required")

        try:
            parts = enrollment_token.split(".")
            if len(parts) != 2:
                raise ValueError("Invalid token format")

            payload_b64, signature_b64 = parts

            def _b64url_decode(data: str) -> bytes:
                # Add base64 padding if needed (RFC 4648)
                pad_len = (-len(data)) % 4
                return base64.urlsafe_b64decode(data + ("=" * pad_len))
            
                padded = data + "=" * (4 - len(data) % 4)
                return base64.urlsafe_b64decode(padded)

            try:
                payload_json = _b64url_decode(payload_b64)
                provided_signature = _b64url_decode(signature_b64)
            except Exception:
                raise ValueError("Invalid token encoding")

            try:
                payload = json.loads(payload_json)
            except Exception:
                raise ValueError("Invalid payload JSON")

            token_id = payload.get("token_id")
            agent_name = payload.get("agent_name")
            expires_at_str = payload.get("expires_at")

            if not all([token_id, agent_name, expires_at_str]):
                raise ValueError("Missing required token fields")

            try:
                expires = datetime.fromisoformat(expires_at_str)
                now = datetime.now(timezone.utc)
                if expires <= now:
                    raise ValueError("enrollment_token expired")
            except ValueError as e:
                if "expired" in str(e):
                    raise
                raise ValueError("Invalid expiration timestamp")

            hmac_key = await self._get_hmac_key()
            expected_signature = hmac.new(
                hmac_key, payload_json, hashlib.sha256
            ).digest()

            if not hmac.compare_digest(provided_signature, expected_signature):
                raise ValueError("enrollment_token signature invalid")
            
            # Enforce one-time use across restarts/processes via SecretStore:
            # generate_enrollment_token() persisted sha256(enrollment_token) under token_id key.
            hash_key = f"{self._token_hash_prefix}{token_id}"
            stored_hash_bytes = await self._secret_store.get(hash_key)
            if stored_hash_bytes is None:
                # Token hash missing => already used (or never issued / revoked externally).
                raise ValueError("enrollment_token already used")

            expected_hash = hashlib.sha256(enrollment_token.encode("utf-8")).hexdigest().encode("utf-8")
            if not hmac.compare_digest(stored_hash_bytes, expected_hash):
                # Token signature may be valid, but it's not the issued token string for this token_id.
                raise ValueError("enrollment_token secret mismatch")

            # Also respect in-process revoke/used markers where available.

            if token_id in self._pending_tokens:
                token = self._pending_tokens[token_id]
                if token.status == EnrollmentTokenStatus.REVOKED:
                    raise ValueError("enrollment_token revoked")
                if token.status == EnrollmentTokenStatus.USED:
                    raise ValueError("enrollment_token already used")
            
            # Token is valid - mark as used and clean up
                elif token.status == EnrollmentTokenStatus.REVOKED:
                    raise ValueError("enrollment_token revoked")

            now = datetime.now(timezone.utc).isoformat()
            if token_id in self._pending_tokens:
                token = self._pending_tokens[token_id]
                token.status = EnrollmentTokenStatus.USED
                token.used_at = now
            else:
                # Keep a minimal in-process marker (helps avoid repeat within same process)
                self._pending_tokens[token_id] = EnrollmentToken(
                    token_id=token_id,
                    token_secret="",
                    token_hash="",
                    agent_name=agent_name,
                    status=EnrollmentTokenStatus.USED,
                    created_at="",
                    expires_at=expires_at_str,
                    used_at=now,
                )
            
            # Delete hash from SecretStore (one-time use enforcement)

            try:
                await self._secret_store.delete(hash_key)
            except Exception:
                pass

            return agent_name
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"enrollment_token validation failed: {e}")

    async def enroll_agent(
        self,
        token_id: str,
        token_secret: str,
        created_at: str,
    ) -> tuple[AgentIdentity, bytes]:
        if token_id not in self._pending_tokens:
            raise ValueError(f"Enrollment token not found: {token_id}")

        token = self._pending_tokens[token_id]

        if not token.is_valid():
            raise ValueError(f"Enrollment token not valid: {token.status}")

        if not EnrollmentTokenFactory.verify_token(token_secret, token.token_hash):
            raise ValueError("Enrollment token secret mismatch")

        identity, private_pem = self._identity_factory.create_identity(
            agent_name=token.agent_name,
            created_at=created_at,
        )

        secret_key = f"agent:{identity.agent_id}:private_key"
        await self._secret_store.put(secret_key, private_pem)

        token.status = EnrollmentTokenStatus.USED
        token.used_at = created_at
        token.used_by_agent_id = identity.agent_id

        try:
            hash_key = f"{self._token_hash_prefix}{token.token_id}"
            await self._secret_store.delete(hash_key)
        except Exception:
            pass

        self._enrolled_agents[identity.agent_id] = identity

        return identity, private_pem

    async def get_agent_identity(self, agent_id: str) -> Optional[AgentIdentity]:
        return self._enrolled_agents.get(agent_id)

    async def get_agent_private_key(self, agent_id: str) -> Optional[bytes]:
        secret_key = f"agent:{agent_id}:private_key"
        return await self._secret_store.get(secret_key)

    async def list_enrolled_agents(self) -> list[str]:
        return list(self._enrolled_agents.keys())

    async def revoke_enrollment_token(self, token_id: str) -> bool:
        if token_id not in self._pending_tokens:
            return False

        self._pending_tokens[token_id].status = EnrollmentTokenStatus.REVOKED
        return True

    async def register_agent_from_ws(
        self,
        agent_name: str,
        ws_client_id: str,
        agent_registry: Optional[Any] = None,
    ) -> str:
        import logging
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        # Дедупликация по имени: при реконнекте возвращаем существующий agent_id
        existing_id = self._agent_id_by_name(agent_name)
        if existing_id:
            identity = self._enrolled_agents[existing_id]
            logging.getLogger(__name__).info(
                f"[AgentEnrollment] ♻️ Reusing agent_id for reconnect: "
                f"agent_name={agent_name!r} agent_id={existing_id} ws_client_id={ws_client_id}"
            )
        else:
            identity, private_pem = AgentIdentityFactory.create_identity(agent_name, now)
            try:
                secret_key = f"agent:{identity.agent_id}:private_key"
                await self._secret_store.put(secret_key, private_pem)
            except Exception:
                pass
            self._enrolled_agents[identity.agent_id] = identity
            logging.getLogger(__name__).info(
                f"[AgentEnrollment] ✅ Registered agent from WS: agent_name={agent_name!r} "
                f"agent_id={identity.agent_id} ws_client_id={ws_client_id}"
            )

        # Синхронизируем с AgentRegistry чтобы list_agents() видел агента
        if agent_registry is not None:
            try:
                await agent_registry.register_agent_online(
                    agent_id=identity.agent_id,
                    agent_name=agent_name,
                    version="",
                    address=ws_client_id,
                    capabilities=[],
                    now=now,
                )
            except Exception:
                pass

        return identity.agent_id

    def _agent_id_by_name(self, agent_name: str) -> Optional[str]:
        """Найти существующий agent_id по имени агента."""
        for agent_id, identity in self._enrolled_agents.items():
            if identity.agent_name == agent_name:
                return agent_id
        return None

    async def deregister_agent(self, agent_id: str) -> bool:
        if agent_id not in self._enrolled_agents:
            return False

        del self._enrolled_agents[agent_id]

        secret_key = f"agent:{agent_id}:private_key"
        await self._secret_store.delete(secret_key)

        return True
