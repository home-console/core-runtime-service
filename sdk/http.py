"""
HTTP endpoint models — re-exported from core for plugin use.

Plugins should import from sdk, not from core directly.
"""

from core.http.models import HttpEndpoint, EndpointAuthConfig, EndpointParamMapping

__all__ = ["HttpEndpoint", "EndpointAuthConfig", "EndpointParamMapping"]
