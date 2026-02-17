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

import secrets
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from enum import Enum

from core.agent.identity import AgentIdentity, AgentIdentityFactory


class EnrollmentTokenStatus(str, Enum):
    """Status of enrollment token."""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class EnrollmentToken:
    """
    Enrollment token for agent enrollment.
    
    One-time use token with TTL.
    """
    token_id: str  # Unique token ID
    token_secret: str  # Secret part (only shown once)
    token_hash: str  # Hash of secret (stored for comparison)
    agent_name: str  # Requested agent name
    status: str = EnrollmentTokenStatus.ACTIVE
    created_at: str = ""  # ISO 8601
    expires_at: str = ""  # ISO 8601
    used_at: Optional[str] = None
    used_by_agent_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnrollmentToken":
        return cls(**data)
    
    def is_valid(self) -> bool:
        """Check if token is still valid."""
        if self.status != EnrollmentTokenStatus.ACTIVE:
            return False
        
        # Check expiration
        expires = datetime.fromisoformat(self.expires_at)
        now = datetime.now(timezone.utc)
        
        return expires > now


class EnrollmentTokenFactory:
    """Factory for creating enrollment tokens."""
    
    TOKEN_LENGTH = 32  # bytes
    TTL_SECONDS = 3600  # 1 hour
    
    @staticmethod
    def generate_token(
        agent_name: str,
        created_at: str,
        ttl_seconds: int = TTL_SECONDS,
    ) -> EnrollmentToken:
        """
        Generate a new enrollment token.
        
        Args:
            agent_name: Requested agent name
            created_at: ISO 8601 timestamp
            ttl_seconds: Token time-to-live
            
        Returns:
            EnrollmentToken with token_secret and token_hash
        """
        # Generate token parts
        token_id = secrets.token_hex(8)  # 64-bit hex
        token_secret = secrets.token_urlsafe(EnrollmentTokenFactory.TOKEN_LENGTH)
        
        # Hash secret for storage
        token_hash = hashlib.sha256(token_secret.encode()).hexdigest()
        
        # Calculate expiration
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
        """
        Verify token secret against stored hash.
        
        Uses constant-time comparison to prevent timing attacks.
        
        Args:
            provided_secret: Secret from client
            stored_hash: Stored hash
            
        Returns:
            True if valid, False otherwise
        """
        import secrets as sec_module
        provided_hash = hashlib.sha256(provided_secret.encode()).hexdigest()
        return sec_module.compare_digest(provided_hash, stored_hash)


class AgentEnrollmentManager:
    """Manages agent enrollment process."""
    
    def __init__(self, secret_store, identity_factory=None):
        """
        Initialize enrollment manager.
        
        Args:
            secret_store: SecretStore instance for storing keys
            identity_factory: Optional custom identity factory
        """
        self._secret_store = secret_store
        self._identity_factory = identity_factory or AgentIdentityFactory
        self._pending_tokens: Dict[str, EnrollmentToken] = {}  # token_id -> token
        self._enrolled_agents: Dict[str, AgentIdentity] = {}  # agent_id -> identity
    
    async def create_enrollment_token(
        self,
        agent_name: str,
        created_at: str,
    ) -> EnrollmentToken:
        """
        Create a new enrollment token for an agent.
        
        Args:
            agent_name: Requested agent name
            created_at: ISO 8601 timestamp
            
        Returns:
            EnrollmentToken with secret (shown only once)
        """
        if not agent_name:
            raise ValueError("agent_name required")
        
        token = EnrollmentTokenFactory.generate_token(agent_name, created_at)
        self._pending_tokens[token.token_id] = token
        
        # Token secret is shown only to caller
        return token
    
    async def enroll_agent(
        self,
        token_id: str,
        token_secret: str,
        created_at: str,
    ) -> tuple[AgentIdentity, bytes]:
        """
        Enroll an agent using enrollment token.
        
        Args:
            token_id: Token ID
            token_secret: Token secret (provided by agent)
            created_at: ISO 8601 timestamp
            
        Returns:
            (AgentIdentity, private_key_bytes) tuple
            
        Raises:
            ValueError: If token invalid or already used
        """
        # Verify token exists
        if token_id not in self._pending_tokens:
            raise ValueError(f"Enrollment token not found: {token_id}")
        
        token = self._pending_tokens[token_id]
        
        # Verify token is valid
        if not token.is_valid():
            raise ValueError(f"Enrollment token not valid: {token.status}")
        
        # Verify secret
        if not EnrollmentTokenFactory.verify_token(token_secret, token.token_hash):
            raise ValueError("Enrollment token secret mismatch")
        
        # Create agent identity
        identity, private_pem = self._identity_factory.create_identity(
            agent_name=token.agent_name,
            created_at=created_at,
        )
        
        # Store private key in SecretStore
        secret_key = f"agent:{identity.agent_id}:private_key"
        await self._secret_store.put(secret_key, private_pem)
        
        # Mark token as used
        token.status = EnrollmentTokenStatus.USED
        token.used_at = created_at
        token.used_by_agent_id = identity.agent_id
        
        # Record enrolled agent
        self._enrolled_agents[identity.agent_id] = identity
        
        return identity, private_pem
    
    async def get_agent_identity(self, agent_id: str) -> Optional[AgentIdentity]:
        """
        Get agent identity if enrolled.
        
        Args:
            agent_id: Agent ID
            
        Returns:
            AgentIdentity or None
        """
        return self._enrolled_agents.get(agent_id)
    
    async def get_agent_private_key(self, agent_id: str) -> Optional[bytes]:
        """
        Get agent private key from SecretStore.
        
        Args:
            agent_id: Agent ID
            
        Returns:
            Private key bytes or None
        """
        secret_key = f"agent:{agent_id}:private_key"
        return await self._secret_store.get(secret_key)
    
    async def list_enrolled_agents(self) -> list[str]:
        """Get list of all enrolled agent IDs."""
        return list(self._enrolled_agents.keys())
    
    async def revoke_enrollment_token(self, token_id: str) -> bool:
        """
        Revoke an enrollment token.
        
        Args:
            token_id: Token ID
            
        Returns:
            True if revoked, False if not found
        """
        if token_id not in self._pending_tokens:
            return False
        
        self._pending_tokens[token_id].status = EnrollmentTokenStatus.REVOKED
        return True
    
    async def deregister_agent(self, agent_id: str) -> bool:
        """
        Deregister an agent.
        
        Args:
            agent_id: Agent ID
            
        Returns:
            True if deregistered, False if not found
        """
        if agent_id not in self._enrolled_agents:
            return False
        
        # Remove from enrolled list
        del self._enrolled_agents[agent_id]
        
        # Remove private key from SecretStore
        secret_key = f"agent:{agent_id}:private_key"
        await self._secret_store.delete(secret_key)
        
        return True
