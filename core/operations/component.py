"""
OperationsComponent — компонент управления операциями и execution.

Отвечает за:
- Управление операциями (operations_manager)
- Выполнение операций (worker)
- Execution controller (execution_controller)

Этот класс инкапсулирует всю логику выполнения операций,
освобождая CoreRuntime от этих обязанностей.
"""

import asyncio
from typing import Any, Optional

from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS
from core.operations.manager import OperationManager
from core.operations.worker import OperationWorker
import logging
logger = logging.getLogger(__name__)


class OperationsComponent:
    """
    Компонент управления операциями и execution.

    Отвечает за:
    - Управление операциями (создание, выполнение, отмена)
    - Worker для обработки операций
    - Execution controller для координации

    Использование:
        ops_component = OperationsComponent(runtime)
        await ops_component.manager.create(...)
        await ops_component.worker.execute_operation_now(...)
    """

    def __init__(self, runtime: Any):
        """
        Инициализация компонента операций.

        Args:
            runtime: экземпляр CoreRuntime (или совместимый объект)
                     используется для создания OperationManager и OperationWorker
        """
        # Operation Manager — управление операциями
        self.manager = OperationManager(runtime)

        # Operation Worker — выполнение операций
        self.worker: Optional[OperationWorker] = None
        self._worker_task: Optional[Any] = None

        # Execution Controller — координация выполнения
        # Выставляется модулем execution извне
        self.execution_controller: Optional[Any] = None

    async def start_worker(self) -> None:
        """
        Запустить worker для обработки операций.

        Вызывается при старте runtime.
        """
        if self.worker is None:
            self.worker = OperationWorker(self)
            # Worker запускается в фоне через runtime
            # Это делается в lifecycle mixin

    async def stop_worker(self) -> None:
        """
        Остановить worker.

        Вызывается при остановке runtime.
        """
        if self.worker is not None:
            self.worker.running = False
            if self._worker_task is not None:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:  # allow_cancelled_suppress
                    pass
                except BEST_EFFORT_BACKGROUND_ERRORS:
                    logger.warning(
                        "component.stop_worker: worker task finished with error",
                        exc_info=True,
                    )
            self.worker = None
            self._worker_task = None

    def create_context(self) -> dict[str, Any]:
        """
        Создать контекст компонента операций.

        Возвращает основные компоненты для работы с операциями.

        Returns:
            Словарь с компонентами операций
        """
        return {
            "operations_manager": self.manager,
            "worker": self.worker,
            "execution_controller": self.execution_controller,
        }

    # --- Public facade delegating to manager ---

    def register_handler(self, op_type: str, handler: Any) -> None:
        self.manager.register_handler(op_type, handler)

    def unregister_handler(self, op_type: str) -> None:
        self.manager.unregister_handler(op_type)

    def list_handler_types(self) -> list[str]:
        return self.manager.list_handler_types()

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        return await self.manager.create(*args, **kwargs)

    async def get(self, operation_id: str) -> Any:
        return await self.manager.get(operation_id)

    async def list(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> list[Any]:
        return await self.manager.list(limit=limit, offset=offset, status=status)

    async def persist(self, operation: Any) -> None:
        await self.manager.persist_operation(operation)

    async def persist_operation(self, operation: Any) -> None:
        await self.manager.persist_operation(operation)

    async def ensure_attempt_created(
        self,
        attempt_id: str,
        operation_id: str,
        attempt_index: int,
    ) -> None:
        await self.manager.ensure_attempt_created(attempt_id, operation_id, attempt_index)

    async def try_claim_attempt(
        self,
        attempt_id: str,
        worker_id: str,
        lease_ttl: int,
    ) -> tuple[bool, Optional[str]]:
        return await self.manager.try_claim_attempt(attempt_id, worker_id, lease_ttl)

    async def get_attempt(self, attempt_id: str) -> Any:
        return await self.manager.get_attempt(attempt_id)

    async def persist_attempt(self, attempt: Any) -> None:
        await self.manager.persist_attempt(attempt)

    def get_executor(self) -> Any:
        return self.manager.get_executor()

    async def execute(self, operation: Any) -> Any:
        """Execute an operation."""
        return await self.manager.execute(operation)

    @property
    def _storage(self) -> Any:
        return self.manager._storage

    @property
    def _executor(self) -> Any:
        return self.manager._executor
