"""
Compatibility shim for `core.agent.registry`.

Re-exports classes from `modules.agent.registry`.
"""

from modules.agent.registry import AgentRegistry, AgentMetadata, AgentStatus

__all__ = ["AgentRegistry", "AgentMetadata", "AgentStatus"]
