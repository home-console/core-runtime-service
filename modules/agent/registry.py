"""
Agent Registry — Tracking enrolled agents and their capabilities.

Agents register as capability providers.
Registry tracks agent status, version, capabilities.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    version: str = ""
    last_seen: Optional[str] = None
    last_heartbeat: Optional[str] = None
    address: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMetadata":
        return cls(**data)


class AgentRegistry:
    """Registry for tracking enrolled agents."""

    def __init__(self):
        self._agents: Dict[str, AgentMetadata] = {}

    async def register_agent_online(
        self,
        agent_id: str,
        agent_name: str,
        version: str,
        address: str,
        capabilities: List[str],
        now: str,
    ) -> None:
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
        if agent_id not in self._agents:
            return None

        metadata = self._agents[agent_id]
        metadata.last_seen = now
        metadata.last_heartbeat = now

        if metadata.status == AgentStatus.OFFLINE:
            metadata.status = AgentStatus.ONLINE

        return metadata

    async def mark_agent_offline(self, agent_id: str) -> Optional[AgentMetadata]:
        if agent_id not in self._agents:
            return None

        metadata = self._agents[agent_id]
        metadata.status = AgentStatus.OFFLINE
        return metadata

    async def get_agent(self, agent_id: str) -> Optional[AgentMetadata]:
        return self._agents.get(agent_id)

    async def list_agents(self) -> List[AgentMetadata]:
        return list(self._agents.values())

    async def list_online_agents(self) -> List[AgentMetadata]:
        return [m for m in self._agents.values() if m.status == AgentStatus.ONLINE]

    async def list_agents_providing_capability(
        self,
        capability_id: str,
    ) -> List[AgentMetadata]:
        return [
            m
            for m in self._agents.values()
            if capability_id in m.capabilities and m.status == AgentStatus.ONLINE
        ]

    async def deregister_agent(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False

        self._agents[agent_id].status = AgentStatus.DEREGISTERED
        del self._agents[agent_id]
        return True

    async def get_agent_capabilities(self, agent_id: str) -> List[str]:
        metadata = self._agents.get(agent_id)
        return metadata.capabilities if metadata else []

    async def update_agent_capabilities(
        self,
        agent_id: str,
        capabilities: List[str],
    ) -> Optional[AgentMetadata]:
        if agent_id not in self._agents:
            return None

        self._agents[agent_id].capabilities = capabilities
        return self._agents[agent_id]
