"""
ServiceRegistry — backward compatibility re-export.

This module is deprecated. Import from core.service instead:
  from core.service import ServiceRegistry, ServiceMiddleware

Kept for backward compatibility.
"""

import warnings

warnings.warn(
  "core.service_registry is deprecated; use core.service instead",
  DeprecationWarning,
  stacklevel=2,
)

# Backward compatibility: re-export from new package
from core.service import ServiceRegistry, ServiceMiddleware, ServiceFunc

__all__ = ["ServiceRegistry", "ServiceMiddleware", "ServiceFunc"]
