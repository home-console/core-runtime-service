"""
Execution controller (D3).

Controller:
- не знает домены
- не знает плагины (кроме optional metadata)
- не знает automation
- работает только с operation envelope + policy + backend registry
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from .backend import BackendId, ExecutionBackend, InProcessBackend, ProcessBackend, ContainerBackend, OperationEnvelope, OperationResult
from .policy import ExecutionPolicy, StateExecutionPolicy


class ExecutionController(Protocol):
    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult: ...


class ExecutionControllerImpl:
    def __init__(
        self,
        runtime: Any,
        policy: Optional[ExecutionPolicy] = None,
        backends: Optional[Dict[BackendId, ExecutionBackend]] = None,
        *,
        policy_storage_namespace: str = "execution",
        policy_storage_key: str = "policy",
    ):
        self._runtime = runtime
        self._policy = policy or StateExecutionPolicy(runtime)
        self._policy_ns = policy_storage_namespace
        self._policy_key = policy_storage_key

        self._backends: Dict[BackendId, ExecutionBackend] = backends or {
            "in_process": InProcessBackend(runtime),
            "process": ProcessBackend(),
            "container": ContainerBackend(),
        }

    async def _load_policy(self) -> Dict[str, Any]:
        """
        Загружает декларативный policy из storage, чтобы можно было менять без рестарта.
        """
        try:
            storage = getattr(self._runtime, "storage", None)
            if storage is None:
                return {}
            raw = await storage.get(self._policy_ns, self._policy_key)
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {}

    async def execute_operation(
        self,
        operation_id: str,
        operation_type: str,
        params: dict,
        context: dict,
    ) -> OperationResult:
        # controller не должен делать доменные вызовы; только policy+backend
        policy_dict = await self._load_policy()

        metadata: Dict[str, Any] = {
            "_execution_policy": policy_dict,
        }

        plugin_name = None
        try:
            plugin_name = (context or {}).get("plugin_name")
        except Exception:
            plugin_name = None

        backend_id = self._policy.select_backend(operation_type, plugin_name, metadata)
        backend = self._backends.get(backend_id)
        if backend is None:
            return OperationResult(
                ok=False,
                error={"code": "unknown_backend", "message": f"Unknown backend: {backend_id}"},
                backend=str(backend_id),
            )

        envelope = OperationEnvelope(
            operation_id=operation_id,
            operation_type=operation_type,
            params=params or {},
            context=context or {},
            metadata=metadata,
        )
        return await backend.execute(envelope)

