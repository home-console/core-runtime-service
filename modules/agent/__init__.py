"""Agent Control Plane Module.

This package is the canonical modules-layer entry point for agent runtime
control plane and agent domain primitives.
"""

from modules.agent.module import AgentControlPlaneModule

# Explicit entrypoint for module discovery
__runtime_module_class__ = AgentControlPlaneModule

from .deploy_service import AgentDeployConfig, AgentDeployService
from .domain import (
    AgentEnrollmentManager,
    AgentIdentity,
    AgentIdentityFactory,
    AgentKeyManager,
    AgentLogStore,
    AgentMetadata,
    AgentPublicKey,
    AgentRegistry,
    AgentStatus,
    DeploymentInfo,
    DeploymentStatus,
    DeploymentTracker,
    EnrollmentToken,
    EnrollmentTokenFactory,
    EnrollmentTokenStatus,
    LogEntry,
    MTLSCertificateAuthority,
)


class AgentModule(AgentControlPlaneModule):
    """Backward-compatible alias for AgentControlPlaneModule."""


__all__ = [
    "AgentControlPlaneModule",
    "AgentModule",
    "AgentDeployConfig",
    "AgentDeployService",
    "AgentIdentity",
    "AgentPublicKey",
    "AgentKeyManager",
    "AgentIdentityFactory",
    "EnrollmentToken",
    "EnrollmentTokenStatus",
    "EnrollmentTokenFactory",
    "AgentEnrollmentManager",
    "MTLSCertificateAuthority",
    "AgentMetadata",
    "AgentStatus",
    "AgentRegistry",
    "DeploymentTracker",
    "DeploymentStatus",
    "DeploymentInfo",
    "AgentLogStore",
    "LogEntry",
]
