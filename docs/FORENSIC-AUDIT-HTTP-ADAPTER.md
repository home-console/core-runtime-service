# Forensic Architectural Audit: HTTP Adapter Layer

**Scope:** Security-critical kernel + module + plugin system.  
**Goal:** Identify why the HTTP adapter stopped working; structural analysis only. No refactor, no fixes, no improvement suggestions.

---

## 1. HTTP ENTRY POINT LOCATION

### 1.1 HTTP server implementation

| Item | Location |
|------|----------|
| **Framework** | FastAPI |
| **ASGI server** | uvicorn (`uvicorn.Server`, `server.serve()`) |
| **App creation** | `modules/api/module.py` — `ApiModule.register()` line 65: `self.app = FastAPI(...)` |
| **Server object creation** | `modules/api/module.py` — `ApiModule.start()` line 597: `self._server = uvicorn.Server(config)` |
| **Server start (bind + accept)** | `main.py` line 160: `await server.serve()` — **not** inside `runtime.start()` |

### 1.2 Who calls the start function

- **`runtime.start()`** is called from **`main()`** (main.py line 124).
- **`runtime.start()`** does **not** start the HTTP server. It only runs:
  - `module_manager.start_all()` → each module’s `start()`, including **ApiModule.start()**.
  - ApiModule.start() **creates** `uvicorn.Server` and stores it in `self._server`; it does **not** call `serve()`.
- **HTTP is actually started** in **main()** after `runtime.start()` returns:
  - main.py gets `server = getattr(api_module, "_server", None)` (line 130).
  - main.py then `await server.serve()` (line 160).

**Call graph (startup):**

```
asyncio.run(main)
  └─ main()
       ├─ CoreRuntime(...)                    # http = HttpRegistry() in __init__
       ├─ runtime.module_manager.register_module_specs(APP_MODULES)
       │    └─ for each spec: _register_module_by_name → module.register()
       │         └─ ApiModule.register()       # creates self.app = FastAPI(...), middleware, routers
       ├─ runtime.start()
       │    ├─ module_manager.start_all()
       │    │    └─ for each module: module.start()
       │    │         └─ ApiModule.start()     # sleep(0.2), runtime.http.list(), add_api_route for each; creates _server
       │    ├─ plugin_manager.auto_load_plugins()
       │    └─ plugin_manager.start_all()     # plugins run on_start() — register HTTP after routes already snapshotted
       ├─ api_module = runtime.module_manager.get_module("api")
       ├─ server = api_module._server
       └─ await server.serve()                # HTTP actually starts here (in main coroutine)
```

### 1.3 Invoked during system bootstrap?

- **App creation:** Yes — during bootstrap, in `ApiModule.register()` when `register_module_specs()` runs.
- **Route registration:** Yes — during bootstrap, in `ApiModule.start()` when `module_manager.start_all()` runs.
- **Server object creation:** Yes — during bootstrap, in `ApiModule.start()`.
- **`serve()` (bind + listen):** Yes — during bootstrap, but **after** `runtime.start()` returns, in `main()`.

So HTTP is **initialized** during bootstrap (app + routes + server object), but **started** (serve) only after the kernel and plugins have started, from the main coroutine.

---

## 2. BOOTSTRAP FLOW TRACE

### 2.1 Full startup sequence

```
main.py
   │
   ├─ _load_dotenv()
   ├─ Config.from_env()
   ├─ build_storage_stack(), CoreRuntime(storage_port, config, vault_port, state_engine)
   │     └─ core/runtime.py __init__: self.http = HttpRegistry()  [HTTP not started; only registry]
   │
   ├─ register_module_specs(runtime, APP_MODULES)
   │     └─ core/module_manager.py register_module_specs()
   │          └─ for each ModuleSpec: _register_module_by_name() → register(module)
   │               └─ modules/api/module.py ApiModule.register()
   │                    └─ Creates FastAPI app, middleware, include_router(monitoring, request_logger), adapters.http.bootstrap
   │
   ├─ runtime.start()
   │     └─ core/runtime.py start()
   │          ├─ module_manager.check_required_modules_registered()
   │          ├─ _hydrate_critical_state()
   │          ├─ module_manager.start_all()
   │          │     └─ core/module_manager.py start_all()
   │          │          └─ for module in _modules.values(): module.start()
   │          │               └─ ApiModule.start(): sleep(0.2), endpoints = runtime.http.list(), add_api_route for each;
   │          │                    creates uvicorn.Server, assigns to _server (no serve() call)
   │          ├─ plugin_manager.auto_load_plugins()
   │          ├─ plugin_manager.start_all()
   │          │     └─ plugins run on_start() — many call runtime.http.register() HERE (after route snapshot)
   │          ├─ dependency_resolver.validate_runtime_integrity()
   │          └─ state_engine.set("runtime.status", "running")
   │
   ├─ api_module = runtime.module_manager.get_module("api")
   ├─ server = getattr(api_module, "_server", None)
   ├─ [optional] loop.add_signal_handler(SIGINT, _on_sigint)
   └─ await server.serve()   ← HTTP listen/accept runs here (main coroutine)
```

### 2.2 Answers

- **Does runtime initialize HTTP?**  
  Runtime **creates** `HttpRegistry()` in `__init__`. It does **not** create the FastAPI app or uvicorn server; ApiModule does that in `register()` and `start()`.

- **Does module_manager register HTTP routes?**  
  No. Module_manager only calls `module.start()`. **ApiModule** registers routes in **its** `start()` by reading `runtime.http.list()` and calling `self.app.add_api_route()` for each endpoint.

- **Is HTTP adapter registered before modules?**  
  The **api** module is one of the modules; it is **registered** (and its `register()` creates the app) in the same pass as other modules. So HTTP app exists before any module `start()` runs.

- **Does HTTP depend on modules being loaded?**  
  Yes. ApiModule.start() calls `self.runtime.http.list()` — so it depends on **other modules and plugins** having already registered endpoints in `runtime.http`. In practice, **modules** register in their `register()` (before any `start()`), so module endpoints are present when ApiModule.start() runs. **Plugins** register in `on_start()`, which runs in `plugin_manager.start_all()` — i.e. **after** ApiModule.start() has already snapshotted `runtime.http.list()`. So plugin-registered HTTP routes are **not** added to the FastAPI app.

---

## 3. ROUTE REGISTRATION ANALYSIS

### 3.1 Mechanisms

- **Declarative contracts:** `runtime.http.register(HttpEndpoint(...))` — used by modules and plugins. Stored in `core/http_registry.py` HttpRegistry.
- **FastAPI route registration:** `self.app.add_api_route(ep.path, handler, methods=[ep.method])` — done in **ApiModule.start()** for every entry in `runtime.http.list()` at that moment.
- **Routers:** `self.app.include_router(...)` — used in ApiModule.register() for monitoring and request_logger (and adapters.http.bootstrap).

### 3.2 Static vs dynamic

- **Dynamic from registry:** Routes for `runtime.http` are registered **once** in ApiModule.start() from `runtime.http.list()`. No re-scan after plugins start.
- **Static in register():** Monitoring and request_logger routes are added in ApiModule.register() via include_router.

### 3.3 Who registers routes (in HttpRegistry)

- **Modules (in register()):** admin, agent, auth, operations, integrations, presence, product_api, devices (none), console (for CLI).  
  These run before ApiModule.start(), so they appear in `runtime.http.list()` when routes are built.
- **Plugins (in on_start()):** client-manager-service, yandex_device_auth, oauth_yandex, test/websocket_test_plugin, etc.  
  These run in plugin_manager.start_all(), **after** ApiModule.start(), so they do **not** appear in the snapshot and their routes are **not** mounted.

### 3.4 Conditional loading

- Request logger middleware and router: try/except ImportError (optional).
- CSRF and rate_limit middleware: try/except ImportError.
- adapters.http.bootstrap: try/except ImportError.
- If api_module or _server is missing, main() prints and does `await asyncio.Event().wait()` (no serve).

### 3.5 Module failure before route registration

- If a **required** module fails in `register()` or `start()`, `module_manager.start_all()` raises RuntimeError and `runtime.start()` fails. main() never reaches `get_module("api")` or `server.serve()`.
- If **ApiModule.start()** fails (e.g. exception before assigning `_server`), then `api_module._server` can be None and main() will not start HTTP (event.wait() path).

---

## 4. DEPENDENCY GRAPH ANALYSIS

### 4.1 HTTP-related files and imports

| File | Imports from |
|------|----------------------|
| **core/http_registry.py** | None (stdlib + typing only). No core.* or modules.*. |
| **core/runtime.py** | core.http_registry.HttpRegistry. Does not import modules.api or uvicorn. |
| **core/module_manager.py** | core.runtime_module, core.logger_helper. Does not import http_registry or api. |
| **modules/api/module.py** | core.runtime_module; modules.api.auth, authz, admin_access_middleware, monitoring, validation_models; modules.request_logger (optional); modules.api.csrf_middleware, security_headers; adapters.http.bootstrap; fastapi, uvicorn. |
| **modules/api/authz.py** | modules.api.auth (RequestContext); modules.api.auth.audit (audit_log_auth_event). |
| **modules/api/auth/** | core.auth_contextvars; core.errors (in some); runtime via request.app.state.runtime. |

### 4.2 Direct cross-module imports (HTTP layer)

- **modules/api/module.py** imports: MonitoringModule, request_logger (middleware, router), csrf_middleware, security_headers, auth, authz, admin_access_middleware, validation_models, adapters.http.bootstrap, core.runtime_module, core.errors.
- **HTTP does not import:** execution_router, plugin_manager, RiskEngine, MFAService, RotationExecutor, AgentControl, vault, SecretStore (no hits in modules/api).

### 4.3 Circular imports

- core.runtime → core.http_registry (no reverse).
- core.http_registry → no core or modules.
- modules.api.module → core.runtime_module, modules.*, adapters.http.bootstrap.  
  No evidence of core or module_manager importing modules.api at import time; api is loaded by module_manager via dynamic import (`modules.api` → ApiModule). So no circular import identified.

### 4.4 HTTP and plugin_manager

- HTTP layer (modules/api) does not import plugin_manager.
- Runtime holds both http (HttpRegistry) and plugin_manager; ApiModule receives runtime and uses runtime.http only. So HTTP depends on plugin_manager only indirectly (runtime); no direct dependency.

---

## 5. SECURITY LAYER ENTANGLEMENT

### 5.1 Security-sensitive calls inside HTTP layer

- **Authn:** require_auth_middleware (JWT, API key, session); reads storage (auth_config, sessions, api_keys, refresh_tokens, users), calls logger and audit.
- **Authz:** authz_require(context, endpoint.service, resource, runtime) before service_registry.call; can trigger audit_log_auth_event on failure.
- **Audit:** audit_log_auth_event (auth/audit.py) writes to runtime.storage (auth_audit_log namespace) and optionally logger.
- **Storage access (HTTP layer):** auth middleware and handlers use runtime.storage (auth_config, auth_api_keys, auth_sessions, auth_refresh_tokens, auth_users, auth_revoked, auth_audit_log, auth rate limits). Handler in module.py: storage.list_keys/get/set for first API key and device ACL.
- **Admin access:** admin_access_middleware returns 403 by IP (no vault/RBAC).
- **CSRF:** csrf_middleware uses core.security.CSRFProtection; rate_limit_middleware uses core.security.RateLimiter.
- **Service calls:** All API handlers call `runtime.service_registry.call(endpoint.service, ...)`; domain services may touch vault/storage/rotation/agents — but that is outside the HTTP layer itself.

### 5.2 What HTTP does not do

- Does not call RiskEngine, MFAService, RotationExecutor, AgentControl, SecretStore, or vault directly.
- Does not implement rotation or agent control; only calls services by name.

---

## 6. FAILURE POINT ANALYSIS (RANKED)

Based on structure only:

1. **HTTP server never started because `serve()` is not in runtime.start()**  
   `serve()` is invoked only in main() after runtime.start(). If main() never reaches that line (e.g. runtime.start() hangs or raises), HTTP never starts. So any hang or exception in runtime.start() (e.g. in plugin_manager.start_all()) prevents the process from reaching `await server.serve()`.

2. **server is None**  
   If api_module is missing or ApiModule.start() did not set _server (e.g. exception before assignment, or start() skipped because app is None), main() gets server is None and runs `await asyncio.Event().wait()` instead of serve(). So HTTP never starts and no error is raised.

3. **Uvicorn signal handling**  
   If uvicorn’s default signal handling runs (e.g. capture_signals not overridden), it can conflict with main()’s SIGINT handling or with running inside an existing event loop, and can affect whether serve() binds or exits as expected.

4. **Route registration timing vs plugins**  
   ApiModule.start() snapshots `runtime.http.list()` during module_manager.start_all(). Plugins register endpoints in on_start() during plugin_manager.start_all(), which runs later. So plugin-registered routes are never passed to add_api_route. Result: plugin HTTP endpoints are missing from the app (structural; may or may not be the cause of “HTTP stopped working” depending on which endpoints are required).

5. **Async event loop / single loop**  
   serve() runs in the same event loop as main(). If something in that loop blocks (e.g. a synchronous call or a deadlock in service_registry/storage used by middleware), the loop could block and HTTP could appear not to respond.

6. **Exception swallowed**  
   If ApiModule.start() or the code that creates _server raises and the exception is caught and not re-raised (e.g. in module_manager or runtime), _server might never be set and main() would fall into the “server is None” path.

7. **Module start order**  
   start_all() iterates _modules.values(). If ApiModule.start() runs and depends on another module’s side effect (e.g. http registry entries), order matters. Currently modules register http in register(), so by start() time the registry already has module endpoints; the main ordering issue is plugins vs ApiModule.start().

---

## 7. ARCHITECTURAL CLASSIFICATION

**Classification: B) Mixed orchestration layer, with traits of D) Kernel entangled layer.**

**Reasoning:**

- **Thin transport (A):** The HTTP layer is **not** a thin adapter. It creates the FastAPI app, mounts middleware (auth, CSRF, rate limit, admin access, security headers, request logger), performs authn/authz and audit at the boundary, and calls service_registry.call() for business logic. So it both transports and orchestrates security and routing.

- **Mixed orchestration (B):** It fits “mixed orchestration”: it orchestrates request flow (middleware order), enforces authn/authz/CSRF/rate limit, and delegates to services. It does not implement domain logic but decides who may call which service and logs/auths at the boundary.

- **Security decision layer (C):** It **does** make security decisions (authz_require, admin_access_middleware, CSRF, rate limit) and emits audit (audit_log_auth_event). So it has a strong “security decision layer” component, but is not only that — it also builds routes and starts the server.

- **Kernel entangled (D):** It is entangled with the kernel in the sense that: (1) server object is created inside a kernel module (ApiModule) but started from main(); (2) it reads runtime.http (kernel registry) once at start(); (3) it uses runtime.storage and runtime.service_registry throughout request handling. So startup and request handling are tied to kernel lifecycle and kernel registries.

**Conclusion:** The HTTP layer is a **mixed orchestration and security boundary** that is tightly coupled to the kernel (runtime, http registry, storage, service_registry) and started from the application entrypoint (main()) rather than fully inside the kernel’s start sequence.

---

## FINAL OUTPUT SUMMARY

| # | Topic | Result |
|---|--------|--------|
| 1 | **HTTP entry point** | App created in `modules/api/module.py` ApiModule.register(); server in ApiModule.start(); **start (serve) in main.py** with `await server.serve()`. |
| 2 | **Startup call graph** | main() → register_module_specs (api.register) → runtime.start() (start_all → ApiModule.start() creates _server) → main() gets server → await server.serve(). |
| 3 | **Route registration** | Dynamic from runtime.http.list() in ApiModule.start() (one snapshot); plugins register after that, so plugin routes not mounted. |
| 4 | **Direct module imports** | ApiModule imports core.runtime_module, modules.api.* (auth, authz, admin_access, csrf, security_headers, validation_models), modules.monitoring, modules.request_logger, adapters.http.bootstrap. No execution_router, plugin_manager, RiskEngine, MFAService, RotationExecutor, AgentControl, vault, SecretStore. |
| 5 | **Security logic in HTTP** | Authn (JWT/API key/session), authz (authz_require + audit on failure), audit (storage + logger), storage (auth namespaces), admin IP check, CSRF, rate limit. No direct vault/RBAC/MFA/rotation/agent. |
| 6 | **Most likely failure cause** | (1) runtime.start() never returns or raises so main() never reaches server.serve(); (2) server is None (api_module or _server missing); (3) uvicorn signal/loop behavior; (4) plugin routes missing due to snapshot timing. |
| 7 | **Architectural classification** | B) Mixed orchestration layer with strong security-decision and D) kernel-entangled traits; server start split between kernel (module start) and main(). |
