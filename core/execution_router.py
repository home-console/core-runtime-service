"""
ExecutionRouter — Legacy adapter для обратной совместимости.

⚠️ DEPRECATED: Этот класс больше не используется в прод-коде и будет удалён в будущем.

ExecutionControllerImpl используется через runtime.execution_controller.

Этот класс остаётся только для обратной совместимости со старым кодом,
который использует Operation + ProviderMetadata → Dict[str, Any].

Новый код должен использовать ExecutionControllerImpl.execute_operation() напрямую.
"""

import asyncio
import logging
from typing import Any, Callable, Awaitable, Optional, Dict

from core.operations.models import Operation
from core.capability_protocol import ProviderMetadata

logger = logging.getLogger(__name__)


class ExecutionRouterError(Exception):
    """Error in execution routing."""
    pass


class ExecutionRouter:
    """
    Legacy adapter: Operation + ProviderMetadata → ExecutionControllerImpl.
    
    Этот класс адаптирует старый API (Operation + ProviderMetadata → Dict)
    к новому ExecutionControllerImpl (operation_id, operation_type, params, context → OperationResult).
    
    Если ExecutionControllerImpl доступен, использует его.
    Иначе fallback на старый in-process execution.
    """
    
    def __init__(self, runtime: Any):
        """
        Initialize router with runtime context.
        
        ⚠️ DEPRECATED: Этот класс больше не используется в прод-коде.
        Используйте runtime.execution_controller напрямую.
        """
        import warnings
        warnings.warn(
            "ExecutionRouter is deprecated and will be removed in a future version. "
            "Use runtime.execution_controller.execute_operation() directly.",
            DeprecationWarning,
            stacklevel=2
        )
        self.runtime = runtime
        # Храним handlers для fallback (если ExecutionController недоступен)
        self._local_handlers: Dict[str, Callable[[Dict[str, Any], Operation], Awaitable[Dict[str, Any]]]] = {}
        self._handler_lock = asyncio.Lock()
    
    async def register_handler(
        self,
        operation_type: str,
        handler: Callable[[Dict[str, Any], Operation], Awaitable[Dict[str, Any]]]
    ) -> None:
        """
        Register local in-process handler (для fallback).
        
        DEPRECATED: Handlers должны регистрироваться через OperationManager.register_handler().
        """
        async with self._handler_lock:
            self._local_handlers[operation_type] = handler
    
    async def unregister_handler(self, operation_type: str) -> None:
        """Unregister handler."""
        async with self._handler_lock:
            self._local_handlers.pop(operation_type, None)
    
    async def execute(
        self,
        operation: Operation,
        provider_metadata: Optional[ProviderMetadata] = None
    ) -> Dict[str, Any]:
        """
        Execute operation через ExecutionControllerImpl (если доступен) или fallback.
        
        Args:
            operation: Operation to execute
            provider_metadata: Provider metadata with execution config
            
        Returns:
            Result dict: {"success": bool, "result": {...}, "error": "..."}
            
        Raises:
            ExecutionRouterError: if routing or execution fails
        """
        # Определяем режим выполнения
        exec_mode = None
        if provider_metadata:
            exec_mode = getattr(provider_metadata, "execution_mode", None)

        # "in_process" и None — всегда локальный fallback, без контроллера
        if exec_mode in (None, "in_process"):
            return await self._execute_in_process_fallback(operation)

        # Неизвестный режим — немедленно ошибка
        _KNOWN_MODES = {"process", "container"}
        if exec_mode not in _KNOWN_MODES:
            raise ExecutionRouterError(f"Unknown execution mode: {exec_mode!r}")

        # Пытаемся использовать ExecutionControllerImpl если доступен
        controller = self.runtime.execution_controller

        if controller is not None:
            # Используем новый ExecutionController
            try:
                # Конвертируем Operation → execute_operation() параметры
                context = {
                    "runtime": self.runtime,
                    "operation_id": operation.operation_id,
                }
                
                # Добавляем provider metadata в context если есть
                if provider_metadata:
                    context["_execution_policy"] = {
                        "execution_mode": getattr(provider_metadata, "execution_mode", "in_process"),
                        "process_config": getattr(provider_metadata, "process_config", None),
                        "container_config": getattr(provider_metadata, "container_config", None),
                    }
                
                op_res = await controller.execute_operation(
                    operation_id=operation.operation_id,
                    operation_type=operation.type,
                    params=operation.params,
                    context=context,
                )
                
                # Конвертируем OperationResult → Dict
                if op_res.ok:
                    return op_res.result or {}
                else:
                    error_msg = "Execution failed"
                    if op_res.error:
                        error_msg = str(op_res.error.get("message", error_msg))
                    raise ExecutionRouterError(error_msg)
                    
            except ExecutionRouterError:
                raise
            except Exception as e:
                logger.warning(f"ExecutionController failed, falling back to legacy: {e}")
                # Fallback на старый код
                return await self._execute_in_process_fallback(operation)
        else:
            # Fallback: старый in-process execution
            return await self._execute_in_process_fallback(operation)
    
    async def _execute_in_process_fallback(
        self,
        operation: Operation
    ) -> Dict[str, Any]:
        """
        Fallback: execute operation in-process (legacy behavior).
        
        Используется только если ExecutionController недоступен.
        """
        # Find handler with lock protection
        async with self._handler_lock:
            handler = self._local_handlers.get(operation.type)
        
        if not handler:
            raise ExecutionRouterError(f"No handler registered for {operation.type}")
        
        # Prepare context
        context = {
            "runtime": self.runtime,
            "operation_id": operation.operation_id
        }
        
        # Execute - return result directly, wrapping handler errors
        try:
            result = await handler(context, operation)
        except ExecutionRouterError:
            raise
        except Exception as e:
            raise ExecutionRouterError(f"Handler raised: {e}") from e
        return result
