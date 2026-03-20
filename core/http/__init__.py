"""
HTTP Registry Package (D2).

Metadata registry for HTTP contracts:
- registry.py: HttpRegistry main class
- models.py: HttpEndpoint, EndpointAuthConfig, EndpointParamMapping

For backward compatibility, HttpRegistry is re-exported from this package.
"""

from core.http.registry import HttpRegistry
from core.http.models import HttpEndpoint, EndpointAuthConfig, EndpointParamMapping

__all__ = ["HttpRegistry", "HttpEndpoint", "EndpointAuthConfig", "EndpointParamMapping"]
