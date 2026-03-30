"""
OperationsComponent — компонент управления операциями и execution.

Отвечает за:
- Управление операциями (operations_manager)
- Выполнение операций (worker)
- Execution controller (execution_controller)

Этот класс инкапсулирует всю логику выполнения операций,
освобождая CoreRuntime от этих обязанностей.
"""

from typing import Any, Optional

from core.operations.manager import OperationManager
from core.operations.worker import OperationWorker


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
                except Exception:
                    pass
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
