from __future__ import annotations

from typing import Any

from core.observability.metrics import get_metrics_registry
from core.runtime_module import RuntimeModule
from modules.hooks.system import register_system_hook, unregister_system_hook
from modules.hooks.runtime_contract import ensure_runtime_execution_contract


class MetricsModule(RuntimeModule):
    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._hook_bindings: list[tuple[str, Any]] = []

    @property
    def name(self) -> str:
        return "metrics"

    async def register(self) -> None:
        ensure_runtime_execution_contract(self.runtime)

        register_system_hook("after_execute", self._after_execute)
        register_system_hook("on_failure", self._on_failure)
        self._hook_bindings.extend(
            [
                ("after_execute", self._after_execute),
                ("on_failure", self._on_failure),
            ]
        )

    async def stop(self) -> None:
        for hook_name, handler in self._hook_bindings:
            unregister_system_hook(hook_name, handler)
        self._hook_bindings.clear()

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
