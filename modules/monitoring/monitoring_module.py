from typing import Any
import asyncio
import time

from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import Counter, Gauge, Histogram
from fastapi import APIRouter, Response


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

    async def metrics_endpoint(self) -> Response:
        self.uptime.set(time.time() - self._start_time)
        data = generate_latest(self.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    async def health_endpoint(self) -> dict:
        self.health_requests_total.inc()
        checks = {"status": "ok", "uptime": time.time() - self._start_time}
        
        # Check storage if runtime available
        if self.runtime:
            try:
                await self.runtime.storage.get("health_check", "test")
                checks["storage"] = "ok"
            except Exception as e:
                checks["storage"] = "error"
                checks["storage_error"] = str(e)
                checks["status"] = "degraded"
        
        return checks
