"""
OperationHandlerRegistry - реестр обработчиков операций.

Отвечает за регистрацию и поиск обработчиков операций по типу.
"""

import threading
from typing import Any, Dict, Optional, List, Callable, Awaitable

from core.operations.models import Operation

OperationHandler = Callable[[dict[str, Any]], Awaitable[Any]]

_operation_registry: Dict[str, OperationHandler] = {}


def register_operation_handler(op_type: str, handler: OperationHandler) -> None:
    _operation_registry[op_type] = handler


def get_operation_handler(op_type: str) -> OperationHandler | None:
    return _operation_registry.get(op_type)


class OperationHandlerRegistry:
    """
    Реестр обработчиков операций.
    
    Хранит mapping: operation_type -> handler function.
    Thread-safe для параллельного доступа.
    """
    
    def __init__(self, execution_router: Optional[Any] = None):
        """
        Инициализация реестра.
        
        Args:
            execution_router: опциональный ExecutionRouter для обратной совместимости
        """
        # Type name -> handler (async callable)
        self._handlers: Dict[str, Callable[[Any, Operation], Awaitable[Dict[str, Any]]]] = {}
        # P0 Hardening: Lock for thread-safe access to _handlers
        self._handlers_lock = threading.RLock()
        self._execution_router = execution_router
    
    def register(
        self,
        op_type: str,
        handler: Callable[[Any, Operation], Awaitable[Dict[str, Any]]]
    ) -> None:
        """
        Register handler for operation type.
        
        Handler signature: async def handler(runtime, operation) -> Dict[str, Any]
        
        Args:
            op_type: Operation type name
            handler: Async handler function
        """
        with self._handlers_lock:
            self._handlers[op_type] = handler
            # ExecutionRouter удалён; handler'ы в ExecutionController
    
    def unregister(self, op_type: str) -> None:
        """
        Unregister handler for operation type.
        
        Args:
            op_type: Operation type to unregister
        """
        with self._handlers_lock:
            self._handlers.pop(op_type, None)
            # ExecutionRouter удалён; дерегистрация не нужна
    
    def list_types(self) -> List[str]:
        """
        Return list of registered operation type names (read-only, for Inspector).
        
        Returns:
            List of operation type names
        """
        with self._handlers_lock:
            return list(self._handlers.keys())
    
    def find_handler(
        self,
        operation_type: str,
        runtime: Optional[Any] = None
    ) -> Optional[Callable[[Any, Operation], Awaitable[Dict[str, Any]]]]:
        """
        Find handler for operation type.
        
        Routing strategy:
        1. Try direct lookup in _handlers (backward compatibility)
        2. Try capability-based lookup via CapabilityRegistry
        3. Return None if not found
        
        Args:
            operation_type: Operation type (can be plugin name or capability)
            runtime: опциональный runtime для capability lookup
            
        Returns:
            Handler callable or None
        """
        del runtime
        with self._handlers_lock:
            return self._handlers.get(operation_type)
