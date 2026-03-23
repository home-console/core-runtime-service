from __future__ import annotations

from typing import Any

from core.observability.metrics import get_metrics_registry
from core.runtime_module import RuntimeModule
from modules.hooks.system import register_system_hook


class MetricsModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "metrics"

    async def register(self) -> None:
        register_system_hook("after_execute", self._after_execute)
        register_system_hook("on_failure", self._on_failure)

    async def _after_execute(self, ctx: dict[str, Any]):
        operation = ctx.get("operation")
        if operation is None:
            return None
        metrics = get_metrics_registry()
        operation_type = getattr(operation, "type", "unknown")
        metrics.increment_counter("operations_total", label_value=operation_type)
        started_at = getattr(operation, "started_at", None)
        finished_at = getattr(operation, "finished_at", None)
        if started_at is not None and finished_at is not None:
            try:
                metrics.observe_histogram(
                    "operation_latency_seconds",
                    max(0.0, float(finished_at) - float(started_at)),
                )
            except Exception:
                pass
        return None

    async def _on_failure(self, ctx: dict[str, Any]):
        operation = ctx.get("operation")
        if operation is None:
            return None
        metrics = get_metrics_registry()
        operation_type = getattr(operation, "type", "unknown")
        metrics.increment_counter("operations_total", label_value=operation_type)
        metrics.increment_counter("operations_failed_total", label_value=operation_type)
        started_at = getattr(operation, "started_at", None)
        finished_at = getattr(operation, "finished_at", None)
        if started_at is not None and finished_at is not None:
            try:
                metrics.observe_histogram(
                    "operation_latency_seconds",
                    max(0.0, float(finished_at) - float(started_at)),
                )
            except Exception:
                pass
        return None