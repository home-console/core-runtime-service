"""
Operations subsystem — first-class entity for all system-level actions.

Operation is immutable audit trail + execution context.
All critical actions MUST be executed through operations.

Поддерживает Capability Protocol v1:
- Remote provider health monitoring
- Retryable error handling
- Timeout enforcement
"""

import uuid
import time
import threading
from typing import Any, Dict, Optional, List, Callable, Awaitable
from enum import Enum
from dataclasses import dataclass, asdict

from core.health_monitor import ProviderHealthMonitor
from core import capability_protocol


class OperationStatus(Enum):
    """Operation lifecycle statuses."""
    PENDING = "pending"      # Created, not yet started
    RUNNING = "running"      # Currently executing
    SUCCESS = "success"      # Completed successfully
    FAILED = "failed"        # Execution failed
    CANCELLED = "cancelled"  # User cancelled


class OperationInitiatorKind(Enum):
    """Who initiated the operation."""
    ADMIN = "admin"      # Explicit admin action
    SYSTEM = "system"    # Background/automatic action


@dataclass
class OperationError:
    """Error details for failed operation."""
    code: str                    # Retryable? Transient? UserError?
    message: str
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            **({"details": self.details} if self.details else {})
        }


@dataclass
class OperationInitiator:
    """Who initiated this operation."""
    kind: OperationInitiatorKind
    user_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            **({"user_id": self.user_id} if self.user_id else {})
        }


class Operation:
    """
    First-class operation entity.
    
    Immutable once created, status transitions are the only mutations.
    Every critical action is tracked as operation.
    """
    
    def __init__(
        self,
        operation_id: str,
        op_type: str,
        params: Dict[str, Any],
        initiator: OperationInitiator,
        parent_operation_id: Optional[str] = None,
    ):
        # Immutable fields
        self.operation_id = operation_id
        self.type = op_type
        self.params = params
        self.initiator = initiator
        self.parent_operation_id = parent_operation_id  # For retries
        
        # Timestamps
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        
        # Status + Result
        self.status = OperationStatus.PENDING
        self.error: Optional[OperationError] = None
        self.result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize operation to dict."""
        data = {
            "operation_id": self.operation_id,
            "type": self.type,
            "params": self.params,
            "initiator": self.initiator.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        
        if self.error:
            data["error"] = self.error.to_dict()
        
        if self.result:
            data["result"] = self.result
        
        if self.parent_operation_id:
            data["parent_operation_id"] = self.parent_operation_id
        
        return data
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Operation":
        """Deserialize operation from dict."""
        initiator_data = data.get("initiator", {})
        initiator = OperationInitiator(
            kind=OperationInitiatorKind(initiator_data.get("kind", "system")),
            user_id=initiator_data.get("user_id")
        )
        
        op = Operation(
            operation_id=data["operation_id"],
            op_type=data["type"],
            params=data.get("params", {}),
            initiator=initiator,
            parent_operation_id=data.get("parent_operation_id")
        )
        
        op.status = OperationStatus(data.get("status", "pending"))
        op.created_at = data.get("created_at", time.time())
        op.started_at = data.get("started_at")
        op.finished_at = data.get("finished_at")
        op.result = data.get("result")
        
        if "error" in data and data["error"]:
            error_data = data["error"]
            op.error = OperationError(
                code=error_data.get("code"),
                message=error_data.get("message"),
                details=error_data.get("details")
            )
        
        return op


class OperationManager:
    """
    Manages operation lifecycle: create, execute, store, query.
    
    Поддерживает Capability Protocol v1:
    - Health monitoring for remote providers
    - Retryable error handling
    - Timeout enforcement from manifest
    
    Coordinates:
    - Operation registry (types)
    - Storage persistence
    - Execution pipeline
    - Audit trail
    """
    
    def __init__(self, runtime: Any):
        self.runtime = runtime
        # Type name -> handler (async callable)
        self._handlers: Dict[str, Callable[[Any, Operation], Awaitable[Dict[str, Any]]]] = {}
        # P0 Hardening: Lock for thread-safe access to _handlers
        self._handlers_lock = threading.RLock()
        # Error codes that allow retry
        self._retryable_errors = {
            "timeout", "transient", "network", "device_offline", "integration_unavailable"
        }
        # Health monitor for remote providers (Protocol v1)
        self._health_monitor = ProviderHealthMonitor()
        # Execution router for plugin isolation
        from core.execution_router import ExecutionRouter
        self._execution_router = ExecutionRouter(runtime)
    
    def register_handler(
        self,
        op_type: str,
        handler: Callable[[Any, Operation], Awaitable[Dict[str, Any]]]
    ) -> None:
        """
        Register handler for operation type.
        
        Handler signature: async def handler(runtime, operation) -> Dict[str, Any]
        """
        with self._handlers_lock:
            self._handlers[op_type] = handler
            # Also register with ExecutionRouter for isolation support
            self._execution_router.register_handler(op_type, handler)

    def unregister_handler(self, op_type: str) -> None:
        """
        Unregister handler for operation type.
        
        Args:
            op_type: Operation type to unregister
        """
        with self._handlers_lock:
            self._handlers.pop(op_type, None)
            # Also unregister from ExecutionRouter (P0: race condition fix)
            self._execution_router.unregister_handler(op_type)

    def list_handler_types(self) -> List[str]:
        """Return list of registered operation type names (read-only, for Inspector)."""
        with self._handlers_lock:
            return list(self._handlers.keys())

    def _find_handler(self, operation_type: str) -> Optional[Callable[[Any, Operation], Awaitable[Dict[str, Any]]]]:
        """
        Find handler for operation type.
        
        Routing strategy:
        1. Try direct lookup in _handlers (backward compatibility)
        2. Try capability-based lookup via CapabilityRegistry
        3. Return None if not found
        
        Args:
            operation_type: Operation type (can be plugin name or capability)
            
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
            if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                cap_reg = self.runtime.capability_registry
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

    def _find_remote_provider(self, operation_type: str) -> Optional[Dict[str, Any]]:
        """
        Find remote provider for operation type (capability).
        
        Args:
            operation_type: Operation type (should be capability name)
            
        Returns:
            Provider info dict: {"name": "...", "type": "remote", "remote_config": {...}}
            or None if no remote provider found
        """
        try:
            if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                cap_reg = self.runtime.capability_registry
                
                # Get all providers for this capability
                all_providers = cap_reg.get_all_providers_for_capability(operation_type)
                
                # Find remote provider (prefer first remote if multiple exist)
                for provider_info in all_providers:
                    if provider_info.get("type") == "remote":
                        return provider_info
        except Exception:
            pass
        
        return None

    async def _execute_remote_operation(
        self,
        operation: Operation,
        provider_info: Dict[str, Any],
        retry_count: int = 0
    ) -> Operation:
        """
        Execute operation on remote provider via HTTP.
        
        Поддерживает Capability Protocol v1:
        - Protocol version negotiation
        - Health monitoring and recording
        - Retryable error handling
        - Per-capability timeouts from manifest
        - Auto-retry on transient failures
        
        Args:
            operation: Operation to execute
            provider_info: Remote provider metadata with protocol info
            retry_count: Current retry attempt (for diagnostics)
            
        Returns:
            Operation with updated status and result/error
        """
        from core.remote_executor import RemoteOperationExecutor
        
        provider_name = provider_info.get("plugin")
        
        # Mark as running
        operation.status = OperationStatus.RUNNING
        operation.started_at = time.time()
        await self._persist(operation)
        
        try:
            # Get remote config and timeout
            remote_config = provider_info.get("remote_config", {})
            base_url = remote_config.get("base_url")
            
            # Use per-capability timeout from manifest if available, else default
            timeouts = provider_info.get("timeouts", {})
            timeout = timeouts.get(operation.type, capability_protocol.DEFAULT_CAPABILITY_TIMEOUT)
            
            if not base_url:
                raise ValueError(f"Remote provider missing base_url in config")
            
            # Prepare execution context
            context = {
                "operation_id": operation.operation_id,
                "initiator": operation.initiator.to_dict() if operation.initiator else None,
            }
            
            # Execute with Protocol v1
            response = await RemoteOperationExecutor.execute_remote(
                base_url=base_url,
                capability=operation.type,
                operation_id=operation.operation_id,
                params=operation.params,
                context=context,
                timeout=timeout
            )
            
            # Record success in health monitor
            self._health_monitor.record_success(provider_name)
            provider_info["healthy"] = True
            
            # Handle response
            if response.get("status") == "success":
                # Success
                operation.status = OperationStatus.SUCCESS
                operation.result = response.get("result", {})
            else:
                # Remote provider returned error
                error_info = response.get("error", {})
                operation.status = OperationStatus.FAILED
                is_retryable = RemoteOperationExecutor.is_error_retryable(response)
                
                operation.error = OperationError(
                    code=error_info.get("code", "remote_error"),
                    message=error_info.get("message", "Remote provider error"),
                )
                
                # Record failure for health tracking
                self._health_monitor.record_failure(
                    provider_name,
                    f"{error_info.get('code')}: {error_info.get('message')}"
                )
                
                # If retryable and we haven't exceeded retry limit → try alternative provider
                if is_retryable and retry_count < capability_protocol.MAX_RETRIES_PER_OPERATION:
                    # Try next provider from registry
                    if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                        cap_reg = self.runtime.capability_registry
                        all_providers = cap_reg.get_all_providers_for_capability(operation.type)
                        
                        # Skip current provider and try next healthy one
                        for alt_provider in all_providers:
                            if alt_provider["plugin"] != provider_name and alt_provider.get("type") == "remote":
                                if not self._health_monitor.should_skip_provider(alt_provider["plugin"]):
                                    # Reset operation status and retry with alternative
                                    operation.status = OperationStatus.PENDING
                                    operation.error = None
                                    return await self._execute_remote_operation(
                                        operation,
                                        alt_provider,
                                        retry_count + 1
                                    )
            
            operation.finished_at = time.time()
        
        except capability_protocol.ProtocolCompatibilityError as e:
            # Protocol mismatch - this is a permanent failure
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="protocol_incompatible",
                message=f"Protocol mismatch with remote provider: {str(e)}"
            )
            operation.finished_at = time.time()
            self._health_monitor.mark_unhealthy(provider_name, "protocol_incompatible")
            provider_info["healthy"] = False
        
        except Exception as e:
            # Network or execution error
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="remote_execution_failed",
                message=f"Remote operation failed: {str(e)}"
            )
            operation.finished_at = time.time()
            
            # Record failure for health monitoring
            self._health_monitor.record_failure(provider_name, str(e))
            provider_info["healthy"] = not self._health_monitor.should_skip_provider(provider_name)
        
        await self._persist(operation)
        return operation

    async def create(
        self,
        op_type: str,
        params: Dict[str, Any],
        initiator: OperationInitiator,
        parent_operation_id: Optional[str] = None,
    ) -> Operation:
        """Create and persist new operation."""
        operation_id = f"op-{uuid.uuid4().hex[:12]}"
        
        operation = Operation(
            operation_id=operation_id,
            op_type=op_type,
            params=params,
            initiator=initiator,
            parent_operation_id=parent_operation_id,
        )
        
        # Persist to storage
        await self.runtime.storage.set(
            "operations",
            operation_id,
            operation.to_dict()
        )
        
        return operation
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """Retrieve operation from storage."""
        data = await self.runtime.storage.get("operations", operation_id)
        if data is None:
            return None
        return Operation.from_dict(data)
    
    async def list(self, limit: int = 100, offset: int = 0) -> List[Operation]:
        """List operations (newest first)."""
        try:
            keys = await self.runtime.storage.list_keys("operations")
        except Exception:
            return []
        
        # Fetch all and sort by created_at descending
        operations = []
        for key in keys:
            try:
                data = await self.runtime.storage.get("operations", key)
                if data:
                    operations.append(Operation.from_dict(data))
            except Exception:
                pass
        
        # Sort by created_at descending
        operations.sort(key=lambda op: op.created_at, reverse=True)
        
        # Apply pagination
        return operations[offset:offset + limit]
    
    async def execute(self, operation: Operation) -> Operation:
        """
        Execute operation following pipeline:
        validate → authorize → run → persist.
        
        Operation status is updated in-place, result persisted.
        
        Supports execution modes:
        1. in_process: direct handler call
        2. process: subprocess execution
        3. container: docker/podman execution
        4. remote: HTTP execution
        """
        try:
            # 1. Validate - try to find handler (direct or capability-based)
            handler = self._find_handler(operation.type)
            provider_metadata = None  # Get metadata for execution mode decision
            
            # P0: ATOMIC PROVIDER SELECTION with lock
            # Lock held only for selection, not during execution
            provider_dict = None
            try:
                if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                    cap_reg = self.runtime.capability_registry
                    # Atomic: hold lock only during selection
                    with cap_reg._lock:
                        all_providers = cap_reg.get_all_providers_for_capability(operation.type)
                        if all_providers and len(all_providers) > 0:
                            # Take snapshot of first provider
                            provider_dict = dict(all_providers[0])
                            # Convert dict to ProviderMetadata using registry method
                            provider_metadata = cap_reg.provider_info_to_metadata(provider_dict)
            except Exception:
                pass  # Failed to get metadata, continue with defaults
            
            # 2. Verify provider still exists (after releasing lock)
            execution_mode = "in_process"  # default
            provider_type = "local"  # default
            if provider_metadata:
                execution_mode = provider_metadata.execution_mode
                provider_type = provider_metadata.provider_type
                
                # Check provider still valid
                if provider_dict and hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                    cap_reg = self.runtime.capability_registry
                    # Try to verify provider with provider_exists check (if available)
                    try:
                        if hasattr(cap_reg, 'provider_exists'):
                            provider_still_exists = cap_reg.provider_exists(
                                provider_dict[\"plugin\"], 
                                operation.type
                            )
                            if not provider_still_exists:
                                raise Exception(f\"Provider {provider_dict['plugin']} disappeared during execution setup\")
                    except (AttributeError, Exception):
                        # provider_exists might not exist yet, skip this check
                        pass
            
            # If no local handler, try remote provider (backward compatible)
            if handler is None:
                # Check for remote provider (either type=\"remote\" or execution_mode=\"remote\")
                if provider_type == \"remote\" or execution_mode == \"remote\":
                    remote_provider_info = self._find_remote_provider(operation.type)
                    if remote_provider_info:
                        return await self._execute_remote_operation(operation, remote_provider_info)
                
                # Neither local nor remote found
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(
                    code=\"unknown_operation_type\",
                    message=f\"No handler or remote provider for operation type: {operation.type}\"
                )
                await self._persist(operation)
                return operation
            
            # Mark as running
            operation.status = OperationStatus.RUNNING
            operation.started_at = time.time()
            await self._persist(operation)
            
            # Execute via ExecutionRouter (handles execution_mode routing)
            result = await self._execution_router.execute(operation, provider_metadata)
            
            # Mark success
            operation.status = OperationStatus.SUCCESS
            operation.result = result
            operation.finished_at = time.time()
            
        except Exception as e:
            # Any exception → failed operation
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="execution_error",
                message=str(e)
            )
            operation.finished_at = time.time()
        
        # Persist final state
        await self._persist(operation)
        return operation
    
    async def cancel(self, operation_id: str) -> Optional[Operation]:
        """Cancel operation if possible (only PENDING or RUNNING)."""
        operation = await self.get(operation_id)
        if not operation:
            return None
        
        if operation.status not in (OperationStatus.PENDING, OperationStatus.RUNNING):
            return operation  # Already terminal
        
        operation.status = OperationStatus.CANCELLED
        operation.finished_at = time.time()
        await self._persist(operation)
        
        return operation
    
    async def retry(self, operation_id: str) -> Optional[Operation]:
        """
        Create new operation as retry of failed operation.
        
        Original operation's error must be retryable.
        """
        original = await self.get(operation_id)
        if not original:
            return None
        
        # Only allow retry for failed operations
        if original.status != OperationStatus.FAILED:
            return None
        
        # Only if error code is retryable
        if original.error and original.error.code not in self._retryable_errors:
            return None
        
        # Create new operation as retry
        new_op = await self.create(
            op_type=original.type,
            params=original.params,
            initiator=original.initiator,
            parent_operation_id=operation_id,
        )
        
        return new_op
    
    async def _persist(self, operation: Operation) -> None:
        """Persist operation state to storage."""
        await self.runtime.storage.set(
            "operations",
            operation.operation_id,
            operation.to_dict()
        )


# Marker for retryable error codes
RETRYABLE_ERRORS = {
    "timeout", "transient", "network", "device_offline", 
    "integration_unavailable", "rate_limited"
}

# Marker for terminal status
TERMINAL_STATUSES = {OperationStatus.SUCCESS, OperationStatus.FAILED, OperationStatus.CANCELLED}
