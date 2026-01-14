"""Monitoring module: exposes health checks and Prometheus metrics endpoint.

This is a lightweight module intended to be registered with CoreRuntime's
`service_registry` and `ApiModule` to mount `/metrics` and `/health` endpoints.
"""

from .monitoring_module import MonitoringModule

__all__ = ["MonitoringModule"]
