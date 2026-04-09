"""
Test for IOperationExecutor interface contract.

Ensures OperationExecutor implements IOperationExecutor interface correctly.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from core.operations.executor import OperationExecutor
from core.operations.interface import IOperationExecutor
from core.operations.models import Operation, OperationStatus


def test_operation_executor_implements_interface():
    """
    Verify OperationExecutor implements IOperationExecutor interface.
    
    This test ensures the contract is satisfied, allowing OperationExecutor
    to be used anywhere IOperationExecutor is expected.
    """
    # Create mock dependencies
    registry = Mock()
    runtime = Mock()
    storage = AsyncMock()
    
    # Create executor
    executor = OperationExecutor(registry, runtime, storage)
    
    # Verify it's recognized as implementing IOperationExecutor
    assert isinstance(executor, IOperationExecutor), (
        "OperationExecutor must implement IOperationExecutor interface"
    )


def test_operation_executor_has_execute_method():
    """
    Verify OperationExecutor has execute method with correct signature.
    """
    registry = Mock()
    runtime = Mock()
    storage = AsyncMock()
    
    executor = OperationExecutor(registry, runtime, storage)
    
    # Check method exists
    assert hasattr(executor, 'execute'), "OperationExecutor must have execute method"
    
    # Check it's async
    import inspect
    assert inspect.iscoroutinefunction(executor.execute), (
        "OperationExecutor.execute must be async"
    )


@pytest.mark.asyncio
async def test_execute_returns_operation():
    """
    Verify execute method returns an Operation with status set.
    """
    from core.operations.models import OperationInitiator, OperationInitiatorKind
    
    # Setup
    registry = Mock()
    registry.find_handler.return_value = None  # No handler, will fail gracefully
    
    runtime = Mock()
    runtime.capability_registry = None
    runtime.execution_controller = None
    
    storage = AsyncMock()
    storage.persist = AsyncMock()
    
    executor = OperationExecutor(registry, runtime, storage)
    
    # Create test operation
    op = Operation(
        operation_id="test-op-1",
        op_type="test.operation",
        params={"key": "value"},
        initiator=OperationInitiator(kind=OperationInitiatorKind.SYSTEM)
    )
    
    # Execute
    result = await executor.execute(op)
    
    # Verify result
    assert isinstance(result, Operation), "execute must return Operation"
    assert result.status in (
        OperationStatus.SUCCESS,
        OperationStatus.FAILED,
        OperationStatus.RUNNING,
        OperationStatus.PENDING
    ), f"Operation status must be valid, got {result.status}"
    
    # Verify storage was called
    assert storage.persist.called, "Operation must be persisted"


def test_executor_is_depended_on_by_interface():
    """
    Verify that code using IOperationExecutor can accept OperationExecutor.
    
    This test demonstrates the interface inversion benefit.
    """
    def use_executor(executor: IOperationExecutor) -> bool:
        """Function that depends on interface."""
        return isinstance(executor, IOperationExecutor)
    
    # Create executor
    registry = Mock()
    runtime = Mock()
    storage = AsyncMock()
    executor = OperationExecutor(registry, runtime, storage)
    
    # This should work without type errors or assertion failures
    assert use_executor(executor), (
        "Executor must satisfy interface contract to be used in interface-dependent code"
    )
