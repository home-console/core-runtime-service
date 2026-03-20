"""Regression tests for the public agent module facade."""

from modules import agent as agent_module
from modules import agents as legacy_agents


def test_modules_agent_exports_canonical_agent_api() -> None:
    assert hasattr(agent_module, "AgentModule")
    assert hasattr(agent_module, "AgentEnrollmentManager")
    assert hasattr(agent_module, "AgentRegistry")
    assert hasattr(agent_module, "MTLSCertificateAuthority")
    assert hasattr(agent_module, "DeploymentTracker")
    assert hasattr(agent_module, "AgentLogStore")
    assert hasattr(agent_module, "AgentDeployService")



def test_modules_agents_remains_compatibility_alias() -> None:
    assert legacy_agents.AgentEnrollmentManager is agent_module.AgentEnrollmentManager
    assert legacy_agents.AgentRegistry is agent_module.AgentRegistry
    assert legacy_agents.MTLSCertificateAuthority is agent_module.MTLSCertificateAuthority
    assert legacy_agents.DeploymentTracker is agent_module.DeploymentTracker
    assert legacy_agents.AgentLogStore is agent_module.AgentLogStore
