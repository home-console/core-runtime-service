"""
ModuleManager — backward compatibility re-export.

This module is deprecated. Import from core.module instead:
  from core.module import ModuleManager, ModuleSpec

Kept for backward compatibility.
"""

import warnings

warnings.warn(
  "core.module_manager is deprecated; use core.module instead",
  DeprecationWarning,
  stacklevel=2,
)

# Backward compatibility: re-export from new package
from core.module import ModuleManager, ModuleSpec

__all__ = ["ModuleManager", "ModuleSpec"]
