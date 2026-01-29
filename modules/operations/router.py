"""
Operations API endpoints.

HTTP routes for operation management:
- POST /admin/v1/operations — create and execute operation
- GET /admin/v1/operations — list operations
- GET /admin/v1/operations/{id} — get operation details
- POST /admin/v1/operations/{id}/cancel — cancel operation
- POST /admin/v1/operations/{id}/retry — retry failed operation
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Any, Dict, Optional
from starlette.requests import Request


def create_operations_router(runtime: Any) -> APIRouter:
    """Create FastAPI router for operations API."""
    router = APIRouter(prefix="/admin/v1/operations", tags=["operations"])
    
    # =========================================================================
    # POST /admin/v1/operations — Create and execute operation
    # =========================================================================
    @router.post("/", status_code=202)
    async def create_and_execute_operation(
        body: Dict[str, Any],
        request: Request,
    ) -> Dict[str, Any]:
        """
        Create and execute an operation.
        
        Request body:
        {
            "type": "device.set_state",
            "params": {
                "device_id": "...",
                "state": {...}
            }
        }
        
        Response (202 Accepted):
        {
            "operation_id": "op_...",
            "type": "device.set_state",
            "status": "success|pending|running|failed|cancelled",
            "result": {...} or null,
            "error": {...} or null,
            "created_at": 1234567890.123,
            "finished_at": 1234567900.456,
        }
        """
        try:
            # Validate request
            op_type = body.get("type")
            params = body.get("params", {})
            
            if not op_type:
                raise HTTPException(
                    status_code=400,
                    detail="Missing 'type' in request body"
                )
            
            # Get auth context from middleware
            auth_context = getattr(request.state, "auth_context", None)
            if not auth_context:
                raise HTTPException(status_code=401, detail="Unauthorized")
            
            # Check ACL
            if not auth_context.get("admin"):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Get operations manager
            operations_mgr = getattr(runtime, "operations", None)
            if not operations_mgr:
                raise HTTPException(
                    status_code=500,
                    detail="Operations manager not available"
                )
            
            # Create operation with context
            from core.operations import OperationInitiator, OperationInitiatorKind
            
            initiator = OperationInitiator(
                kind=OperationInitiatorKind.ADMIN,
                user_id=auth_context.get("user_id"),
            )
            
            operation = await operations_mgr.create(
                op_type=op_type,
                params=params,
                initiator=initiator,
            )
            
            # Attach operation_id to request context for logging
            request.state.operation_id = operation.operation_id
            
            # Execute operation
            result = await operations_mgr.execute(operation)
            
            # Return result
            return result.to_dict()
        
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Operation failed: {str(e)}")
    
    # =========================================================================
    # GET /admin/v1/operations — List operations
    # =========================================================================
    @router.get("/")
    async def list_operations(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status: Optional[str] = Query(None),
        request: Request = None,
    ) -> Dict[str, Any]:
        """
        List operations with optional filtering.
        
        Query params:
        - limit: Max results (default 100)
        - offset: Pagination offset (default 0)
        - status: Filter by status (pending|running|success|failed|cancelled)
        
        Response:
        {
            "ok": true,
            "operations": [
                {...operation...},
            ],
            "total": 42,
        }
        """
        try:
            # Check auth
            auth_context = getattr(request.state, "auth_context", None)
            if not auth_context or not auth_context.get("admin"):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Get operations manager
            operations_mgr = getattr(runtime, "operations", None)
            if not operations_mgr:
                raise HTTPException(
                    status_code=500,
                    detail="Operations manager not available"
                )
            
            # List operations
            ops = await operations_mgr.list(limit=limit, offset=offset)
            
            # Filter by status if provided
            if status:
                ops = [op for op in ops if op.status.value == status]
            
            return {
                "ok": True,
                "operations": [op.to_dict() for op in ops],
                "total": len(ops),
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list operations: {str(e)}")
    
    # =========================================================================
    # GET /admin/v1/operations/{id} — Get operation details
    # =========================================================================
    @router.get("/{operation_id}")
    async def get_operation(
        operation_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """
        Get operation details by ID.
        
        Response:
        {
            "operation_id": "op_...",
            "type": "device.set_state",
            "status": "success",
            "result": {...},
            "error": null,
            ...
        }
        """
        try:
            # Check auth
            auth_context = getattr(request.state, "auth_context", None)
            if not auth_context or not auth_context.get("admin"):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Get operations manager
            operations_mgr = getattr(runtime, "operations", None)
            if not operations_mgr:
                raise HTTPException(
                    status_code=500,
                    detail="Operations manager not available"
                )
            
            # Get operation
            operation = await operations_mgr.get(operation_id)
            if not operation:
                raise HTTPException(
                    status_code=404,
                    detail=f"Operation {operation_id} not found"
                )
            
            return operation.to_dict()
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get operation: {str(e)}")
    
    # =========================================================================
    # POST /admin/v1/operations/{id}/cancel — Cancel operation
    # =========================================================================
    @router.post("/{operation_id}/cancel", status_code=200)
    async def cancel_operation(
        operation_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """
        Cancel a pending or running operation.
        
        Response:
        {
            "ok": true,
            "operation": {...operation with status=cancelled...},
        }
        """
        try:
            # Check auth
            auth_context = getattr(request.state, "auth_context", None)
            if not auth_context or not auth_context.get("admin"):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Get operations manager
            operations_mgr = getattr(runtime, "operations", None)
            if not operations_mgr:
                raise HTTPException(
                    status_code=500,
                    detail="Operations manager not available"
                )
            
            # Cancel operation
            operation = await operations_mgr.cancel(operation_id)
            if not operation:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot cancel operation {operation_id} (not pending or running)"
                )
            
            return {
                "ok": True,
                "operation": operation.to_dict(),
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to cancel operation: {str(e)}")
    
    # =========================================================================
    # POST /admin/v1/operations/{id}/retry — Retry failed operation
    # =========================================================================
    @router.post("/{operation_id}/retry", status_code=202)
    async def retry_operation(
        operation_id: str,
        request: Request,
    ) -> Dict[str, Any]:
        """
        Retry a failed operation (if error is retryable).
        
        Response (202 Accepted):
        {
            "ok": true,
            "new_operation_id": "op_...",
            "status": "success|running|failed",
            "result": {...} or null,
            "error": {...} or null,
        }
        """
        try:
            # Check auth
            auth_context = getattr(request.state, "auth_context", None)
            if not auth_context or not auth_context.get("admin"):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Get operations manager
            operations_mgr = getattr(runtime, "operations", None)
            if not operations_mgr:
                raise HTTPException(
                    status_code=500,
                    detail="Operations manager not available"
                )
            
            # Get original operation
            original_op = await operations_mgr.get(operation_id)
            if not original_op:
                raise HTTPException(
                    status_code=404,
                    detail=f"Operation {operation_id} not found"
                )
            
            # Try to create retry operation
            new_op = await operations_mgr.retry(operation_id)
            if not new_op:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot retry operation {operation_id} "
                           "(not failed or error not retryable)"
                )
            
            # Execute new operation
            result = await operations_mgr.execute(new_op)
            
            return {
                "ok": True,
                "new_operation_id": result.operation_id,
                "status": result.status.value,
                "result": result.result,
                "error": result.error.to_dict() if result.error else None,
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to retry operation: {str(e)}")
    
    return router
