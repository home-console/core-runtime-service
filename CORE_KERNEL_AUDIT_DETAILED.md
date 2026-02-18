# CORE KERNEL ARCHITECTURE AUDIT

**Date**: 2026-02-18  
**Status**: AUDIT IN PROGRESS  
**Purpose**: Identify architectural violations before Step 20+

---

## PHASE 1: CURRENT STATE ANALYSIS

### 1.1 Directory Structure Inventory

```
core/
├── 43 files directly in core/ ← 🔴 PROBLEM: Too many top-level files
├── agent/ (N files)
├── audit/ (N files)
├── credentials/ (N files)
├── execution/ (with backends/, runner/)
├── marketplace/
├── observability/
├── remote_services/
├── security/ (10 files + subdirs: mfa/, risk/, trust/)
├── trust/
└── utils/

Total: 108 Python files (NOT organized as kernel/modules/sdk)
```

### 1.2 "Fat Objects" (LOC > 400) - PRIMARY CONCERNS

| File | LOC | Category | Risk | Issue |
|------|-----|----------|------|-------|
| **plugin_manager.py** | 852 | Extensibility | 🔴 CRITICAL | Too much responsibility mixed (discovery, loading, isolation, lifecycle) |
| **operations.py** | 677 | Core | 🔴 CRITICAL | Operations orchestration + policy + execution all mixed |
| **runtime.py** | 531 | Core | 🟠 HIGH | Main runtime loop + module loading + request handling |
| **secure_storage.py** | 479 | Kernel | 🟠 HIGH | Storage + transaction + durability all in one |
| **service_registry.py** | 462 | Core | 🟠 HIGH | Registry + dependency tracking + binding |
| **capability_registry.py** | 442 | Security | 🟠 HIGH | Capabilities + enforcement + checking all mixed |
| **dependency_resolver.py** | 439 | Core | 🟠 HIGH | Dependency graph + resolution + validation |
| **module_manager.py** | 413 | Extensibility | 🟠 HIGH | Module loading + init + lifecycle all mixed |

**Diagnosis**: These 8 files contain ~4,100 LOC of mixed responsibilities. Each should be split 2-3 ways.

---

## PHASE 2: COMPONENT AUDIT MATRIX

Каждый компонент оценивается по критериям:

| Компонент | Makes Auth Decision? | Stores Security State? | Can Be Disabled? | Kernel / Module / Plugin | Current Location | Issue |
|-----------|---------------------|------------------------|------------------|---------------------------|------------------|-------|
| **vault_manager** | ✅ (unlock gate) | ✅ (master secrets) | ❌ NO | KERNEL | core/security/ | 🟢 Correct |
| **storage_manager** | ❌ | ✅ (auth data) | ❌ NO | KERNEL | core/ | 🟢 Correct |
| **audit_log** | ❌ | ✅ (immutable) | ❌ NO | KERNEL | core/audit/ | 🟢 Correct |
| **epoch_manager** | ❌ | ✅ (versioning) | ❌ NO | KERNEL | core/ | 🟠 Buried in runtime.py |
| **scheduler** | ❌ | ⚠️ (task queue) | ❌ NO | KERNEL | core/ | 🟠 Implicit, not extracted |
| **loader** | ✅ (permission check) | ✅ (module registry) | ❌ NO | KERNEL | core/module_manager.py | 🔴 TOO FAT |
| **credential_repo** | ✅ (access policy) | ✅ (metadata) | ✅ YES | MODULE | core/credentials/ | 🟠 Should be module, not core |
| **mfa_service** | ✅ (elevation gate) | ✅ (state) | ❌ NO | MODULE | core/security/mfa/ | 🟠 Correct but needs explicit module wrapper |
| **risk_engine** | ✅ (risk score) | ✅ (anomaly state) | ⚠️ (degrades gracefully) | MODULE | core/security/risk/ | 🟠 Should make this explicit |
| **trust_engine** | ✅ (trust decision) | ✅ (trust state) | ❌ NO | MODULE | core/security/trust/ | 🟠 Correct but embedded |
| **rotation_executor** | ✅ (what to rotate) | ✅ (audit trail) | ❌ NO | MODULE | (unknown - buried?) | 🔴 MISSING CLEAR BOUNDARY |
| **rotation_strategies** | ❌ (implements policy) | ❌ (stateless) | ✅ YES | **PLUGIN** | core/ or modules/ | 🔴 WRONG LOCATION |
| **rbac_policy_engine** | ✅ (access decision) | ✅ (policy rules) | ❌ NO | MODULE | core/security/ | 🟠 Correct but scattered |
| **event_bus** | ❌ (dispatcher only) | ⚠️ (temp queue) | ⚠️ (yes) | KERNEL | core/event_bus.py | 🟠 Should be kernel primitives |
| **plugin_manager** | ✅ (isolation) | ✅ (manifest) | ❌ NO | KERNEL | core/plugin_manager.py | 🔴 TOO FAT + WRONG LOC |
| **capability_system** | ✅ (enforce) | ✅ (grants) | ❌ NO | KERNEL | core/capability_registry.py | 🔴 TOO FAT |
| **http_registry** | ❌ | ❌ | ✅ YES | KERNEL (router) | core/http_registry.py | 🟠 Should be thin adapter |
| **remote_executor** | ❌ (executes) | ⚠️ (logs) | ⚠️ (yes) | MODULE | core/remote_executor.py | 🔴 WRONG LEVEL |
| **process_executor** | ❌ (executes) | ⚠️ (logs) | ✅ YES | PLUGIN | core/process_executor.py | 🔴 WRONG LOCATION |
| **marketplace** | ✅ (verify sig) | ✅ (manifest) | ⚠️ (yes) | MODULE | core/marketplace/ | 🟠 Should be system boundary |
| **agent_registry** | ✅ (auth agent) | ✅ (metadata) | ❌ NO | MODULE | core/agent/ | 🟠 Correct but needs explicit |
| **client_manager** | ✅ (connection) | ✅ (tokens) | ❌ NO | MODULE | core/agent/ | 🟠 Correct but needs explicit |

---

## PHASE 3: CROSS-MODULE DEPENDENCY VIOLATIONS

### 3.1 Direct Imports Between Modules (Event-bus Pattern Violations)

**Problem**: Modules import each other directly instead of using event bus.

Examples to check:
```python
# ❌ WRONG (direct import and call)
from core.security.risk.engine import RiskEngine
from core.operations.rotation import RotationExecutor

class OperationModule:
    def execute(self):
        risk_score = RiskEngine.score()  # Direct call!
        if risk_score > threshold:
            RotationExecutor.rotate()    # Direct call!

# ✅ CORRECT (event-driven)
class OperationModule:
    def execute(self):
        self.event_bus.publish('operation.requested', {'op': data})
        # RiskModule listens: event_bus.subscribe('operation.requested', ...)
        # RiskModule emits: event_bus.publish('risk.update', {'score': ...})
        # OperationModule listens: event_bus.subscribe('risk.update', ...)
```

### 3.2 Files to Check for Direct Imports

- `core/operations.py` — likely calls multiple modules directly
- `core/runtime.py` — orchestrator, probably has direct imports
- `core/module_manager.py` — module init phase, might hardcode module dependencies
- `core/service_registry.py` — registry, might auto-wire modules
- Any `core/modules/*/module.py` — should only use events, not direct imports

### 3.3 Suspected Violations (Require Code Review)

```
⚠️ To verify:
  - Does RiskEngine directly import RotationExecutor?
  - Does MFAService directly import CredentialRepo?
  - Does AgentControl directly import RotationScheduler?
  - Does OperationContext orchestrate without event bus?
```

---

## PHASE 4: "FAT OBJECT" DECOMPOSITION PLAN

### 4.1 plugin_manager.py (852 LOC) → Split into 5 Files

**Current mixing (suspected)**:
```python
class PluginManager:
    # Responsibility 1: Discovery
    def discover_plugins(location): ...
    
    # Responsibility 2: Loading (with AST analysis)
    def load_plugin(path): ...
    
    # Responsibility 3: Isolation
    def create_sandbox(code): ...
    
    # Responsibility 4: Lifecycle
    def init_plugin(manifest): ...
    
    # Responsibility 5: Capability checking
    def verify_capabilities(plugin, required): ...
```

**Target split**:
- `kernel/plugin_loader.py` (250 LOC) — discovery + loading orchestration
- `kernel/plugin_sandbox.py` (200 LOC) — isolation + AST analysis
- `kernel/plugin_manifest.py` (150 LOC) — manifest validation
- `kernel/plugin_lifecycle.py` (150 LOC) — init/uninstall hooks
- `kernel/plugin_isolation_enforcer.py` (100 LOC) — capability checking

### 4.2 operations.py (677 LOC) → Split into 4 Files

**Current mixing (suspected)**:
```python
class OperationContext:
    # Responsibility 1: Operation metadata
    def ...
    
    # Responsibility 2: Execution orchestration
    def execute_operation(): ...
    
    # Responsibility 3: Policy checking
    def check_policy(): ...
    
    # Responsibility 4: Audit logging
    def log_operation(): ...
```

**Target split**:
- `modules/operations/operation.py` (100 LOC) — dataclass only
- `modules/operations/executor.py` (250 LOC) — orchestration + state
- `modules/operations/policy.py` (150 LOC) — policy enforcement
- `modules/operations/audit_integration.py` (100 LOC) — audit logging

### 4.3 capability_registry.py (442 LOC) → Split into 3 Files

**Target split**:
- `kernel/capability_model.py` (150 LOC) — definitions
- `kernel/capability_enforcer.py` (200 LOC) — checking + enforcement
- `kernel/capability_grants.py` (100 LOC) — grant storage + query

---

## PHASE 5: MIGRATION TARGET LAYOUT

### 5.1 Recommended restructuring

```
core/
├── kernel/
│   ├── __init__.py
│   ├── vault.py              (VaultManager - from core/security/)
│   ├── storage.py            (from secure_storage.py + storage_manager.py)
│   ├── audit.py              (from core/audit/)
│   ├── epoch.py              (from core/)
│   ├── scheduler.py          (from core/)
│   ├── event_bus.py          (from core/)
│   ├── loader.py             (from module_manager.py) - SPLIT
│   ├── plugin_loader.py      (from plugin_manager.py)
│   ├── plugin_sandbox.py     (from plugin_manager.py)
│   ├── capability_model.py   (from capability_registry.py) - SPLIT
│   ├── capability_enforcer.py(from capability_registry.py) - SPLIT
│   └── errors.py             (core/errors.py)
│
├── modules/
│   ├── __init__.py
│   ├── credentials/
│   │   ├── __init__.py
│   │   ├── module.py         (CredentialModule base class - NEW)
│   │   ├── repository.py     (from core/credentials/)
│   │   ├── domain.py         (from core/credentials/)
│   │   ├── access_control.py (from core/credentials/)
│   │   └── tests.py
│   │
│   ├── security/
│   │   ├── __init__.py
│   │   ├── module.py         (SecurityModule base - NEW)
│   │   ├── mfa/
│   │   │   ├── service.py
│   │   │   └── ...
│   │   ├── risk/
│   │   │   ├── engine.py
│   │   │   └── ...
│   │   ├── trust/
│   │   │   ├── engine.py
│   │   │   └── ...
│   │   ├── policy_engine.py  (from core/security/)
│   │   └── tests.py
│   │
│   ├── operations/
│   │   ├── __init__.py
│   │   ├── module.py         (OperationModule - NEW)
│   │   ├── operation.py      (from operations.py) - SPLIT
│   │   ├── executor.py       (from operations.py) - SPLIT
│   │   ├── rotation/
│   │   │   ├── executor.py   (credential rotation logic)
│   │   │   └── scheduler.py  (from ???)
│   │   ├── policy.py         (from operations.py) - SPLIT
│   │   └── tests.py
│   │
│   ├── audit/
│   │   ├── __init__.py
│   │   ├── module.py         (AuditModule - NEW)
│   │   ├── logger.py         (from core/audit/)
│   │   ├── binder.py         (events→audit binding)
│   │   ├── integration.py    (module integration)
│   │   └── tests.py
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── module.py         (AgentModule - NEW)
│   │   ├── registry.py       (from core/agent/ or new)
│   │   ├── client_manager.py (from core/agent/)
│   │   ├── control.py        (from core/agent/)
│   │   └── tests.py
│   │
│   └── marketplace/
│       ├── __init__.py
│       ├── module.py         (MarketplaceModule - NEW)
│       ├── registry_client.py
│       ├── validator.py
│       └── tests.py
│
├── sdk/
│   ├── __init__.py
│   ├── plugin.py             (BasePlugin)
│   ├── context.py            (PluginContext)
│   ├── credential_api.py     (CredentialAPI for plugins)
│   ├── audit_api.py          (AuditAPI for plugins)
│   ├── storage_api.py        (PluginStorageAPI)
│   ├── errors.py
│   └── typing.py
│
└── config.py                 (stays here)

plugins/                       ← USER PLUGINS
├── rotation_strategies/      (MOVE FROM core/modules/)
├── risk_extensions/
├── audit_reporters/
└── marketplace_integration/

```

### 5.2 Files to Delete / Consolidate

| Current File | Action | Reason |
|--------------|--------|--------|
| core/plugin_manager.py | SPLIT into kernel/*.py | Too fat + mixed concerns |
| core/operations.py | SPLIT into modules/operations/*.py | Too fat + mixed concerns |
| core/runtime.py | REFACTOR (keep thin) | Main loop grew too big |
| core/secure_storage.py | MERGE into kernel/storage.py | Two files do same thing |
| core/service_registry.py | EVALUATE (might be obsolete) | Replaced by event bus + loader? |
| core/dependency_resolver.py | EVALUATE (might be implicit in loader) | Is this still needed? |
| core/execution_router.py | MOVE to kernel/ or modules/agent/ | Where does HTTP routing belong? |
| core/trust/ | MERGE into core/security/trust/ | Duplicate? |
| core/observability/ | MOVE to plugins/ | Not system-critical |

---

## PHASE 6: BOUNDARY VIOLATIONS CHECKLIST

For each file in core/, answer:

| File | Makes Decision? | Stores State? | Can Disable? | Classification | Current LOC | Issue |
|------|-----------------|---------------|-------------|-----------------|------------|-------|
| acl.py | TBD (analyze) | TBD | ? | ? | ? | Need review |
| auth_contextvars.py | TBD | TBD | ? | ? | ? | Need review |
| base_plugin.py | ❌ | ❌ | ✅ | SDK | ? | 🟢 Likely OK |
| capability_protocol.py | ✅ | ❌ | ❌ | KERNEL | ? | 🟠 Check imports |
| capability_registry.py | ✅ | ✅ | ❌ | KERNEL | 442 | 🔴 TOO FAT |
| config.py | ❌ | ❌ | ✅ | Util | ? | 🟢 Likely OK |
| console.py | ❌ | ❌ | ✅ | Util | ? | 🟢 Likely OK |
| container_executor.py | ❌ | ⚠️ | ✅ | MODULE or PLUGIN? | ? | 🟠 Categorize |
| dependency_resolver.py | ❌ | ✅ | ❌ | KERNEL | 439 | 🟠 Check if needed |
| errors.py | ❌ | ❌ | ✅ | SDK | ? | 🟢 OK |
| event_bus.py | ❌ | ⚠️ | ⚠️ | KERNEL | ? | 🟠 Check if needed |
| execution_router.py | ❌ | ✅ | ✅ | MODULE | ? | 🟠 Categorize |
| health_monitor.py | ❌ | ⚠️ | ✅ | KERNEL | ? | 🟠 Check scope |
| http_registry.py | ❌ | ✅ | ✅ | MODULE | 397 | 🟠 Too fat for routing? |
| integration_registry.py | ❌ | ✅ | ⚠️ | KERNEL | ? | 🟠 Check scope |
| logger_helper.py | ❌ | ❌ | ✅ | SDK | ? | 🟢 OK |
| module_manager.py | ✅ | ✅ | ❌ | KERNEL | 413 | 🔴 TOO FAT |
| operation_context.py | ⚠️ | ✅ | ❌ | MODULE | ? | 🟠 Part of operations mix? |
| operations.py | ✅ | ✅ | ❌ | MODULE | 677 | 🔴 TOO FAT |
| plugin_manager.py | ✅ | ✅ | ❌ | KERNEL | 852 | 🔴 **MOST FAT** |
| plugin_isolation.py | ✅ | ✅ | ? | KERNEL | 277 | 🟠 Part of loader? |
| plugin_schema.py | ❌ | ❌ | ✅ | SDK | ? | 🟢 OK |
| process_executor.py | ❌ | ⚠️ | ✅ | PLUGIN | 269 | 🔴 WRONG LOCATION |
| remote_executor.py | ❌ | ⚠️ | ✅ | PLUGIN or MODULE? | 288 | 🔴 CATEGORIZE |
| runtime.py | ✅ | ✅ | ❌ | KERNEL | 531 | 🔴 TOO FAT |
| secure_storage.py | ❌ | ✅ | ❌ | KERNEL | 479 | 🔴 TOO FAT |
| security.py | ✅ | ✅ | ❌ | MODULE | 389 | 🟠 Part of security module? |
| service_registry.py | ❌ | ✅ | ? | KERNEL | 462 | 🟠 Check if needed |
| storage_manager.py | ❌ | ✅ | ❌ | KERNEL | 269 | 🟠 Duplicate of secure_storage? |
| storage_migrate.py | ❌ | ✅ | ✅ | KERNEL | ? | 🟠 Check scope |
| storage_startup.py | ❌ | ✅ | ❌ | KERNEL | 269 | 🟠 Part of storage.py? |

---

## PHASE 7: IMMEDIATE ACTION ITEMS

### 🔴 CRITICAL (Week 1)

1. **Analyze plugin_manager.py (852 LOC)**
   - Read entire file
   - Identify 5 responsibilities
   - Create split plan
   - Extract into kernel/plugin_*.py files

2. **Analyze operations.py (677 LOC)**
   - Identify 4 responsibilities
   - Create split plan
   - Extract into modules/operations/*.py

3. **Check runtime.py (531 LOC) for Epoch + Scheduler**
   - Extract EpochManager → kernel/epoch.py
   - Extract Scheduler → kernel/scheduler.py

4. **Create kernel/ subdirectory structure**
   - Move vault, storage, audit to kernel/
   - Create kernel/__init__.py with exports

### 🟠 HIGH (Week 1-2)

5. **Extract RotationStrategies to plugins/rotation_strategies/**
   - Identify which files in core currently contain them
   - Move to plugins/rotation_strategies/
   - Update imports

6. **Map Module Dependencies**
   - Grep for direct imports between modules
   - Build dependency graph
   - Identify event-bus violations

7. **Create Module Base Classes**
   - Each module needs explicit Module(BaseModule) class
   - Declare REQUIRED_CAPABILITIES
   - Declare lifecycle hooks

### 🟡 MEDIUM (Week 2-3)

8. **Consolidate storage files**
   - storage_manager.py + secure_storage.py + storage_startup.py + storage_migrate.py
   - → Merge into kernel/storage.py
   - Clean up exports

9. **Create plugin SDK**
   - core/sdk/ with BasePlugin, PluginContext, APIs
   - Document for users

10. **Setup new directory structure**
    - mkdir -p core/kernel core/modules/{credentials,security,operations,audit,agent,marketplace}
    - mkdir -p core/sdk
    - mkdir -p plugins/{rotation_strategies,risk_extensions,audit_reporters}

---

## PHASE 8: VALIDATION CHECKLIST

After reorganization:

- [ ] `core/kernel/` contains ONLY: vault, storage, audit, epoch, scheduler, event_bus, loader, plugin_*, capability_*
- [ ] `core/modules/*/module.py` exists and declares REQUIRED_CAPABILITIES
- [ ] No direct imports between modules (all via event_bus)
- [ ] `plugins/rotation_strategies/` exists with strategy implementations
- [ ] plugin_manager.py split into 5+ files, each <300 LOC
- [ ] operations.py split into 4 files, each <200 LOC
- [ ] No "fat objects" remain (all files <300 LOC except documentation)
- [ ] All imports in core/ properly scoped (no circular deps)
- [ ] Tests pass after refactoring
- [ ] Documentation updated to reflect new structure

---

## NEXT STEPS

1. **Read and analyze the top 5 fat objects** (provide specifics here in next doc)
2. **Create detailed refactoring plan per file**
3. **Begin migration** (with safety: git branch, preserve tests)
4. **Validate** with test suite

---

**END OF AUDIT DOCUMENT**

This is foundation analysis. Next phase: detailed code review of each fat object to finalize decomposition strategy.
