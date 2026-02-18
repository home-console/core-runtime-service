# ARCHITECTURE: Module vs Plugin Boundary Analysis

**Date**: 2026-02-18  
**Status**: DEFINITIVE (foundational architecture freeze)  
**Purpose**: Establish strict architectural boundaries before Step 20+

---

## 1. BOUNDARY DEFINITION: Module vs Plugin

### 1.1 Module Characteristics

| Aspect | Module | Rationale |
|--------|--------|-----------|
| **Load Time** | Mandatory at boot | Core system incompleteness without it |
| **Removal** | Cannot be deleted | Breaking system invariants |
| **Trust Level** | Full (same process)| Integral part of trusted kernel |
| **Lifecycle** | System events (`init()`, `shutdown()`, `health_check()`) | Participates in system bootstrap/teardown |
| **Capabilities** | Unrestricted access to internals | Controls critical invariants |
| **Storage Access** | Direct DB + Cache + Vault | System-level state management |
| **Audit Integration** | **Required** to emit events | Auditable system operations |
| **Background Tasks** | Can create & manage | System-level scheduling |
| **Dependency Graph** | Can declare forward/backward deps | Kernel composition rule |
| **Replacement** | Not swappable during runtime | Recompile/redeploy cycle |

### 1.2 Plugin Characteristics

| Aspect | Plugin | Rationale |
|--------|--------|-----------|
| **Load Time** | Optional (marketplace install) | Enhancement to system |
| **Removal** | Can be deleted safely | No system breakage |
| **Trust Level** | Untrusted code | External/user-contributed |
| **Lifecycle** | Hook only: `on_install()`, `on_uninstall()` | No participation in system boot |
| **Capabilities** | Public SDK only + declared permissions | Sandbox enforcement |
| **Storage Access** | Namespaced key-value store | Isolated per-plugin |
| **Audit Integration** | Optional (calls `audit.emit()` API) | Plugins can audit own actions |
| **Background Tasks** | Limited: deferred queues only | No direct thread/process control |
| **Dependency Graph** | Can only depend on Modules (read-only) | Never on other Plugins |
| **Replacement** | Swappable: disable/enable at runtime | No restart needed |
| **Failure Isolation** | Errors don't crash system | Graceful degradation |

---

## 2. ARCHITECTURAL TRUST & ACCESS LAYERS

### 2.1 Storage Access Model

```
┌─────────────────────────────────────────────────┐
│               CORE KERNEL                       │
│  ├─ Operation Log (immutable hash chain)        │
│  ├─ Vault (master secrets, mlock'd)            │
│  ├─ Audit Log (signed, timestamped)            │
│  └─ System State (epoch + merkle verified)     │
└─────────────────────────────────────────────────┘
              ↑ Direct access (Modules only)
              
┌─────────────────────────────────────────────────┐
│            SYSTEM INTERFACE LAYER               │
│  ├─ Credential Store (read authorized creds)   │
│  ├─ Operation Queue (read-only operations)     │
│  ├─ Audit Events (emit-only for plugins)       │
│  └─ Metrics (counter/gauge registration)       │
└─────────────────────────────────────────────────┘
              ↑ Controlled API (Modules + Plugins)
              
┌─────────────────────────────────────────────────┐
│           PLUGIN SANDBOX LAYER                  │
│  ├─ Plugin Storage (namespaced KV per plugin)   │
│  ├─ Plugin Events (publish/subscribe within PG) │
│  └─ Plugin Metrics (own counters only)          │
└─────────────────────────────────────────────────┘
              ↑ Restricted API (Plugins only)
```

### 2.2 Security Primitives Access

| Primitive | Core | System Module | Plugin | Enforcement |
|-----------|------|---------------|--------|-------------|
| **mlock/secure_memory** | ✅ | ✅ | ❌ | Capability check at init |
| **core_dump disable** | ✅ | ✅ | ❌ | OS-level, applies to process |
| **vault_unlock** | ✅ | ✅ | ❌ (read-only secrets) | Guarded by permission system |
| **epoch_bump** | ✅ | ⚠️ (specific modules) | ❌ | Audit log tracks who |
| **audit.emit** | ✅ | ✅ | ✅ (limited) | Event type whitelist |
| **ptrace_disable** | ✅ | ✅ | ❌ | Process-wide, can't revoke |

---

## 3. LIFECYCLE HOOKS: Module vs Plugin

### 3.1 Module Lifecycle (Mandatory)

**System boot sequence:**
```
1. Core kernel initializes (vault, storage, audit)
2. Load System Modules in dependency order
3. For each Module: call init(kernel_context)
   - Declares capabilities needed
   - Registers handlers
   - Verifies preconditions
   - Returns ready status
4. If any Module.init() fails → System FAILED (abort boot)
5. Begin accepting external requests
6. On shutdown: call Module.shutdown() in reverse order
```

**Runtime hooks (optional per module):**
```
- health_check() → Called by supervisor, emit metrics
- on_credential_rotation() → Notified when creds rotate
- on_policy_update() → Notified of permission changes
- on_vault_unlock() → Can react to unlock events
```

### 3.2 Plugin Lifecycle (Lightweight)

**Plugin install:**
```
1. Verify signature (code signing Step 18)
2. Extract to plugins/{plugin_id}/
3. Load plugin module (Python import)
4. Call plugin.on_install(plugin_context)
   - Can read config
   - Can check dependencies
   - Cannot modify system state
5. Register hook handlers
6. Mark as enabled
7. Continue serving requests (no restart needed)
```

**Plugin removal:**
```
1. Call plugin.on_uninstall()
   - Clean own storage
   - Deregister handlers
2. Unload module
3. Delete from plugins/{plugin_id}/
```

**Runtime hooks (optional):**
```
- on_event(event) → Async listener for emitted events
- on_request_intercept(request) → Can modify request pre-processing
- on_response_transform(response) → Can transform response
```

---

## 4. CAPABILITY ENFORCEMENT MODEL

### 4.1 Module Capability Declaration

```python
class CredentialModule(BaseModule):
    """System module for credential management."""
    
    REQUIRED_CAPABILITIES = [
        'vault.read',           # Direct vault access
        'storage.write',        # Direct DB writes
        'audit.emit',           # Emit audit events
        'operation.execute',    # Run operations
    ]
    
    OPTIONAL_CAPABILITIES = [
        'background.spawn',     # Create background tasks
    ]
    
    def init(self, kernel):
        kernel.check_capabilities(self.REQUIRED_CAPABILITIES)
        # All capabilities available unconditionally
        self.vault = kernel.vault
        self.storage = kernel.storage
```

### 4.2 Plugin Capability Declaration

```python
class MyPlugin(BasePlugin):
    """User plugin for custom logic."""
    
    REQUIRED_PERMISSIONS = [
        'credentials.read',     # Read credential metadata only
        'audit.emit:custom.event',  # Emit custom event type
    ]
    
    OPTIONAL_PERMISSIONS = [
        'storage.read:plugin',  # Read own namespaced storage
    ]
    
    def on_install(self, plugin_context):
        # Plugin context provides guarded access
        perms = plugin_context.check_permissions(self.REQUIRED_PERMISSIONS)
        if not perms['credentials.read']:
            raise PermissionDenied("Need credentials.read")
        
        # Cannot access vault directly
        # self.vault = plugin_context.vault  ← AttributeError
        
        # Can only emit whitelisted event types
        plugin_context.audit.emit('custom.event', {'data': ...})
```

---

## 5. COMPONENT CLASSIFICATION MATRIX

| Component | Current | **Recommended** | Rationale | Risk if Wrong |
|-----------|---------|-----------------|-----------|--------------|
| **agent_control** | Mixed | **Module** | Controls agent bootstrap & lifecycle; security-critical | Code injection if Plugin |
| **client_manager** | ? | **Module** | Manages client connections, auth tokens; architectural | Unauthorized client access |
| **CredentialRepository** | Module | ✅ **Module** | Stores sensitive credential metadata; audit required | Bypass all access control |
| **RiskEngine** | ? | **Module** | Tracks risk state, feeds auth decisions; can't be deleted | System becomes insecure |
| **MFAService** | ? | **Module** | Authentication gate; system-critical | Bypass 2FA entirely |
| **TrustEngine** | ? | **Module** | Trust state machine; feeds auth layer | Trust decisions become unreliable |
| **rotation_strategies** | ? | **Plugin** | User-defined rotation logic; can vary per deployment | One bad strategy crashes? No, sandboxed |
| **risk_extensions** | ? | **Plugin** | Custom risk models (fraud detection, etc.) | Doesn't need system-level access |
| **audit_reporters** | Mixed | **Plugin** | Custom audit output (Splunk, Datadog, etc.) | Plugins can integrate via audit SDK |
| **marketplace_sync** | ? | **Module** | Syncs plugin catalog, verifies signatures, updates code | Compromised sync = trojanized plugins |
| **webhook_handlers** | ? | **Plugin** | Custom webhooks (PagerDuty, Slack alerts) | Isolated sandbox fine |

---

## 6. FORMALIZED API SURFACES

### 6.1 Module API Surface (Full Access)

```python
class KernelContext:
    """Passed to Module.init() - unrestricted system interface."""
    
    # Core access
    vault: VaultManager           # Unlock, get master secrets
    storage: StorageManager       # Raw DB, transaction control
    audit: AuditLogger            # Emit immutable audit events
    operation_log: OperationLog   # Append to operation journal
    
    # Lifecycle
    register_handler(event_type, handler)
    register_background_task(name, coro)
    
    # Capability enforcement
    check_capabilities(required_caps: List[str]) → bool
    
    # System state
    @property
    def system_state() → SystemState  # Read current epoch/merkle
    
    # Health & metrics
    register_metric(name, type, help_text)
```

**Example: CredentialModule using full API**

```python
class CredentialModule(BaseModule):
    def init(self, kernel):
        kernel.check_capabilities(['vault.read', 'storage.write', 'audit.emit'])
        
        # Direct vault access
        master_key = kernel.vault.unlock(passphrase)
        
        # Direct DB access with transactions
        with kernel.storage.transaction():
            kernel.storage.execute(
                "INSERT INTO credentials (id, name) VALUES (?, ?)",
                (cred_id, name)
            )
            kernel.audit.emit('credential.created', {'id': cred_id})
        
        # Register system hooks
        kernel.register_handler('vault.unlock', self.on_vault_unlock)
        kernel.register_background_task('rotation_ticker', self.rotation_loop)
```

### 6.2 Plugin API Surface (Sandboxed)

```python
class PluginContext:
    """Passed to Plugin.on_install() - sandbox interface."""
    
    # Guarded credential access
    credentials: CredentialAPI    # read-only, namespaced by plugin
    
    # Audit (emit-only, whitelist)
    audit: AuditAPI               # emit(event_type, data) - types must be whitelisted
    
    # Plugin storage (isolated KV)
    storage: PluginStorageAPI     # get(key), set(key, value, ttl)
    
    # Event bus (within plugin namespace)
    events: PluginEventBusAPI     # publish(topic), subscribe(topic, handler)
    
    # Metrics (plugin-scoped)
    metrics: MetricsAPI           # counter, gauge, histogram
    
    # Permissions check
    check_permissions(required: List[str]) → Dict[str, bool]
    
    # Error handling
    class PermissionDenied(Exception): pass
    class QuotaExceeded(Exception): pass
```

**Example: RotationStrategy plugin**

```python
class CustomRotationPlugin(BasePlugin):
    """User-defined rotation logic."""
    
    REQUIRED_PERMISSIONS = ['credentials.read', 'audit.emit:rotation.custom']
    
    def on_install(self, ctx):
        perms = ctx.check_permissions(self.REQUIRED_PERMISSIONS)
        assert perms['credentials.read'], "Need creds.read"
        
        # Register event handler (within plugin namespace)
        ctx.events.subscribe('rotation.ticker', self.rotate_custom)
    
    def rotate_custom(self, event, ctx):
        # Can read creds (metadata only, not vault secrets)
        creds = ctx.credentials.list(namespace='app')
        
        # Cannot access vault directly
        # ctx.vault ← AttributeError!
        
        # Can emit custom audit events
        ctx.audit.emit('rotation.custom', {'rotated': len(creds)})
        
        # Limited background work (via deferred queue)
        ctx.defer_task('custom_rotation', creds)
```

---

## 7. SANDBOX ENFORCEMENT RULES

### 7.1 What Plugins CAN'T Do

| Restriction | Enforcement | Consequence |
|-------------|-------------|------------|
| Access raw vault | TypeError at import | PermissionDenied |
| Direct DB writes | No StorageManager in API | AttributeError |
| Create OS threads | Not in PluginContext | Blocked by monitor |
| Call ptrace/core dump disable | Not available in context | Feature doesn't exist in sandbox |
| Import `core.security.vault` directly | Import guard (sys.modules intercept) | ImportError |
| Use unrestricted audit.emit | Event type whitelist checked | AuditEventTypeNotAllowed |
| Access other plugin storage | Namespace enforcement at KV layer | KeyError (namespace not found) |
| Infinite loops / DoS | Task timeout + CPU quota | QuotaExceeded exception |

### 7.2 What Modules CAN'T Do

| Restriction | Enforcement | Consequence |
|-------------|-------------|------------|
| Bypass audit logging | All storage ops tracked | StateCompromised exception |
| Modify epoch without operation | Transaction guard | OperationNotRecorded exception |
| Store plaintext secrets | SecureBytes enforced | TypeError on assignment |
| Ignore health checks | Supervisor monitors | Marked unhealthy, restart |
| Declare false capabilities | runtime check vs actual usage | SecurityViolation exception |

---

## 8. THREE-LEVEL ARCHITECTURE MODEL

### 8.1 Proposed Model

```
LEVEL 1: CORE KERNEL
├─ Operation Log (immutable, hash-chained)
├─ Vault (mlock'd master secrets)
├─ Audit Log (signed, timestamped)
├─ EpochManager (versioning + rollback detection)
├─ StorageManager (SQLite + WAL)
└─ SecurityHardening (ptrace disable, core dump, mlockall)

LEVEL 2: SYSTEM MODULES (mandatory at boot)
├─ CredentialModule
│  ├─ CredentialRepository (credential metadata)
│  ├─ CredentialDomain (entity models)
│  └─ AccessControl (policy enforcement)
├─ SecurityModule
│  ├─ MFAService (elevation gates)
│  ├─ RiskEngine (anomaly scoring)
│  ├─ TrustEngine (trust state machine)
│  └─ PolicyEngine (RBAC rules)
├─ OperationModule
│  ├─ RotationExecutor (credential rotation core)
│  ├─ SchedulerService (background tasks)
│  └─ EventBus (internal async events)
├─ AuditModule
│  ├─ AuditLogger (emit events)
│  ├─ SigningService (event signing)
│  └─ RetentionPolicy (cleanup rules)
└─ AgentModule
   ├─ AgentRegistry (agent metadata)
   ├─ AgentControl (command routing)
   ├─ ClientManager (connection lifecycle)
   └─ TokenService (session tokens)

LEVEL 3: USER PLUGINS (optional, installable)
├─ CustomRotationStrategy
├─ RiskExtension (fraud detection)
├─ AuditReporter (Splunk/Datadog integration)
├─ WebhookHandler (PagerDuty/Slack)
└─ [User-defined plugins]
```

### 8.2 Why Three Levels?

| Level | Purpose | Why Separate |
|-------|---------|------------|
| **Core** | Irreducible kernel | Can't be disabled; foundational guarantees |
| **Modules** | System completeness | Must boot with kernel; architectural role |
| **Plugins** | User customization | Optional; safe to remove; don't affect core |

---

## 9. ARCHITECTURAL RISKS & MITIGATION

### 9.1 Risk: Plugin Privilege Escalation

**Risk**: Plugin uses import tricks to access `core.security.vault` directly

**Mitigation**:
```python
# At system init, intercept all imports
import sys
sys.modules['core.security.vault'] = None  # Make inaccessible

# Plugin import → ImportError
class PluginSandbox:
    def check_imports(self, module_code):
        forbidden = ['core.security.vault', 'core.storage', 'core.audit']
        for name in forbidden:
            if f"import {name}" in module_code:
                raise SecurityViolation(f"Forbidden import: {name}")
```

**Enforcement**: AST analysis of plugin source + runtime import guard

---

### 9.2 Risk: Module Overweight (Too Much Logic in Core)

**Risk**: Operations team keeps adding logic to CredentialModule → bloats core

**Metric-based policy**:
```
CredentialModule MAX SIZE policy:
├─ 5,000 lines MAX (currently ~2,000)
├─ If exceeds → move logic to Plugin
└─ Code review gate: "Can this be a plugin?"
```

**Split strategy**:
- Keep: credential lifecycle, policy enforcement, audit
- Move to plugin: custom rotation strategies, fraud rules

---

### 9.3 Risk: Agent Control Logic in Core

**Risk**: AgentModule grows to handle all agent orchestration → couples to agent lifecycle

**Boundary rule**:
```
AgentModule responsibilities:
✅ Agent registration & lifecycle events
✅ Client connection management
✅ Token issuance & validation
❌ Agent command execution logic (→ Plugin)
❌ Agent-specific policies (→ Plugin + RBAC)
❌ Agent monitoring/compliance (→ Plugin + audit)
```

**Implementation**: AgentModule → thin registry + auth layer
All command logic → `agent_control` Module (separate concern)

---

### 9.4 Risk: Plugin as Plugin (Cascading Dependencies)

**Risk**: PluginA depends on PluginB; PluginB uninstalled → PluginA breaks

**Solution**: No plugin-to-plugin dependencies
```python
class PluginRegistry:
    def register(self, plugin, dependencies):
        for dep in dependencies:
            if dep not in SYSTEM_MODULES:
                raise InvalidDependency(
                    f"Plugins can only depend on Modules, not {dep}"
                )
```

**Allowed**:
```
CustomRotationPlugin → depends on RotationExecutor (Module) ✅
```

**Forbidden**:
```
CustomRotationPlugin → depends on RiskExtensionPlugin ❌
```

---

## 10. FORMALIZED BOUNDARIES: DECISION TABLE

| Question | Answer | Rationale | Place |
|----------|--------|-----------|-------|
| Does system fail without it? | YES | → System Module | core/modules/ |
| | NO | → Plugin or User code | plugins/ |
| Does it manipulate core state (epoch, merkle)? | YES | → System Module | core/modules/ |
| | NO | → Could be Plugin | plugins/ |
| Does it emit audit events? | YES (required) | → Module | core/modules/ |
| | OPTIONAL | → Could be Plugin | plugins/ |
| Does it need vault access? | YES | → Module | core/modules/ |
| | NO (read-only) | → Plugin | plugins/ |
| Does it run at system boot? | YES | → Module | core/modules/ |
| | NO | → Plugin or User | plugins/ |
| Can user safely remove it? | YES | → Plugin | plugins/ |
| | NO | → Module | core/modules/ |
| Does it accept user config? | YES(static config per deployment) | → Plugin | plugins/ |
| | NO | → Core/Module | core/ |

---

## 11. FINAL COMPONENT CLASSIFICATION

### 11.1 Definitive Assignments

#### **LEVEL 1: Core Kernel** (Non-negotiable)
```
✅ Vault (master secrets management)
✅ StorageManager (SQLite + durability guarantees)
✅ AuditLog (immutable event store)
✅ EpochManager (versioning)
✅ SecurityHardening (mlock, core dump, ptrace disable)
✅ OperationLog (hash-chained journal)
```

#### **LEVEL 2: System Modules** (Mandatory boot)
```
MODULE: Credentials
  ✅ CredentialRepository (credential lifecycle)
  ✅ CredentialDomain (entity models)
  ✅ AccessControl (policy enforcement)

MODULE: Security
  ✅ MFAService (elevation control)
  ✅ RiskEngine (real-time scoring)
  ✅ TrustEngine (trust state machine)
  ✅ PolicyEngine (RBAC + rules)
  ✅ PolicyEnforcer (policy application)

MODULE: Operations
  ✅ RotationExecutor (credential rotation core loop)
  ✅ SchedulerService (background task management)
  ✅ EventBus (internal async dispatching)

MODULE: Audit
  ✅ AuditLogger (emit events with signatures)
  ✅ AuditEventBinder (event routing)
  ✅ SigningService (cryptographic signing)

MODULE: Agent
  ✅ AgentRegistry (agent metadata + lifecycle)
  ✅ AgentControl (command routing + execution)
  ✅ ClientManager (connection management)
  ✅ TokenService (session token lifecycle)
```

#### **LEVEL 3: User Plugins** (Optional, installable)
```
PLUGIN: RotationStrategies
  ✅ CustomRotationStrategy (user-defined rotation)
  ✅ RotationSchedule (custom timing rules)

PLUGIN: RiskExtensions
  ✅ FraudDetectionEngine (custom anomaly rules)
  ✅ BehavioralAnalysisPlugin (user-defined models)

PLUGIN: AuditReporters
  ✅ SplunkConnector (export audit to Splunk)
  ✅ DatadogConnector (export to Datadog)
  ✅ CustomLogForwarder (user-defined sinks)

PLUGIN: Webhooks
  ✅ PagerDutyIntegration (on-call alerting)
  ✅ SlackNotifications (team alerts)
  ✅ CustomWebhook (user endpoints)

PLUGIN: Custom User Logic
  ✅ [Any custom business logic]
```

---

## 12. ARCHITECTURAL DIAGRAM: Final Design

```
╔════════════════════════════════════════════════════════════════════╗
║                          USER PLUGINS (LEVEL 3)                   ║
║  [Custom Rotation]  [Fraud Detection]  [AuditReporter]  [Webhook] ║
║  [Marketplace Sync] [Custom Extensions]  ...                      ║
╚════════════════════════════════════════════════════════════════════╝
                    ↑ Plugin SDK (sandboxed)
                    
╔════════════════════════════════════════════════════════════════════╗
║                     SYSTEM MODULES (LEVEL 2)                      ║
║                                                                    ║
║  ┌──────────┬──────────┬──────────┬──────────┬───────────┐        ║
║  │Credential│ Security │Operation │  Audit   │  Agent    │        ║
║  │  Module  │ Module   │ Module   │  Module  │  Module   │        ║
║  │          │          │          │          │           │        ║
║  │Repo Auth │MFA Risk  │  Rotation│ Logger   │ Registry  │        ║
║  │Policy    │Trust RBAC│Scheduler │ Binder   │ Control   │        ║
║  │Access    │Engine    │EventBus  │ Signing  │ ClientMgr │        ║
║  └──────────┴──────────┴──────────┴──────────┴───────────┘        ║
║                                                                    ║
║                    ↓ Unrestricted internal API                    ║
╚════════════════════════════════════════════════════════════════════╝
                            ↑ KernelContext
                            
╔════════════════════════════════════════════════════════════════════╗
║                    CORE KERNEL (LEVEL 1)                          ║
║                                                                    ║
║  ┌─────────────────────────────────────────────────────────┐      ║
║  │ OperationLog: Hash-chained journal (append-only)        │      ║
║  │   Each op = {op_id, timestamp, hash(prev), data}        │      ║
║  └─────────────────────────────────────────────────────────┘      ║
║  ┌─────────────────────────────────────────────────────────┐      ║
║  │ Vault: mlock'd master secrets                           │      ║
║  │   - Unlock (Argon2id)                                   │      ║
║  │   - Derive keys (HKDF)                                  │      ║
║  │   - Zeroize on lock                                     │      ║
║  └─────────────────────────────────────────────────────────┘      ║
║  ┌─────────────────────────────────────────────────────────┐      ║
║  │ StorageManager: SQLite + WAL                            │      ║
║  │   - Transactions (ACID)                                 │      ║
║  │   - Durability (synchronous=FULL)                       │      ║
║  │   - Epoch tracking                                      │      ║
║  └─────────────────────────────────────────────────────────┘      ║
║  ┌─────────────────────────────────────────────────────────┐      ║
║  │ AuditLog: Signed, timestamped events                    │      ║
║  │   - Hash chain (like Operation Log)                     │      ║
║  │   - Immutable (no deletes, only appends)                │      ║
║  │   - Periodic signing checkpoints                        │      ║
║  └─────────────────────────────────────────────────────────┘      ║
║  ┌─────────────────────────────────────────────────────────┐      ║
║  │ SecurityHardening: Process-level protections            │      ║
║  │   - ptrace disabled (PR_SET_DUMPABLE=0)                 │      ║
║  │   - core dumps disabled (RLIMIT_CORE=0)                 │      ║
║  │   - mlockall (no swap)                                  │      ║
║  └─────────────────────────────────────────────────────────┘      ║
║  ┌─────────────────────────────────────────────────────────┐      ║
║  │ Loader: Module & Plugin discovery + lifecycle           │      ║
║  │   - Module init at boot (mandatory)                     │      ║
║  │   - Plugin install/uninstall (optional)                 │      ║
║  │   - Permission checking                                │      ║
║  └─────────────────────────────────────────────────────────┘      ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
           ↑ Direct DB, vault, audit access (no sandbox)
           
     ┌───────────────┬───────────────┬──────────────┐
     ↓               ↓                ↓              ↓
   SQLite         Config Files    Credentials    Filesystem
```

---

## 13. API ENFORCEMENT: Code-Level Guards

### 13.1 Module Init Guard

```python
# In core/loader.py - prevents Plugin from calling Module.init()

class ModuleLoader:
    def load_module(self, module_path: str) -> BaseModule:
        """Load system module with full access."""
        spec = importlib.util.spec_from_file_location(module_path)
        module = importlib.util.module_from_spec(spec)
        
        # Full kernel context
        kernel_ctx = KernelContext(
            vault=self.vault,           # Direct access
            storage=self.storage,       # Direct access
            audit=self.audit,           # Direct access
        )
        
        spec.loader.exec_module(module)
        return module.ModuleClass().init(kernel_ctx)

class PluginLoader:
    def load_plugin(self, plugin_path: str) -> BasePlugin:
        """Load user plugin with sandboxed access."""
        spec = importlib.util.spec_from_file_location(plugin_path)
        module = importlib.util.module_from_spec(spec)
        
        # Sandboxed context only
        plugin_ctx = PluginContext(
            credentials=CredentialAPI(kernel, namespace=plugin_id),
            audit=AuditAPI(kernel, allowed_event_types=['custom.*']),
            storage=PluginStorageAPI(kernel, namespace=plugin_id),
        )
        
        spec.loader.exec_module(module)
        return module.PluginClass().on_install(plugin_ctx)
```

### 13.2 Import Guard

```python
# At system init, make sensitive packages inaccessible to plugins

import sys

FORBIDDEN_TO_PLUGINS = [
    'core.security.vault',
    'core.storage',
    'core.audit',
    'core.security.hardening',
]

def lockdown_imports():
    """Prevent plugins from importing sensitive internals."""
    for module_name in FORBIDDEN_TO_PLUGINS:
        sys.modules[module_name] = None
    
    # Also intercept __import__ at plugin load time
    
class PluginSandbox:
    def __init__(self):
        self.original_import = __builtins__.__import__
    
    def sandboxed_import(self, name, *args, **kwargs):
        if name in FORBIDDEN_TO_PLUGINS:
            raise ImportError(f"Forbidden: {name} not available in plugin context")
        return self.original_import(name, *args, **kwargs)
    
    def enter(self):
        __builtins__.__import__ = self.sandboxed_import
```

---

## 14. DEPLOYMENT MODEL: Module vs Plugin Placement

### 14.1 Directory Structure

```
core-runtime-service/
├── core/
│   ├── __init__.py
│   ├── kernel.py              ← CORE KERNEL
│   ├── vault.py               ← CORE
│   ├── storage.py             ← CORE
│   ├── audit.py               ← CORE
│   ├── loader.py              ← Bootstrap (Module + Plugin loading)
│   │
│   ├── modules/               ← SYSTEM MODULES (mandatory at boot)
│   │   ├── credentials/       ← CredentialModule
│   │   │   ├── __init__.py
│   │   │   ├── repository.py
│   │   │   ├── domain.py
│   │   │   └── access_control.py
│   │   ├── security/          ← SecurityModule
│   │   │   ├── __init__.py
│   │   │   ├── mfa/
│   │   │   ├── risk/
│   │   │   └── trust/
│   │   ├── operations/        ← OperationModule
│   │   │   ├── __init__.py
│   │   │   ├── rotation/
│   │   │   └── scheduler.py
│   │   ├── audit/             ← AuditModule
│   │   │   ├── __init__.py
│   │   │   ├── logger.py
│   │   │   └── signing.py
│   │   └── agent/             ← AgentModule
│   │       ├── __init__.py
│   │       ├── registry.py
│   │       └── control.py
│   │
│   └── plugin_sdk/            ← Public API for plugins
│       ├── __init__.py
│       ├── base.py            (BasePlugin class)
│       ├── context.py         (PluginContext)
│       ├── credential_api.py
│       ├── audit_api.py
│       ├── storage_api.py
│       └── errors.py

plugins/                        ← USER PLUGINS (optional, installable)
├── custom_rotation/
│   ├── __init__.py
│   ├── strategies.py
│   └── tests.py
├── fraud_detection/
│   ├── __init__.py
│   ├── engine.py
│   └── tests.py
├── audit_reporters/
│   ├── __init__.py
│   ├── splunk.py
│   ├── datadog.py
│   └── tests.py
└── webhooks/
    ├── __init__.py
    ├── pagerduty.py
    ├── slack.py
    └── tests.py
```

### 14.2 Bootstrap Sequence

```python
# In main.py - system startup

def main():
    # Step 1: Initialize core kernel
    kernel = CoreKernel()
    kernel.init_vault()
    kernel.init_storage()
    kernel.init_audit()
    
    # Step 2: Load system modules (mandatory)
    loader = ModuleLoader(kernel)
    
    modules_to_load = [
        'core.modules.credentials',      # CredentialModule
        'core.modules.security',         # SecurityModule
        'core.modules.operations',       # OperationModule (pulls RotationExecutor)
        'core.modules.audit',            # AuditModule
        'core.modules.agent',            # AgentModule
    ]
    
    for module_path in modules_to_load:
        try:
            module = loader.load_module(module_path)
            print(f"✅ Loaded {module_path}")
        except Exception as e:
            print(f"❌ Failed to load {module_path}: {e}")
            sys.exit(1)  # Critical failure
    
    # Step 3: Load user plugins (optional)
    plugin_loader = PluginLoader(kernel)
    
    plugin_dir = Path('plugins')
    for plugin_path in plugin_dir.iterdir():
        try:
            plugin = plugin_loader.load_plugin(str(plugin_path))
            print(f"⚠️  Loaded plugin {plugin_path.name}")
        except Exception as e:
            # Plugin failure is non-fatal
            print(f"⚠️  Failed to load plugin {plugin_path.name}: {e}")
    
    # Step 4: Begin serving requests
    return kernel
```

---

## 15. MIGRATION GUIDE: Current → Target Architecture

### 15.1 Components to Move

| Current Location | Target Location | Reason | Timeline |
|------------------|-----------------|--------|----------|
| `agent_control` | core/modules/agent/ | System-critical, boot-time required | Immediate |
| `client_manager` | core/modules/agent/ | Part of agent lifecycle | Immediate |
| `risk_extensions` | plugins/risk_extensions/ | User-customizable, deployable separately | Week 2 |
| `rotation_strategies` | plugins/custom_rotation/ | User-defined, can be replaced | Week 2 |
| `audit_reporters` | plugins/audit_reporters/ | Optional integrations (Splunk, Datadog) | Week 3 |

### 15.2 API Changes Required

```python
# BEFORE (mixed access)
class RotationExecutor:
    def __init__(self):
        self.vault = get_vault()        # Direct access
        self.db = get_db()              # Direct access
        self.strategies = load_plugins()  # Plugin loading

# AFTER (Module API)
class RotationExecutor(BaseModule):
    def init(self, kernel):
        self.vault = kernel.vault
        self.db = kernel.storage
        self.strategies = StrategyRegistry()  # Registry, not direct plugin load
        kernel.register_handler('rotation.tick', self.rotate)

# AFTER (Plugin API)
class CustomRotationPlugin(BasePlugin):
    def on_install(self, ctx):
        ctx.audit.emit('rotation.custom.installed', {})
        ctx.events.subscribe('rotation.tick', self.custom_rotate)
    
    def custom_rotate(self, event, ctx):
        # Limited to plugin context
        creds = ctx.credentials.list()
        for cred in creds:
            # Rotation logic here (NO vault access)
            pass
```

---

## 16. CHECKLIST: Architecture Enforcement

### 16.1 Code Review Gate

**Before merging code, verify:**
- [ ] Module import guard prevents direct vault access → plugins
- [ ] All Module.init() calls receive KernelContext, not PluginContext
- [ ] All Plugin.on_install() calls receive PluginContext, not KernelContext
- [ ] No Module directly reads other Module private state (declared deps only)
- [ ] No Plugin-to-Plugin imports (dependency dead code)
- [ ] All system operations logged to audit (modules must emit events)
- [ ] Plugin storage namespaced per plugin_id (no cross-plugin key leakage)
- [ ] Background tasks spawned via kernel API, not os.spawn()
- [ ] DBConnections use ctx.storage transaction API, not raw SQL
- [ ] Audit events use approved event types (whitelist checked)

### 16.2 Runtime Validation

```python
def validate_architecture():
    """Run system start-up to catch architecture violations."""
    
    # Verify module dependencies form DAG
    deps = get_module_dependency_graph()
    if has_cycle(deps):
        raise ArchitectureViolation("Circular module dependencies")
    
    # Verify every module reports capabilities used
    for module in SYSTEM_MODULES:
        if not hasattr(module, 'REQUIRED_CAPABILITIES'):
            raise ArchitectureViolation(f"{module} missing capability declaration")
    
    # Verify plugins don't import forbidden modules
    for plugin_dir in PLUGIN_DIRS:
        code = read_plugin_code(plugin_dir)
        forbidden_imports = find_imports(code, FORBIDDEN_MODULES)
        if forbidden_imports:
            raise ArchitectureViolation(
                f"Plugin {plugin_dir} imports forbidden {forbidden_imports}"
            )
    
    print("✅ Architecture validation passed")
```

---

## 17. FINAL RECOMMENDATIONS

### 17.1 MUST DO IMMEDIATELY

1. **Move AgentModule to System**: `agent_control` + `client_manager` → `core/modules/agent/`
   - Reason: System-critical at boot, controls incoming requests
   - Risk if not done: Agent compromise bypasses auth

2. **Create PluginContext Guard**: Prevent plugins from accessing `core.security.vault` etc.
   - Reason: Privilege escalation vector
   - Implementation: Import intercept + AST analysis

3. **Formalize Module API**: KernelContext with documented methods
   - Reason: Avoid API drift, make boundaries explicit
   - Deliverable: Typing stubs + docstrings

### 17.2 SHOULD DO NEXT WEEK

4. **Extract RotationStrategies to Plugin**: Move user-defined rotation to `plugins/custom_rotation/`
   - Reason: Users need customization without modifying core
   - Backward compat: Provide adapter for existing strategies

5. **Extract RiskExtensions to Plugin**: Move fraud/behavioral models to `plugins/risk_extensions/`
   - Reason: Deployable independently, declines gracefully if disabled
   - Backward compat: Default no-op extension if plugin missing

6. **Create Audit Reporter Plugins**: Splunk, Datadog, Syslog connectors
   - Reason: Don't bloat core with integrations
   - Benefit: Users add reporting without recompile

### 17.3 SHOULD DO NEXT MONTH

7. **Formalize Plugin Marketplace**: Install/uninstall/enable/disable UI
   - Reason: Self-service plugin management
   - Include: Version constraints, dependency checking

8. **Add Permission System**: Fine-grained capabilities per plugin
   - Reason: Run untrusted third-party plugins safely
   - Example: Plugin can read creds but not vault secrets

9. **Implement Resource Quotas**: CPU, memory, task limits per plugin
   - Reason: Prevent DoS via runaway plugins
   - Metrics: Dashboard to monitor plugin resource usage

### 17.4 DO NOT DO

❌ **Do not add arbitrary logic to System Modules**
- Rule: If it's not system-critical, it's a plugin

❌ **Do not let Plugins depend on Plugins**
- Rule: Plugins → Modules only (DAG enforcement)

❌ **Do not store state outside audit log for critical operations**
- Rule: All operations must be reversible via audit log replay

❌ **Do not expose Vault/Storage directly to Plugins**
- Rule: Sandbox is the boundary; no exceptions

---

## 18. ARCHITECTURE DECISION RECORD (ADR)

**Title**: Module vs Plugin Boundary Model  
**Status**: ACCEPTED (2026-02-18)  
**Context**: System grew organically; unclear what belongs in core  
**Decision**: Implement three-level architecture (Core → Modules → Plugins)  
**Rationale**:
- Core: Irreducible kernel (vault, storage, audit, scheduler)
- Modules: System completeness (credential, security, operations, audit, agent)
- Plugins: User extensions (rotation strategies, risk models, integrations)

**Consequences**:
- ✅ Clear boundary enforcement at code & runtime
- ✅ Plugins can be removed without system breakage
- ✅ Independent deployment of plugins (no recompile)
- ✅ Improved testability (plugin tests isolated)
- ⚠️ Requires refactoring ~20% of code
- ⚠️ New permission system needed for fine-grained control

**Implementation Timeline**:
- Week 1: Move AgentModule, create guards
- Week 2: Extract rotation strategies, risk extensions
- Week 3: Create audit reporter plugins
- Month 2: Marketplace UI + permission system

---

## APPENDIX A: Component Ownership Matrix

| Component | Owner | Module/Plugin | Mutable | Testable |
|-----------|-------|---------------|---------|----------|
| Vault | Security team | Core | Local | Unit tests |
| CredentialRepository | Ops team | Module | Shared | Integration tests |
| RiskEngine | ML team | Module | Shared | Integration tests |
| CustomRotationPlugin | Users | Plugin | User-controlled | Plugin SDK tests |
| AuditLog | Compliance team | Core | System-only | Audit tests |
| AgentControl | Platform team | Module | Shared | Contract tests |
| WebhookReporter | Users | Plugin | User-controlled | Plugin SDK tests |

---

## APPENDIX B: Quick Reference

**"Is this a Module or Plugin?"**

| Question | Answer |
|----------|--------|
| System boots without it? | Plugin |
| System boots with it? | Module |
| Users need to customize it? | Plugin |
| Every deployment identical? | Module |
| Can be uninstalled safely? | Plugin |
| Uninstall breaks system? | Module |
| Needs vault access? | Module (probably) |
| Reads creds only? | Plugin |
| Updates core state (epoch)? | Module |
| Updates own state? | Plugin |

---

**End of Architecture Analysis Document**

Generated: 2026-02-18  
Status: DEFINITIVE — Foundation for Step 20+  
Next: Implement migration plan (Week 1 priorities)
