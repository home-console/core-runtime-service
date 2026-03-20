"""Legacy compatibility shim for the agent deploy service."""

from modules.agent.deploy_service import AgentDeployConfig, AgentDeployService

__all__ = ["AgentDeployConfig", "AgentDeployService"]
