"""
Step 15: Agent Registry — Tracking enrolled agents and their capabilities.

Agents register as capability providers.
Registry tracks agent status, version, capabilities.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from enum import Enum


class AgentStatus(str, Enum):
    """Agent operational status."""
    ENROLLED = "enrolled"
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    DEREGISTERED = "deregistered"


@dataclass
class AgentMetadata:
    """Agent metadata and status."""
    agent_id: str
    agent_name: str
    status: str = AgentStatus.ENROLLED
    version: str = ""  # Agent version
    last_seen: Optional[str] = None  # ISO 8601
    last_heartbeat: Optional[str] = None  # ISO 8601
    address: Optional[str] = None  # IP + port
    capabilities: List[str] = None  # List of capability IDs
    properties: Dict[str, Any] = None  # Custom properties
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []
        if self.properties is None:
            self.properties = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMetadata":
        return cls(**data)


class AgentRegistry:
    """Registry for tracking enrolled agents."""
    
    def __init__(self):
        """Initialize agent registry."""
        self._agents: Dict[str, AgentMetadata] = {}  # agent_id -> metadata
    
    async def register_agent_online(
        self,
        agent_id: str,
        agent_name: str,
        version: str,
        address: str,
        capabilities: List[str],
        now: str,  # ISO 8601
    ) -> None:
        """
        Register agent as online.
        
        Args:
            agent_id: Agent ID
            agent_name: Agent name
            version: Agent version
            address: Agent address (host:port)
            capabilities: List of capability IDs
            now: Current timestamp
        """
        metadata = AgentMetadata(
            agent_id=agent_id,
            agent_name=agent_name,
            status=AgentStatus.ONLINE,
            version=version,
            last_seen=now,
            last_heartbeat=now,
            address=address,
            capabilities=capabilities,
        )
        
        self._agents[agent_id] = metadata
    
    async def update_agent_heartbeat(
        self,
        agent_id: str,
        now: str,
    ) -> Optional[AgentMetadata]:
        """
        Update agent heartbeat timestamp.
        
        Args:
            agent_id: Agent ID
            now: Current timestamp
            
        Returns:
            Updated metadata or None
        """
        if agent_id not in self._agents:
            return None
        
        metadata = self._agents[agent_id]
        metadata.last_seen = now
        metadata.last_heartbeat = now
        
        if metadata.status == AgentStatus.OFFLINE:
            metadata.status = AgentStatus.ONLINE
        
        return metadata
    
    async def mark_agent_offline(self, agent_id: str) -> Optional[AgentMetadata]:
        """
        Mark agent as offline.
        
        Args:
            agent_id: Agent ID
            
        Returns:
            Updated metadata or None
        """
        if agent_id not in self._agents:
            return None
        
        metadata = self._agents[agent_id]
        metadata.status = AgentStatus.OFFLINE
        return metadata
    
    async def get_agent(self, agent_id: str) -> Optional[AgentMetadata]:
        """Get agent metadata."""
        return self._agents.get(agent_id)
    
    async def list_agents(self) -> List[AgentMetadata]:
        """List all registered agents."""
        return list(self._agents.values())
    
    async def list_online_agents(self) -> List[AgentMetadata]:
        """List all online agents."""
        return [
            m for m in self._agents.values()
            if m.status == AgentStatus.ONLINE
        ]
    
    async def list_agents_providing_capability(
        self,
        capability_id: str,
    ) -> List[AgentMetadata]:
        """
        List agents providing a specific capability.
        
        Args:
            capability_id: Capability ID
            
        Returns:
            List of agent metadata
        """
        return [
            m for m in self._agents.values()
            if capability_id in m.capabilities and m.status == AgentStatus.ONLINE
        ]
    
    async def deregister_agent(self, agent_id: str) -> bool:
        """
        Deregister an agent.
        
        Args:
            agent_id: Agent ID
            
        Returns:
            True if deregistered, False if not found
        """
        if agent_id not in self._agents:
            return False
        
        self._agents[agent_id].status = AgentStatus.DEREGISTERED
        del self._agents[agent_id]
        return True
    
    async def get_agent_capabilities(self, agent_id: str) -> List[str]:
        """Get list of capabilities provided by agent."""
        metadata = self._agents.get(agent_id)
        return metadata.capabilities if metadata else []
    
    async def update_agent_capabilities(
        self,
        agent_id: str,
        capabilities: List[str],
    ) -> Optional[AgentMetadata]:
        """Update agent capabilities."""
        if agent_id not in self._agents:
            return None
        
        self._agents[agent_id].capabilities = capabilities
        return self._agents[agent_id]
