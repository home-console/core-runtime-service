"""
OperationsModule — runtime module for operations subsystem.

Registers operations manager, handlers, and services.
Exposes API for operation CRUD and execution.
"""

from typing import Any, Dict, Optional
from core.runtime_module import RuntimeModule
from core.operations import (
    OperationManager, OperationInitiator, OperationInitiatorKind,
    OperationStatus, OperationError, RETRYABLE_ERRORS
)


class OperationsModule(RuntimeModule):
    """
    Operations subsystem module.
    
    - Manages operation lifecycle
    - Registers operation type handlers
    - Provides API for operation management
    """
    
    @property
    def name(self) -> str:
        return "operations"
    
    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self.manager: Optional[OperationManager] = None
    
    async def register(self) -> None:
        """Register operations manager and handlers."""
        # Create manager
        self.manager = OperationManager(self.runtime)
        
        # Store in runtime for access
        self.runtime.operations = self.manager
        
        # Register handlers
        await self._register_handlers()
        
        # Register services
        await self._register_services()
    
    async def start(self) -> None:
        """Start operations module."""
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Operations module started",
                module="operations"
            )
        except Exception:
            pass
    
    async def stop(self) -> None:
        """Stop operations module."""
        pass
    
    async def _register_handlers(self) -> None:
        """Register handlers for each operation type."""
        from modules.operations import handlers
        
        # Device operations
        self.manager.register_handler(
            "device.set_state",
            handlers.handle_device_set_state
        )
        
        # Yandex operations
        self.manager.register_handler(
            "yandex.sync",
            handlers.handle_yandex_sync
        )
        self.manager.register_handler(
            "yandex.check_devices_online",
            handlers.handle_yandex_check_online
        )
        
        # OAuth operations
        self.manager.register_handler(
            "oauth.refresh_token",
            handlers.handle_oauth_refresh
        )
        
        # Mapping operations
        self.manager.register_handler(
            "mappings.create",
            handlers.handle_mappings_create
        )
        self.manager.register_handler(
            "mappings.delete",
            handlers.handle_mappings_delete
        )
        self.manager.register_handler(
            "mappings.auto",
            handlers.handle_mappings_auto
        )
    
    async def _register_services(self) -> None:
        """Register operation management services."""
        
        async def operations_create(op_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
            """Create and execute operation."""
            if self.manager is None:
                raise RuntimeError("Operations manager not initialized")
            
            # TODO: Get initiator from context (admin vs system)
            initiator = OperationInitiator(
                kind=OperationInitiatorKind.ADMIN,
                user_id=None  # Will be set from RequestContext
            )
            
            operation = await self.manager.create(
                op_type=op_type,
                params=params,
                initiator=initiator,
            )
            
            # Execute synchronously
            result = await self.manager.execute(operation)
            
            return {
                "operation_id": result.operation_id,
                "status": result.status.value,
                "result": result.result,
                "error": result.error.to_dict() if result.error else None,
            }
        
        async def operations_list(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
            """List operations."""
            if self.manager is None:
                raise RuntimeError("Operations manager not initialized")
            
            ops = await self.manager.list(limit=limit, offset=offset)
            return {
                "ok": True,
                "operations": [op.to_dict() for op in ops],
                "total": len(ops),
            }
        
        async def operations_get(operation_id: str) -> Dict[str, Any]:
            """Get operation details."""
            if self.manager is None:
                raise RuntimeError("Operations manager not initialized")
            
            op = await self.manager.get(operation_id)
            if not op:
                raise ValueError(f"Operation {operation_id} not found")
            
            return op.to_dict()
        
        async def operations_cancel(operation_id: str) -> Dict[str, Any]:
            """Cancel operation."""
            if self.manager is None:
                raise RuntimeError("Operations manager not initialized")
            
            op = await self.manager.cancel(operation_id)
            if not op:
                raise ValueError(f"Operation {operation_id} not found")
            
            return {
                "ok": True,
                "operation": op.to_dict(),
            }
        
        async def operations_retry(operation_id: str) -> Dict[str, Any]:
            """Retry failed operation."""
            if self.manager is None:
                raise RuntimeError("Operations manager not initialized")
            
            new_op = await self.manager.retry(operation_id)
            if not new_op:
                raise ValueError(
                    f"Cannot retry operation {operation_id} "
                    "(not failed or error not retryable)"
                )
            
            # Execute new operation
            result = await self.manager.execute(new_op)
            
            return {
                "ok": True,
                "new_operation_id": result.operation_id,
                "status": result.status.value,
                "result": result.result,
                "error": result.error.to_dict() if result.error else None,
            }
        
        # Register services (admin-only)
        reg = self.runtime.service_registry
        
        await reg.register_with_acl("operations.create", operations_create, admin_only=True)
        await reg.register_with_acl("operations.list", operations_list, admin_only=True)
        await reg.register_with_acl("operations.get", operations_get, admin_only=True)
        await reg.register_with_acl("operations.cancel", operations_cancel, admin_only=True)
        await reg.register_with_acl("operations.retry", operations_retry, admin_only=True)
