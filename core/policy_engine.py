"""
PolicyEngine backward compatibility wrapper.

Use core.policy package for canonical imports.
"""

import warnings

warnings.warn(
    "core.policy_engine is deprecated; use core.policy instead",
    DeprecationWarning,
    stacklevel=2,
)

from core.policy import (
    Policy,
    DevicePolicy,
    AdminOnlyPolicy,
    PolicyEngine,
    get_policy_engine,
    set_policy_engine,
)

__all__ = [
    "Policy",
    "DevicePolicy",
    "AdminOnlyPolicy",
    "PolicyEngine",
    "get_policy_engine",
    "set_policy_engine",
]
