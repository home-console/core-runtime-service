"""Step 15: Agent module — Secure Agent Enrollment & Control Plane."""

from core.agent.identity import (
    AgentIdentity,
    AgentPublicKey,
    AgentKeyManager,
    AgentIdentityFactory,
)
from core.agent.enrollment import (
    EnrollmentToken,
    EnrollmentTokenStatus,
    EnrollmentTokenFactory,
    AgentEnrollmentManager,
)
from core.agent.tls import (
    MTLSCertificateAuthority,
)
from core.agent.registry import (
    AgentMetadata,
    AgentStatus,
    AgentRegistry,
)

__all__ = [
    # Identity
    "AgentIdentity",
    "AgentPublicKey",
    "AgentKeyManager",
    "AgentIdentityFactory",
    # Enrollment
    "EnrollmentToken",
    "EnrollmentTokenStatus",
    "EnrollmentTokenFactory",
    "AgentEnrollmentManager",
    # mTLS
    "MTLSCertificateAuthority",
    # Registry
    "AgentMetadata",
    "AgentStatus",
    "AgentRegistry",
]
