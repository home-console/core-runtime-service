"""
DependencyResolver — backward compatibility re-export.

This module is deprecated. Import from core.dependency instead:
  from core.dependency import DependencyResolver, DependencyError

Kept for backward compatibility.
"""

import warnings

warnings.warn(
  "core.dependency_resolver is deprecated; use core.dependency instead",
  DeprecationWarning,
  stacklevel=2,
)

# Backward compatibility: re-export from new package
from core.dependency import DependencyResolver, DependencyError, RuntimeIntegrityError

__all__ = ["DependencyResolver", "DependencyError", "RuntimeIntegrityError"]
