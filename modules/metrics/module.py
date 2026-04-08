from __future__ import annotations

from typing import Any

from core.observability.metrics import MetricsRegistry
from core.runtime.runtime_module import RuntimeModule
from modules.hooks.system import register_system_hook, unregister_system_hook
from modules.hooks.runtime_contract import ensure_runtime_execution_contract
import logging
logger = logging.getLogger(__name__)


class MetricsModule(RuntimeModule):
    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._hook_bindings: list[tuple[str, Any]] = []
        # Get metrics registry from runtime (dependency injection)
        self._metrics: MetricsRegistry = getattr(runtime, "_metrics_registry", None)
        if self._metrics is None:
            # Fallback for tests/backward compat
            self._metrics = MetricsRegistry()

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
        operation_type = getattr(operation, "type", "unknown")
        self._metrics.increment_counter("operations_total", label_value=operation_type)
        started_at = getattr(operation, "started_at", None)
        finished_at = getattr(operation, "finished_at", None)
        if started_at is not None and finished_at is not None:
            try:
                self._metrics.observe_histogram(
                    "operation_latency_seconds",
                    max(0.0, float(finished_at) - float(started_at)),
                )
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)
        return None

    async def _on_failure(self, ctx: dict[str, Any]):
        operation = ctx.get("operation")
        if operation is None:
            return None
        operation_type = getattr(operation, "type", "unknown")
        self._metrics.increment_counter("operations_total", label_value=operation_type)
        self._metrics.increment_counter("operations_failed_total", label_value=operation_type)
        started_at = getattr(operation, "started_at", None)
        finished_at = getattr(operation, "finished_at", None)
        if started_at is not None and finished_at is not None:
            try:
                self._metrics.observe_histogram(
                    "operation_latency_seconds",
                    max(0.0, float(finished_at) - float(started_at)),
                )
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)
        return None
