"""
HTTP Interface Registry для Core Runtime (Backward Compatibility).

This module is deprecated. Import from core.http instead:
  from core.http import HttpRegistry, HttpEndpoint

Kept for backward compatibility.
"""

import warnings

warnings.warn(
  "core.http_registry is deprecated; use core.http instead",
  DeprecationWarning,
  stacklevel=2,
)

# Backward compatibility: re-export from new package
from core.http import HttpRegistry, HttpEndpoint, EndpointAuthConfig, EndpointParamMapping

__all__ = ["HttpRegistry", "HttpEndpoint", "EndpointAuthConfig", "EndpointParamMapping"]
