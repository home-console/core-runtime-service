"""
OperationHandlerRegistry - реестр обработчиков операций.

Отвечает за регистрацию и поиск обработчиков операций по типу.
"""

import threading
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.operations.models import Operation


class OperationHandlerRegistry:
    """
    Реестр обработчиков операций.
    
    Хранит mapping: operation_type -> handler function.
    Thread-safe для параллельного доступа.
    """
    
    def __init__(self):
        """
        Инициализация реестра.
        """
        # Type name -> handler (async callable)
        self._handlers: Dict[str, Callable[[Any, Operation], Awaitable[Dict[str, Any]]]] = {}
        # P0 Hardening: Lock for thread-safe access to _handlers
        self._handlers_lock = threading.RLock()
    
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
    ) -> Optional[Callable[[Any, Operation], Awaitable[Dict[str, Any]]]]:
        """
        Find handler for operation type.

        Args:
            operation_type: Operation type name

        Returns:
            Handler callable or None
        """
        with self._handlers_lock:
            return self._handlers.get(operation_type)
