"""
Admin operations services.

Moved from AdminModule for architectural clarity.
Behavior is unchanged.
"""
from typing import Any, Dict, Optional


async def admin_operations_create(runtime: Any, body: Any = None, **kwargs) -> Dict[str, Any]:
    """Create and execute an operation."""
    try:
        if not isinstance(body, dict):
            raise ValueError("Request body must be JSON object")

        op_type = body.get("type")
        params = body.get("params", {})

        if not op_type:
            raise ValueError("Missing 'type' in request body")

        ops_mgr = runtime.operations
        if not ops_mgr:
            raise RuntimeError("Operations manager not available")

        from core.operations import OperationInitiator, OperationInitiatorKind

        initiator = OperationInitiator(
            kind=OperationInitiatorKind.ADMIN,
            user_id=None,
        )

        operation = await ops_mgr.create(
            op_type=op_type,
            params=params,
            initiator=initiator,
        )

        result = await ops_mgr.execute(operation)

        return result.to_dict()

    except ValueError as e:
        raise ValueError(str(e))
    except Exception as e:
        raise RuntimeError(f"Operation creation failed: {str(e)}")


async def admin_operations_list(runtime: Any, limit: int = 100, offset: int = 0, status: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """List operations with pagination and filtering."""
    try:
        # Query params from HTTP are often strings; ensure int for slice
        limit = int(limit) if limit is not None else 100
        offset = int(offset) if offset is not None else 0
        limit = max(1, min(1000, limit))
        offset = max(0, offset)

        ops_mgr = runtime.operations
        if not ops_mgr:
            raise RuntimeError("Operations manager not available")

        ops = await ops_mgr.list(limit=limit, offset=offset)

        if status:
            normalized_status = {
                "pending": "created",
                "success": "completed",
            }.get(str(status), str(status))
            ops = [op for op in ops if op.status.value == normalized_status]

        return {
            "ok": True,
            "operations": [op.to_dict() for op in ops],
            "total": len(ops),
        }
    except Exception as e:
        raise RuntimeError(f"Failed to list operations: {str(e)}")


async def admin_operations_get(runtime: Any, operation_id: str, **kwargs) -> Dict[str, Any]:
    """Get operation details by ID."""
    try:
        ops_mgr = runtime.operations
        if not ops_mgr:
            raise RuntimeError("Operations manager not available")

        op = await ops_mgr.get(operation_id)
        if not op:
            raise ValueError(f"Operation {operation_id} not found")

        return op.to_dict()
    except ValueError as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Failed to get operation: {str(e)}")


async def admin_operations_cancel(runtime: Any, operation_id: str, **kwargs) -> Dict[str, Any]:
    """Cancel a pending or running operation."""
    try:
        ops_mgr = runtime.operations
        if not ops_mgr:
            raise RuntimeError("Operations manager not available")

        op = await ops_mgr.cancel(operation_id)
        if not op:
            raise ValueError(f"Cannot cancel operation {operation_id}")

        return {
            "ok": True,
            "operation": op.to_dict(),
        }
    except ValueError as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Failed to cancel operation: {str(e)}")


async def admin_operations_retry(runtime: Any, operation_id: str, **kwargs) -> Dict[str, Any]:
    """Retry a failed operation."""
    try:
        ops_mgr = runtime.operations
        if not ops_mgr:
            raise RuntimeError("Operations manager not available")

        original_op = await ops_mgr.get(operation_id)
        if not original_op:
            raise ValueError(f"Operation {operation_id} not found")

        new_op = await ops_mgr.retry(operation_id)
        if not new_op:
            raise ValueError(
                f"Cannot retry operation {operation_id} "
                "(not failed or error not retryable)"
            )

        result = await ops_mgr.execute(new_op)

        return {
            "ok": True,
            "new_operation_id": result.operation_id,
            "status": result.status.value,
            "result": result.result,
            "error": result.error.to_dict() if result.error else None,
        }
    except ValueError as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Failed to retry operation: {str(e)}")
