"""Regression tests for the public agent module facade."""

import importlib

import pytest

from modules import agent as agent_module


def test_modules_agent_exports_canonical_agent_api() -> None:
    assert hasattr(agent_module, "AgentModule")
    assert hasattr(agent_module, "AgentEnrollmentManager")
    assert hasattr(agent_module, "AgentRegistry")
    assert hasattr(agent_module, "MTLSCertificateAuthority")
    assert hasattr(agent_module, "DeploymentTracker")
    assert hasattr(agent_module, "AgentLogStore")
    assert hasattr(agent_module, "AgentDeployService")


def test_modules_agents_legacy_alias_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("modules.agents")
