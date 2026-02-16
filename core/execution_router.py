"""
ExecutionRouter — маршрутизация выполнения операций на основе execution_mode.

Plugin Isolation — распределённое выполнение плагинов
в разных контекстах: in-process, subprocess, container, remote.

Поддерживает:
- in_process: Прямой вызов (как сейчас)
- process: Запуск через subprocess с JSON протоколом
- container: Запуск через docker/podman
- remote: HTTP запрос (уже реализовано)

Все остатко остаётся уровня Operation — не меняет Capability Protocol v1.
"""

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Awaitable, Optional, Dict
from dataclasses import asdict

from core.operations import Operation
from core.capability_protocol import ProviderMetadata

logger = logging.getLogger(__name__)


class ExecutionRouterError(Exception):
    """Error in execution routing."""
    pass


class ExecutionRouter:
    """Route operation execution based on execution_mode."""
    
    def __init__(self, runtime: Any):
        """Initialize router with runtime context."""
        self.runtime = runtime
        self._local_handlers: Dict[str, Callable[[Dict[str, Any], Operation], Awaitable[Dict[str, Any]]]] = {}
        self._handler_lock = threading.Lock()  # P0 Hardening: Protect from concurrent access
    
    def register_handler(
        self,
        operation_type: str,
        handler: Callable[[Dict[str, Any], Operation], Awaitable[Dict[str, Any]]]
    ) -> None:
        """Register local in-process handler (thread-safe)."""
        with self._handler_lock:
            self._local_handlers[operation_type] = handler
    
    def unregister_handler(self, operation_type: str) -> None:
        """Unregister handler (thread-safe)."""
        with self._handler_lock:
            self._local_handlers.pop(operation_type, None)
    
    async def execute(
        self,
        operation: Operation,
        provider_metadata: Optional[ProviderMetadata] = None
    ) -> Dict[str, Any]:
        """
        Route and execute operation based on execution_mode.
        
        Args:
            operation: Operation to execute
            provider_metadata: Provider metadata with execution config
            
        Returns:
            Result dict: {"success": bool, "result": {...}, "error": "..."}
            
        Raises:
            ExecutionRouterError: if routing or execution fails
        """
        # Determine execution mode
        execution_mode = "in_process"  # default
        if provider_metadata:
            execution_mode = getattr(provider_metadata, "execution_mode", "in_process")
        
        try:
            if execution_mode == "in_process":
                return await self._execute_in_process(operation, provider_metadata)
            
            elif execution_mode == "process":
                return await self._execute_process(operation, provider_metadata)
            
            elif execution_mode == "container":
                return await self._execute_container(operation, provider_metadata)
            
            elif execution_mode == "remote":
                # Remote execution handled by OperationManager, fallback for now
                return await self._execute_remote(operation, provider_metadata)
            
            else:
                raise ExecutionRouterError(f"Unknown execution_mode: {execution_mode}")
        
        except ExecutionRouterError:
            raise
        except Exception as e:
            logger.error(f"Execution error: {str(e)}")
            raise ExecutionRouterError(f"Execution failed: {str(e)}")
    
    async def _execute_in_process(
        self,
        operation: Operation,
        provider_metadata: Optional[ProviderMetadata]
    ) -> Dict[str, Any]:
        """Execute operation in-process (direct handler call)."""
        # Find handler with lock protection (P0: race condition fix)
        with self._handler_lock:
            handler = self._local_handlers.get(operation.type)
        if not handler:
            raise ExecutionRouterError(f"No handler registered for {operation.type}")
        
        # Prepare context
        context = {
            "runtime": self.runtime,
            "operation_id": operation.operation_id
        }
        
        # Execute - return result directly (not wrapped)
        result = await handler(context, operation)
        return result
    
    async def _execute_process(
        self,
        operation: Operation,
        provider_metadata: Optional[ProviderMetadata]
    ) -> Dict[str, Any]:
        """Execute operation via subprocess."""
        from core.process_executor import ProcessExecutor
        
        executor = ProcessExecutor(self.runtime)
        config = {}
        if provider_metadata and provider_metadata.process_config:
            config = provider_metadata.process_config
        
        return await executor.execute(operation, config)
    
    async def _execute_container(
        self,
        operation: Operation,
        provider_metadata: Optional[ProviderMetadata]
    ) -> Dict[str, Any]:
        """Execute operation in container."""
        from core.container_executor import ContainerExecutor
        
        executor = ContainerExecutor(self.runtime)
        config = {}
        if provider_metadata and provider_metadata.container_config:
            config = provider_metadata.container_config
        
        return await executor.execute(operation, config)
    
    async def _execute_remote(
        self,
        operation: Operation,
        provider_metadata: Optional[ProviderMetadata]
    ) -> Dict[str, Any]:
        """Fallback to remote execution."""
        # Remote execution normally handled by OperationManager._execute_remote_operation
        # This is a fallback if called directly
        raise ExecutionRouterError("Remote execution should be handled by OperationManager")
