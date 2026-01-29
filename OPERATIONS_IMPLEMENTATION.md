"""
Operations Subsystem Implementation Guide

COMPLETED IMPLEMENTATION:
========================

1. Core Model (core/operations.py)
   ✅ Operation class: immutable entity with lifecycle
   ✅ OperationManager: create, execute, get, list, cancel, retry
   ✅ Status enum: PENDING → RUNNING → SUCCESS/FAILED/CANCELLED
   ✅ Initiator tracking: admin vs system with user_id
   ✅ Error handling: code + message + details + retryable flag
   ✅ Persistence: all operations stored in "operations" namespace

2. Module Integration (modules/operations/module.py)
   ✅ OperationsModule: RuntimeModule subclass
   ✅ Handler registration: 7 operation types registered
   ✅ Service registration: operations.* services (create, list, get, cancel, retry)
   ✅ Integration point: self.runtime.operations = manager

3. Handlers (modules/operations/handlers.py)
   ✅ device.set_state: Set device state with delta support
   ✅ yandex.sync: Trigger full sync with Yandex Smart Home
   ✅ yandex.check_devices_online: Check all devices online status
   ✅ oauth.refresh_token: Refresh OAuth tokens
   ✅ mappings.create: Create new device mapping
   ✅ mappings.delete: Delete device mapping
   ✅ mappings.auto: Auto-discover and create mappings

4. API Endpoints (modules/operations/router.py)
   ✅ POST /admin/v1/operations - Create and execute operation (202 Accepted)
   ✅ GET /admin/v1/operations - List operations with filtering
   ✅ GET /admin/v1/operations/{id} - Get operation details
   ✅ POST /admin/v1/operations/{id}/cancel - Cancel pending/running
   ✅ POST /admin/v1/operations/{id}/retry - Retry failed operation (if retryable)

5. Endpoint Redirects (modules/admin/module.py)
   ✅ admin_devices_set_state: Redirects to device.set_state operation
   ✅ admin_v1_yandex_sync: Redirects to yandex.sync operation
   ✅ Fallback: Direct call if operations not available

NEXT STEPS FOR FULL INTEGRATION:
=================================

1. Mount Operations Router in ApiModule
   ---
   In modules/api/module.py, after line 130 (monitoring router):
   
   ```python
   # Mount operations router
   try:
       from modules.operations import create_operations_router
       operations_router = create_operations_router(self.runtime)
       self.app.include_router(operations_router)
   except ImportError:
       import logging
       logging.warning("Operations module not available")
   ```

2. Register OperationsModule in Runtime
   ---
   In core/runtime.py, module registration loop (typically __init__ or start()):
   
   ```python
   from modules.operations import OperationsModule
   
   # In module registration:
   operations_module = OperationsModule(self)
   await operations_module.register()
   ```

3. Update Remaining Endpoints
   ---
   Other endpoints that should route through operations:
   
   a) Mapping operations in admin module:
      - admin_v1_mappings_create → operation type "mappings.create"
      - admin_v1_mappings_delete → operation type "mappings.delete"
      - admin_v1_mappings_auto → operation type "mappings.auto"
   
   b) OAuth operations (if any):
      - oauth refresh endpoint → operation type "oauth.refresh_token"

4. Add Context Propagation
   ---
   Ensure operation_id flows through logging and HTTP calls:
   
   In request context middleware:
   ```python
   context.operation_id = getattr(request.state, "operation_id", None)
   ```
   
   In logging middleware:
   ```python
   extra = {"operation_id": getattr(request.state, "operation_id", None)}
   logger.info(message, extra=extra)
   ```

5. Testing Strategy
   ---
   Test scenarios:
   
   ✅ Basic operation creation and execution:
      POST /admin/v1/operations with type="device.set_state"
      → Returns operation_id, status="success", result contains output
   
   ✅ Operation listing and filtering:
      GET /admin/v1/operations?status=success
      → Returns list of terminal operations
   
   ✅ Operation details:
      GET /admin/v1/operations/{id}
      → Returns full operation including error if failed
   
   ✅ Operation cancellation:
      POST /admin/v1/operations/{id}/cancel
      → Returns cancelled operation (only works for PENDING/RUNNING)
   
   ✅ Operation retry:
      POST /admin/v1/operations/{id}/retry
      → Creates new operation with parent_operation_id set
      → Only works if error.code is retryable
   
   ✅ Fallback behavior:
      If operations manager not available, existing endpoints still work

API USAGE EXAMPLES:
===================

1. Set Device State (via Operations)
   POST /admin/v1/operations
   Content-Type: application/json
   X-CSRF-Token: [token]
   
   {
     "type": "device.set_state",
     "params": {
       "device_id": "lights_living_room",
       "state": {"on": true},
       "delta": true
     }
   }
   
   Response (202 Accepted):
   {
     "operation_id": "op-abc123def456",
     "type": "device.set_state",
     "status": "success",
     "result": {
       "device_id": "lights_living_room",
       "success": true,
       "old_state": {"on": false},
       "new_state": {"on": true}
     },
     "error": null,
     "created_at": 1234567890.123,
     "started_at": 1234567891.456,
     "finished_at": 1234567892.789
   }

2. Sync Yandex (via Operations)
   POST /admin/v1/operations
   {
     "type": "yandex.sync",
     "params": {}
   }
   
   Response:
   {
     "operation_id": "op-xyz789uvw012",
     "status": "success",
     "result": {
       "success": true,
       "devices_synced": 15,
       "timestamp": 1234567893.123
     }
   }

3. List Operations
   GET /admin/v1/operations?limit=50&status=failed
   
   Response:
   {
     "ok": true,
     "operations": [
       {
         "operation_id": "op-...",
         "type": "device.set_state",
         "status": "failed",
         "error": {
           "code": "device_offline",
           "message": "Device is offline"
         }
       }
     ],
     "total": 3
   }

4. Retry Failed Operation
   POST /admin/v1/operations/op-abc123def456/retry
   
   Response (202 Accepted):
   {
     "ok": true,
     "new_operation_id": "op-def456ghi789",
     "status": "success",
     "result": {...}
   }

CONFIGURATION NOTES:
====================

1. Timeout Behavior
   - Operations persist until explicitly deleted
   - No automatic cleanup (manual archive/delete if needed)
   - Query using GET /admin/v1/operations for audit trail

2. Handler Execution
   - All handlers run synchronously within operation.execute()
   - Exception handling: any exception → operation.error with code="execution_error"
   - Timeout errors: retry-friendly (error.code="timeout")
   - Device offline: retry-friendly (error.code="device_offline")

3. Initiator Tracking
   - All operations must have initiator (admin vs system)
   - user_id optional (populated from auth context)
   - Audit trail shows who/what triggered operation

4. Storage
   - Operations namespace: "operations"
   - Key: operation_id (op-{uuid})
   - Value: Operation.to_dict() (JSON-serializable)
   - Persisted after each status transition

SECURITY IMPLICATIONS:
=======================

✅ Audit Trail
   - Every operation tracked with operation_id
   - Timestamps: created_at, started_at, finished_at
   - Initiator: admin user_id or system process
   - Result: full execution details

✅ ACL Enforcement
   - All endpoints require admin access (401/403)
   - Context propagation via request.state.auth_context
   - Fallback: direct endpoint calls if no operations available

✅ Error Handling
   - No exceptions leak to HTTP layer
   - All errors captured in operation.error
   - Client must check status and error codes

⚠️ TODO Items
   - Rate limiting per admin user (prevent DOS)
   - Large batch operations (paginate results)
   - Cleanup/archival of old operations
"""
