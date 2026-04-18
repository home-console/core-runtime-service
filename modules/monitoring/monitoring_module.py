from typing import Any
import asyncio
import time

from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import Counter, Gauge, Histogram
from fastapi import APIRouter, Response, Request
import logging
logger = logging.getLogger(__name__)


class MonitoringModule:
    """Minimal MonitoringModule exposing Prometheus metrics and health checks.

    Usage: instantiate and register `router` with your FastAPI app.
    """

    def __init__(self, name: str = "monitoring", runtime: Any = None):
        self.name = name
        self.runtime = runtime
        self.registry = CollectorRegistry()
        self._start_time = time.time()

        # Health metrics
        self.health_requests_total = Counter(
            "hc_health_requests_total",
            "Total health check requests",
            registry=self.registry,
        )
        self.uptime = Gauge("hc_uptime_seconds", "Module uptime seconds", registry=self.registry)

        # Auth metrics
        self.auth_requests_total = Counter(
            "hc_auth_requests_total",
            "Total auth requests",
            ["source", "status"],
            registry=self.registry,
        )
        self.auth_latency = Histogram(
            "hc_auth_latency_seconds",
            "Auth request latency",
            ["source"],
            registry=self.registry,
        )

        self.router = APIRouter()
        self.router.add_api_route("/metrics", self.metrics_endpoint, methods=["GET"])
        self.router.add_api_route("/health", self.health_endpoint, methods=["GET"])

    def _metrics_allowed(self, request: Request) -> bool:
        """
        Protect /metrics:
        - If RUNTIME_METRICS_TOKEN is set: require Authorization: Bearer <token>
        - Otherwise, in production: deny by default
        - In development: allow (for local debugging)
        """
        import os

        token = (os.getenv("RUNTIME_METRICS_TOKEN") or "").strip()
        if token:
            auth = (request.headers.get("authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                provided = auth.split(" ", 1)[1].strip()
                return provided == token
            return False

        env = (os.getenv("RUNTIME_ENV") or "development").lower().strip()
        return env != "production"

    async def metrics_endpoint(self, request: Request) -> Response:
        if not self._metrics_allowed(request):
            return Response(status_code=403, content="Forbidden")
        self.uptime.set(time.time() - self._start_time)
        data = generate_latest(self.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    async def health_endpoint(self) -> dict:
        self.health_requests_total.inc()
        checks = {"status": "ok", "uptime": time.time() - self._start_time}
        
        # Check storage if runtime available
        if self.runtime:
            try:
                # Runtime can expose storage via different surfaces depending on integration.
                # Try a few common ones (best-effort).
                storage = None
                runtime = self.runtime
                if hasattr(runtime, "context") and getattr(runtime, "context", None) is not None:
                    storage = getattr(runtime.context, "storage", None)
                if storage is None:
                    storage = getattr(runtime, "storage", None)
                if storage is None:
                    manager = getattr(runtime, "storage_manager", None)
                    if manager is not None and hasattr(manager, "get_core"):
                        storage = manager.get_core()

                if storage is None:
                    raise RuntimeError("storage not available on runtime")

                await storage.get("health_check", "test")
                checks["storage"] = "ok"
            except Exception as e:
                logger.debug("monitoring_module.health_endpoint: error (using fallback value): %s", e)
                checks["storage"] = "error"
                checks["storage_error"] = str(e)
                checks["status"] = "degraded"
        
        return checks
