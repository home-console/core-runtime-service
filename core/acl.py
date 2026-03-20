"""
ACL helper backward compatibility wrapper.

Use core.policy ACL helpers for canonical imports.
"""

import warnings

warnings.warn(
    "core.acl is deprecated; use core.policy ACL helpers instead",
    DeprecationWarning,
    stacklevel=2,
)

from core.policy import (
    is_privileged,
    enforce_admin,
    enforce_policy,
    filter_with_policy,
    current_context,
)

__all__ = [
    "is_privileged",
    "enforce_admin",
    "enforce_policy",
    "filter_with_policy",
    "current_context",
]

