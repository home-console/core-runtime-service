# Remote Plugin Contract
## Formal Specification for Core Runtime ↔ Remote Plugin Interaction

**Status:** Formalized  
**Based on:** `remote_logger`, `remote_metrics` implementations  
**Version:** 1.0  

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Plugin Lifecycle Contract](#plugin-lifecycle-contract)
4. [Service Registration & Invocation](#service-registration--invocation)
5. [Responsibility Matrix](#responsibility-matrix)
6. [Constraints & Prohibitions](#constraints--prohibitions)
7. [Error Handling & Resilience](#error-handling--resilience)
8. [Pre-SDK Verification Checklist](#pre-sdk-verification-checklist)

---

## Executive Summary

This document formalizes the HTTP-based contract between Core Runtime and remote plugins.

**Key Invariants:**
- Core Runtime **does not change** when integrating remote plugins
- Remote plugins are managed via HTTP lifecycle endpoints
- Services are declared in metadata and auto-registered by proxy
- Remote plugin failure **must not** cascade to Core Runtime failure

**Scope:** System plugins only (remote_logger, remote_metrics, etc.). Domain plugins remain in-process.

---

## Architecture Overview

### Component Interaction

```
┌─────────────────────────┐
│   Core Runtime          │
│  - PluginManager        │
│  - ServiceRegistry      │
│  - EventBus, etc.       │
└───────────┬─────────────┘
            │ (lifecycle methods)
            │ (service calls)
            ▼
┌─────────────────────────┐
│  RemotePluginProxy      │
│  (local plugin in Core) │
│  - HTTP forwarder       │
│  - service registration │
└───────────┬─────────────┘
            │ (HTTP POST/GET)
            │
    ┌───────┴──────────┐
    │   Network        │
    └───────┬──────────┘
            │
            ▼
┌─────────────────────────┐
│  Remote Plugin (Process)│
│  - HTTP endpoints       │
│  - business logic       │
│  - state management     │
└─────────────────────────┘
```

### Data Flow

```
1. Plugin Loading:
   Core → PluginManager.load_plugin(RemotePluginProxy)
   RemotePluginProxy.on_load():
     → GET  /plugin/metadata
     → POST /plugin/load
     → register services from metadata.services

2. Service Invocation:
   Core → ServiceRegistry.call("metrics.report", args)
   ServiceRegistry → registered forwarder
   forwarder → RemotePluginProxy → POST /metrics/report (payload)
   Remote plugin processes, returns response

3. Plugin Stopping:
   Core → PluginManager.stop_plugin(name)
   RemotePluginProxy.on_stop():
     → POST /plugin/stop

4. Plugin Unloading:
   Core → PluginManager.unload_plugin(name)
   RemotePluginProxy.on_unload():
     → POST /plugin/unload
     → unregister all services from metadata.services
```

---

## Plugin Lifecycle Contract

### Lifecycle Endpoints (Required)

Every remote plugin **must** implement these HTTP endpoints:

#### `GET /plugin/metadata`

**Purpose:** Declare plugin capabilities, name, version, and available services.

**Response (JSON):**
```json
{
  "name": "string",              // Required: plugin identifier (e.g., "remote_logger")
  "type": "string",              // Required: "system" or "domain"
  "mode": "string",              // Required: "remote"
  "version": "string",           // Required: semantic version (e.g., "0.1.0")
  "description": "string",       // Optional: human-readable description
  "author": "string",            // Optional: plugin author/maintainer
  "services": [                  // Required (may be empty array)
    {
      "name": "string",          // Required: service identifier (e.g., "metrics.report")
      "endpoint": "string",      // Required: HTTP endpoint (e.g., "/metrics/report")
      "method": "string"         // Required: "GET" or "POST"
    }
  ]
}
```

**Status Codes:**
- `200`: Metadata provided (even during error state)
- `500`: Fatal error (e.g., plugin crashed)

**Idempotency:** Yes. Must return same data on repeated calls.

**Notes:**
- Response is read once during `on_load()` by proxy
- Proxy uses `metadata.services` to auto-register local forwarders
- Name in metadata **should** match PluginManager expectations

---

#### `GET /plugin/health`

**Purpose:** Check remote plugin liveness (optional but recommended).

**Response (JSON):**
```json
{
  "status": "ok" | "error",
  "loaded": boolean,
  "started": boolean,
  "timestamp": "ISO8601"
}
```

**Status Codes:**
- `200`: Health data provided
- `503`: Service unavailable (temporary)

**Idempotency:** Yes.

**Notes:**
- Used for diagnostics, not required for lifecycle
- Proxy may log this during lifecycle transitions (future enhancement)

---

#### `POST /plugin/load`

**Purpose:** Initialize plugin state, prepare resources, declare services (no activation).

**Request:** No body required.

**Response (JSON):**
```json
{
  "status": "ok" | "already loaded" | "error",
  "message": "string"  // Optional
}
```

**Status Codes:**
- `200`: Successfully loaded (or was already loaded)
- `500`: Fatal error

**Idempotency:** Yes.  
- If already loaded, return `{"status": "already loaded"}` (HTTP 200)
- Do not error on repeated calls

**Ordering Guarantee:**
- Called **before** `/plugin/start`
- Called **once per plugin instance** (unless explicitly unloaded)

**Responsibilities of Remote Plugin:**
- Allocate resources (memory, file handles, connections)
- Validate configuration
- Do **not** start background tasks or listen on external events

**Proxy Behavior:**
- Calls immediately after `/plugin/metadata`
- On failure: raises exception, blocks Core loading

---

#### `POST /plugin/start`

**Purpose:** Activate plugin, start background tasks, enable service endpoints.

**Request:** No body required.

**Response (JSON):**
```json
{
  "status": "ok" | "already started" | "error",
  "message": "string"  // Optional
}
```

**Status Codes:**
- `200`: Started (or was already started)
- `500`: Fatal error

**Idempotency:** Yes.  
- If already started, return `{"status": "already started"}` (HTTP 200)

**Ordering Guarantee:**
- Called **after** `/plugin/load`
- Called **once per Core runtime cycle**

**Responsibilities of Remote Plugin:**
- Start event listeners
- Begin serving service endpoints
- Service endpoints may now receive requests

**Proxy Behavior:**
- Called by `PluginManager.start_plugin(name)`
- If this fails, plugin state = ERROR

---

#### `POST /plugin/stop`

**Purpose:** Gracefully deactivate plugin, pause background tasks, stop accepting new service calls.

**Request:** No body required.

**Response (JSON):**
```json
{
  "status": "ok" | "already stopped" | "error",
  "message": "string"  // Optional
}
```

**Status Codes:**
- `200`: Stopped (or was already stopped)
- `500`: Fatal error

**Idempotency:** Yes.  
- If already stopped, return `{"status": "already stopped"}` (HTTP 200)

**Ordering Guarantee:**
- Called **after** `/plugin/start`
- Called **once per shutdown cycle**

**Responsibilities of Remote Plugin:**
- Stop listening to events
- Allow in-flight requests to complete
- Do not accept new service calls
- Release temporary resources (buffers, caches)

**Proxy Behavior:**
- Called by `PluginManager.stop_plugin(name)`
- Errors logged but do not block unloading

---

#### `POST /plugin/unload`

**Purpose:** Final cleanup, release all resources, prepare for shutdown.

**Request:** No body required.

**Response (JSON):**
```json
{
  "status": "ok" | "error",
  "message": "string"  // Optional
}
```

**Status Codes:**
- `200`: Unloaded
- `500`: Fatal error

**Idempotency:** Yes.  
- Once unloaded, plugin no longer services requests
- Subsequent calls may return error (acceptable)

**Ordering Guarantee:**
- Called **after** `/plugin/stop` (enforced by proxy)
- Called **once per plugin lifetime**

**Responsibilities of Remote Plugin:**
- Close all database/file connections
- Release all memory
- Flush pending buffers
- Prepare for process termination

**Proxy Behavior:**
- Calls immediately before unloading from Core
- On success: unregisters all services from ServiceRegistry
- On failure: logs error, still unregisters services (to prevent registry corruption)

---

## Service Registration & Invocation

### Service Declaration (metadata.services)

Remote plugins declare available services in `/plugin/metadata` response.

**Schema:**
```json
{
  "name": "service.identifier",    // e.g., "metrics.report", "logger.log"
  "endpoint": "/relative/path",    // e.g., "/metrics/report"
  "method": "POST" | "GET"         // HTTP verb
}
```

**Requirements:**
- `name` must be **unique within Core ServiceRegistry**
- `name` must follow pattern: `namespace.action` (e.g., `metrics.report`)
- `endpoint` must be relative to remote plugin base URL
- `method` determines HTTP verb used by proxy

**Proxy Behavior:**
- On `on_load()`: reads `metadata.services`
- For each service: creates async forwarder function
- Registers forwarder with `runtime.service_registry.register(name, forwarder)`
- On `on_unload()`: unregisters all forwarders

### Service Invocation (Proxy ↔ Remote)

#### Request Format

**Proxy forwards local service call to remote endpoint:**

```
POST /endpoint
Content-Type: application/json

{
  "args": [],           // positional arguments (usually empty for kwargs-only calls)
  "kwargs": {           // keyword arguments from caller
    "key": "value",
    "param2": 123
  }
}
```

**Example (metrics.report call):**
```
Caller:
  await runtime.service_registry.call(
    "metrics.report",
    name="cpu_usage",
    value=0.42,
    tags={"host": "server1"}
  )

Proxy converts to HTTP request:
  POST http://remote:8002/metrics/report
  {
    "args": [],
    "kwargs": {
      "name": "cpu_usage",
      "value": 0.42,
      "tags": {"host": "server1"}
    }
  }
```

#### Response Format

**Remote plugin must return JSON:**

```json
{
  "status": "ok",            // Required: "ok" for success
  // Any additional fields are application-specific
}
```

**Status Codes:**
- `200`: Service executed successfully
- `400`: Invalid parameters (bad request)
- `500`: Service error (internal server error)
- `503`: Service unavailable (plugin not started)

**Proxy Behavior on Response:**
- Status 200 → return parsed JSON to caller
- Status 4xx/5xx → raise exception (propagate to caller)
- Timeout (no response) → raise exception

#### GET Service Endpoints (Optional)

If `method` = "GET", proxy ignores kwargs and calls:
```
GET /endpoint
```

Response same as POST (JSON with `{"status": "ok", ...}`).

**Use case:** query-only operations (e.g., health check, metrics dump).

---

## Responsibility Matrix

| Aspect | Remote Plugin | Proxy | Core Runtime |
|--------|---------------|-------|--------------|
| **HTTP Server** | ✅ Must implement | ❌ No | ❌ No |
| **Lifecycle Endpoints** | ✅ Must implement | ✅ Calls | ❌ Unaware |
| **Service Endpoints** | ✅ Must implement | ✅ Forwards | ❌ Unaware |
| **Metadata Declaration** | ✅ Must provide | ✅ Reads once | ❌ Unaware |
| **Service Registration** | ❌ No | ✅ Registers | ❌ Unaware |
| **Error Handling** | ✅ Returns HTTP error | ✅ Logs & propagates | ✅ Handles exceptions |
| **State Management** | ✅ Maintains (load/start/stop/unload) | ❌ No | ❌ Unaware |
| **Timeout Handling** | ✅ Returns within timeout | ✅ Implements timeout logic | ❌ Unaware |
| **Logging** | ✅ May log locally | ✅ Logs proxy errors | ✅ Logs handler errors |
| **Graceful Shutdown** | ✅ Flushes in-flight requests | ✅ Calls /plugin/stop first | ✅ Calls plugin manager methods |

---

## Constraints & Prohibitions

### Explicitly Prohibited

1. **Ad-hoc Parameter Encoding**  
   ❌ FORBIDDEN: Different proxy implementations inventing different `{args, kwargs}` formats  
   ✅ REQUIRED: All proxies use standardized `{"args": [], "kwargs": {...}}` format (as defined above)

2. **Core Runtime Modifications**  
   ❌ FORBIDDEN: Adding new Core methods to support remote plugins  
   ✅ REQUIRED: Remote plugins use existing Core APIs (ServiceRegistry, PluginManager, etc.)

3. **Direct Service Endpoint Registration**  
   ❌ FORBIDDEN: Remote plugin directly calling `runtime.service_registry.register()`  
   ✅ REQUIRED: Services declared in metadata; proxy auto-registers them

4. **Implicit Dependency Management**  
   ❌ FORBIDDEN: Remote plugin assuming other services exist without lifecycle check  
   ✅ REQUIRED: Remote plugin gracefully handles missing dependencies at runtime

5. **Versioning Negotiation**  
   ❌ FORBIDDEN: Proxy and remote negotiating API versions on the fly  
   ✅ REQUIRED: Version in metadata is informational only; proxy treats all remotes same way

6. **Authentication/Authorization**  
   ❌ FORBIDDEN: Adding auth to remote plugin HTTP endpoints  
   ✅ REQUIRED: Network isolation (local-only URLs) is sufficient for MVP

7. **Breaking Lifecycle Idempotency**  
   ❌ FORBIDDEN: Remote plugin failing when called twice (e.g., `POST /plugin/load` twice)  
   ✅ REQUIRED: Lifecycle endpoints must be idempotent (see [Lifecycle Contract](#plugin-lifecycle-contract))

---

## Error Handling & Resilience

### Failure Scenarios

#### Scenario 1: Remote Plugin Crashes During Load

```
Proxy.on_load() calls GET /plugin/metadata → timeout/connection refused
Proxy: logs error, re-raises exception
PluginManager: catches exception, sets plugin state = ERROR
Result: Plugin not loaded, Core continues
```

**Behavior:**
- Core does NOT crash
- Other plugins load normally
- Failed plugin remains in ERROR state

#### Scenario 2: Remote Plugin Never Calls `/plugin/start`

```
Proxy.on_start() calls POST /plugin/start → returns 500 error
Proxy: logs error, re-raises exception
PluginManager: catches exception, sets plugin state = ERROR
Result: Service is registered but endpoints return errors
```

**Behavior:**
- Core does NOT crash
- Services are available to call (backward compat)
- Service calls to remote endpoint will fail (network/remote error)

#### Scenario 3: Remote Plugin Crashes During Service Call

```
Caller: await runtime.service_registry.call("metrics.report", ...)
Proxy forwarder: sends POST /metrics/report → timeout
Proxy: raises exception (network error)
Caller: catches exception
Result: This service call fails, but Core/proxy remain alive
```

**Behavior:**
- Call raises exception to caller
- Caller must handle exception
- Proxy and Core are unaffected
- Other service calls continue normally

#### Scenario 4: Remote Plugin Crashes During Stop/Unload

```
Proxy.on_stop() calls POST /plugin/stop → timeout
Proxy: logs error, suppresses exception
PluginManager: plugin state = STOPPED (partial)
Result: Plugin marked stopped, but remote may still be running
```

**Behavior:**
- Stop errors are logged but do NOT block lifecycle
- Unload proceeds anyway
- Services are unregistered even if unload fails
- Core marks plugin as unloaded

### Timeout Behavior

**Current Implementation (urllib):**
- Blocking HTTP calls with no explicit timeout
- Long-running operations may hang

**Proxy Responsibility:**
- Implement timeout in HTTP layer (future: add `socket.settimeout()`)
- Timeout should be configured or default to 5 seconds

**Remote Plugin Responsibility:**
- All lifecycle endpoints should respond within 1 second
- Service endpoints may take longer (up to timeout)

---

## Pre-SDK Verification Checklist

Before releasing an SDK based on this contract, verify:

### ✅ Lifecycle Idempotency
- [ ] Test: Call `/plugin/load` twice → both return `{"status": "ok"}` (HTTP 200)
- [ ] Test: Call `/plugin/start` twice → both return `{"status": "ok"}` (HTTP 200)
- [ ] Test: Call `/plugin/stop` twice → both return `{"status": "ok"}` (HTTP 200)
- [ ] Test: Call `/plugin/unload` on non-loaded plugin → graceful error (HTTP 200 or 400, not 500)

### ✅ Service Registration & Invocation
- [ ] Test: Metadata declares 2+ services → all registered in ServiceRegistry
- [ ] Test: Service call with kwargs → proxy forwards as `{"kwargs": {...}}`
- [ ] Test: Service endpoint returns custom JSON → passed to caller
- [ ] Test: Service endpoint returns 500 → proxy raises exception to caller

### ✅ Error Isolation
- [ ] Test: Remote plugin crashes → Core runtime continues
- [ ] Test: Proxy network timeout → exception logged, caller informed (not Core crash)
- [ ] Test: Remote /plugin/load fails → other plugins still load
- [ ] Test: Service call fails → other services still callable

### ✅ Lifecycle Ordering
- [ ] Test: Call `/plugin/start` before `/plugin/load` → error or graceful rejection
- [ ] Test: Call service before `/plugin/start` → error or HTTP 503
- [ ] Test: Unload → services unregistered (not callable afterward)

### ✅ Metadata Validity
- [ ] Test: Metadata missing `name` field → proxy handles gracefully
- [ ] Test: Service `endpoint` invalid or unreachable → proxy logs error, service fails on call
- [ ] Test: Service `name` conflicts with existing service → proxy logs warning, registration may fail

### ✅ Concurrency & Race Conditions
- [ ] Test: Two concurrent calls to same service → both execute independently
- [ ] Test: Concurrent `/plugin/stop` and service call → service call fails gracefully, stop succeeds
- [ ] Test: Service registration + immediate call → race-free (service must be callable after on_load returns)

### ✅ HTTP Contract Consistency
- [ ] Test: Two different remote plugins (logger, metrics) → same lifecycle endpoint signatures
- [ ] Test: Request format consistent (GET has no body, POST has JSON body)
- [ ] Test: Response format consistent (all return JSON with `status` field)

### ✅ Documentation & Discovery
- [ ] [ ] Schema validation: metadata.services list is syntactically valid
- [ ] [ ] Proxy logs endpoint URLs for debugging
- [ ] [ ] Error messages include endpoint name and HTTP status

---

## Appendix: Reference Implementations

### Remote Plugin Template (Minimal)

```python
from fastapi import FastAPI, HTTPException

_state = {"loaded": False, "started": False}
app = FastAPI()

@app.get("/plugin/metadata")
async def metadata():
    return {
        "name": "my_plugin",
        "type": "system",
        "mode": "remote",
        "version": "0.1.0",
        "services": [
            {"name": "my.service", "endpoint": "/my/service", "method": "POST"}
        ]
    }

@app.post("/plugin/load")
async def load():
    if _state["loaded"]:
        return {"status": "already loaded"}
    _state["loaded"] = True
    return {"status": "ok"}

@app.post("/plugin/start")
async def start():
    if not _state["loaded"]:
        raise HTTPException(500, "not loaded")
    if _state["started"]:
        return {"status": "already started"}
    _state["started"] = True
    return {"status": "ok"}

@app.post("/plugin/stop")
async def stop():
    if not _state["started"]:
        return {"status": "already stopped"}
    _state["started"] = False
    return {"status": "ok"}

@app.post("/plugin/unload")
async def unload():
    _state["loaded"] = False
    return {"status": "ok"}

@app.post("/my/service")
async def my_service(request):
    body = await request.json()
    kwargs = body.get("kwargs", {})
    # Process service call
    return {"status": "ok", "result": ...}
```

### Proxy Expectations

Proxy (`RemotePluginProxy` class) expects:
1. HTTP GET `/plugin/metadata` accessible before lifecycle
2. Idempotent lifecycle endpoints (load, start, stop, unload)
3. Service endpoints respond within timeout (5s default)
4. All responses are JSON with top-level `"status"` field
5. HTTP 200 = success or already-done, HTTP 5xx = error

---

## Conclusion

This contract formalizes the proven pattern of `remote_logger` and `remote_metrics`.

**Summary:**
- **Core unchanged:** Only proxy and remote plugin use HTTP
- **Lifecycle clear:** load → start → stop → unload (all idempotent)
- **Services declared:** metadata.services → auto-registered → callable
- **Failures isolated:** Remote errors do not crash Core
- **Extensible:** New remote plugins use same contract

**Next Steps for SDK:**
1. Codify this contract in SDK documentation
2. Provide template + validation tools
3. Test against 3+ diverse remote plugin implementations
4. Establish HTTP client library (timeout, retry, logging)
