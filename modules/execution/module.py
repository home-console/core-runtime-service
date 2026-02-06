"""
ExecutionModule (D3) — подключаемый слой исполнения operations.

Ключевая идея:
- НЕ меняем Core (core/), SDK, automation, UI
- Встраиваем execution как RuntimeModule, который приложение может включить/выключить
- Единственная точка интеграции: перехват `runtime.operations.execute()`
  и делегирование в `execution.controller.ExecutionControllerImpl`

Core не знает про process/container/docker — это знания backends, которые живут вне core/.
"""

from __future__ import annotations

import time
from typing import Any, Optional, Callable, Awaitable

from core.runtime_module import RuntimeModule
from core.operations import Operation, OperationStatus, OperationError

from execution.controller import ExecutionControllerImpl


class ExecutionModule(RuntimeModule):
    @property
    def name(self) -> str:
        return "execution"

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._original_execute: Optional[Callable[[Operation], Awaitable[Operation]]] = None
        self._controller: Optional[ExecutionControllerImpl] = None

    async def register(self) -> None:
        # Создаём controller и публикуем в runtime как расширение (не Core API).
        self._controller = ExecutionControllerImpl(self.runtime)
        setattr(self.runtime, "execution_controller", self._controller)

        ops_mgr = getattr(self.runtime, "operations", None)
        if ops_mgr is None:
            return

        # Operation: execution.cancel (D3.4)
        async def _handle_execution_cancel(params: dict, context: dict) -> dict:
            execution_id = params.get("execution_id")
            if not execution_id:
                return {"status": "error", "error": {"code": "missing_execution_id", "message": "execution_id is required"}}

            controller: ExecutionControllerImpl = getattr(self.runtime, "execution_controller", None)
            if controller is None:
                return {"status": "error", "error": {"code": "no_execution_controller", "message": "Execution controller not available"}}

            accepted = await controller.cancel_execution(execution_id=str(execution_id), reason="user")
            return {
                "status": "cancelled" if accepted else "noop",
                "execution_id": str(execution_id),
            }

        ops_mgr.register_handler("execution.cancel", _handle_execution_cancel)

        if self._original_execute is None:
            self._original_execute = ops_mgr.execute

        async def _execute_with_execution(operation: Operation) -> Operation:
            """
            Обёртка вокруг OperationManager.execute:
            validate → mark running → delegate to execution_controller → persist.

            Важно: `InProcessBackend` НЕ вызывает ops_mgr.execute(), а обращается
            напрямую к handlers, чтобы избежать рекурсии.
            """
            try:
                # 1) Validate (как в core.operations.OperationManager.execute)
                handlers = getattr(ops_mgr, "_handlers", {})
                if operation.type not in handlers:
                    operation.status = OperationStatus.FAILED
                    operation.error = OperationError(
                        code="unknown_operation_type",
                        message=f"No handler for operation type: {operation.type}",
                    )
                    await ops_mgr._persist(operation)  # type: ignore[attr-defined]
                    return operation

                # 2) Mark as running
                operation.status = OperationStatus.RUNNING
                operation.started_at = time.time()
                await ops_mgr._persist(operation)  # type: ignore[attr-defined]

                # 3) Delegate to execution controller (policy + backend)
                controller = getattr(self.runtime, "execution_controller", None)
                if controller is None:
                    # fallback: original behavior (should not happen if module registered)
                    return await self._original_execute(operation)  # type: ignore[misc]

                op_res = await controller.execute_operation(
                    operation_id=operation.operation_id,
                    operation_type=operation.type,
                    params=operation.params,
                    context={"runtime": self.runtime, "operation_id": operation.operation_id},
                )

                if op_res.ok:
                    operation.status = OperationStatus.SUCCESS
                    operation.result = op_res.result or {}
                else:
                    operation.status = OperationStatus.FAILED
                    err = op_res.error or {"code": "execution_error", "message": "Unknown execution error"}
                    operation.error = OperationError(code=str(err.get("code", "execution_error")), message=str(err.get("message", "")), details=err)

                operation.finished_at = time.time()
            except Exception as e:
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(code="execution_error", message=str(e))
                operation.finished_at = time.time()

            await ops_mgr._persist(operation)  # type: ignore[attr-defined]
            return operation

        # Monkeypatch: operations subsystem делегирует сюда, не зная policy/backend.
        ops_mgr.execute = _execute_with_execution  # type: ignore[assignment]

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        # Восстанавливаем оригинальный execute, если он был перехвачен.
        ops_mgr = getattr(self.runtime, "operations", None)
        if ops_mgr is not None and self._original_execute is not None:
            ops_mgr.execute = self._original_execute  # type: ignore[assignment]

