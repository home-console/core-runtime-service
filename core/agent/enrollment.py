"""
Compatibility shim for `core.agent.enrollment`.

Re-exports classes from `modules.agent.enrollment`.
"""

from modules.agent.enrollment import (
    AgentEnrollmentManager,
    EnrollmentToken,
    EnrollmentTokenFactory,
    EnrollmentTokenStatus,
)

__all__ = [
    "AgentEnrollmentManager",
    "EnrollmentToken",
    "EnrollmentTokenFactory",
    "EnrollmentTokenStatus",
]
