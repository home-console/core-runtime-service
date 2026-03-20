"""
Service Registry Package (D2).

Service-based inter-plugin communication:
- registry.py: ServiceRegistry main class
- models.py: ServiceMiddleware ABC and ServiceFunc type

For backward compatibility, ServiceRegistry is re-exported from this package.
"""

from core.service.registry import ServiceRegistry
from core.service.models import ServiceMiddleware, ServiceFunc

__all__ = ["ServiceRegistry", "ServiceMiddleware", "ServiceFunc"]
