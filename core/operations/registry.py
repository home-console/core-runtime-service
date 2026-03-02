"""
OperationHandlerRegistry - реестр обработчиков операций.

Отвечает за регистрацию и поиск обработчиков операций по типу.
"""

import threading
from typing import Any, Dict, Optional, List, Callable, Awaitable

from core.operations.models import Operation


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
        with self._handlers_lock:
            # Strategy 1: Direct lookup (backward compatibility)
            if operation_type in self._handlers:
                return self._handlers[operation_type]
        
        # Strategy 2: Capability-based lookup (outside lock, for CapabilityRegistry)
        # Try to find provider through capability registry
        try:
            if runtime and hasattr(runtime, 'capability_registry') and runtime.capability_registry:
                cap_reg = runtime.capability_registry
                providers = cap_reg.get_providers(operation_type)
                
                if providers:
                    # Get primary provider (first one, or could be configurable)
                    provider_name = providers[0]
                    
                    # Try to find handler registered under provider name + capability
                    # Fallback handler names:
                    # For capability "client.command.execute" and provider "client_manager":
                    # Try: "client_manager.client.command.execute" or
                    #      "client.command.execute" (already tried above)
                    # The handler should be registered under the capability name, 
                    # not provider name + capability
                    # So, if we reached here, handler might not be registered properly
                    
                    # Actually, the handler SHOULD be registered under capability name
                    # in _handlers by the plugin itself. If not found in step 1, it's an error.
                    # But we could also check if handler exists under provider-namespaced name
                    with self._handlers_lock:
                        fallback_type = f"{provider_name}.{operation_type}"
                        if fallback_type in self._handlers:
                            return self._handlers[fallback_type]
        except Exception:
            # Capability registry might not be available - continue
            pass
        
        return None
