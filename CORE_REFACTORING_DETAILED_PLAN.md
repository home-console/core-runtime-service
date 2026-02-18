# DETAILED REFACTORING PLAN: Fat Objects Analysis + Decomposition

**Date**: 2026-02-18  
**Phase**: Core Architecture Audit - Implementation Details

---

## 1. PLUGIN_MANAGER.PY → Split into 5 Files

### 1.1 Current State Analysis

**File**: core/plugin_manager.py (852 LOC)

**Classes**:
- PluginState (enum) — SHARED
- PluginManager (main fat object)

**Methods in PluginManager** (14 total):
```
Responsibility 1: LOADER/DISCOVERY
  - _load_plugin_manifest()
  - _topological_sort_manifests()

Responsibility 2: LIFECYCLE MANAGEMENT
  - __init__()
  - load_plugin()
  - start_plugin()
  - stop_plugin()
  - unload_plugin()
  - reload_plugin()
  - start_all() / stop_all()

Responsibility 3: QUERY / STATE TRACKING
  - get_plugin()
  - get_plugin_state()
  - list_plugins()
  - get_plugin_block_reason()

Responsibility 4: ISOLATION / SANDBOX (mixed in load_plugin)
  - StorageProxy creation
  - ServiceProxy creation
  - Permission checking
```

### 1.2 Split Strategy

```
core/plugin_manager.py (852 LOC)
    ↓
    ├─ kernel/plugin_loader.py (250 LOC)
    │   - _load_plugin_manifest() → load_plugin_manifest()
    │   - _topological_sort_manifests() → topological_sort()
    │   - Manifest parsing + validation
    │   - Dependency resolution
    │
    ├─ kernel/plugin_lifecycle.py (200 LOC)
    │   - load_plugin() — orchstration + state transitions
    │   - start_plugin()
    │   - stop_plugin()
    │   - unload_plugin()
    │   - reload_plugin()
    │   - start_all() / stop_all()
    │
    ├─ kernel/plugin_registry.py (150 LOC)
    │   - get_plugin()
    │   - get_plugin_state()
    │   - list_plugins()
    │   - get_plugin_block_reason()
    │   - Holds _plugins, _states, _block_reasons dicts
    │
    ├─ kernel/plugin_sandbox.py (200 LOC)
    │   - StorageProxy (moved from load_plugin inline)
    │   - ServiceProxy (moved from load_plugin inline)
    │   - _create_isolation_context()
    │   - _verify_capabilities()
    │
    └─ kernel/plugin_manifest.py (100 LOC)
        - PluginMetadata dataclass
        - PluginManifest parsing
        - Validation rules
```

### 1.3 Migration Steps

**Step 1**: Create kernel/plugin_loader.py
```python
# kernel/plugin_loader.py

class PluginManifestLoader:
    @staticmethod
    def load_manifest(plugin_path: Path) -> Dict[str, Any]:
        """Load plugin.json or manifest.json"""
        # Extract from line 440-500 of plugin_manager.py
        pass
    
    @staticmethod
    def topological_sort(manifests: Dict[str, Dict]) -> List[str]:
        """Sort plugins by dependencies"""
        # Extract from line 614+ of plugin_manager.py
        pass
```

**Step 2**: Create kernel/plugin_registry.py
```python
# kernel/plugin_registry.py

class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}
        self._states: Dict[str, PluginState] = {}
        self._block_reasons: Dict[str, Dict] = {}
        self._plugin_lock = threading.Lock()
    
    def register(self, name: str, plugin: BasePlugin, state: PluginState) -> None:
        with self._plugin_lock:
            self._plugins[name] = plugin
            self._states[name] = state
    
    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        # Extract lines 374-385
        pass
    
    def get_state(self, name: str) -> Optional[PluginState]:
        # Extract lines 386-397
        pass
    
    def list_all(self) -> List[str]:
        # Extract lines 408-417
        pass
```

**Step 3**: Create kernel/plugin_sandbox.py
```python
# kernel/plugin_sandbox.py

from core.plugin_isolation import StorageProxy, ServiceProxy

class PluginSandbox:
    @staticmethod
    def create_isolation_context(
        plugin: BasePlugin,
        runtime: CoreRuntime,
        namespace: str
    ) -> Dict[str, Any]:
        """Create isolated context for plugin"""
        # Extract from load_plugin lines 85-125
        storage_proxy = StorageProxy(runtime.storage, namespace=namespace)
        service_proxy = ServiceProxy(runtime, plugin_name=namespace)
        
        return {
            'storage': storage_proxy,
            'services': service_proxy,
            'vault': None,  # plugins don't get vault
            'audit': AuditProxy(runtime.audit, namespace=namespace)
        }
    
    @staticmethod
    def verify_capabilities(plugin: BasePlugin, runtime: CoreRuntime) -> bool:
        """Check if plugin has required capabilities"""
        # Extract capability checking logic
        pass
```

**Step 4**: Create kernel/plugin_lifecycle.py
```python
# kernel/plugin_lifecycle.py

class PluginLifecycleManager:
    def __init__(self, registry: PluginRegistry, sandbox: PluginSandbox, loader: PluginManifestLoader):
        self.registry = registry
        self.sandbox = sandbox
        self.loader = loader
    
    async def load_plugin(self, plugin: BasePlugin, runtime: CoreRuntime) -> None:
        """Load plugin (orchestration + state transitions)"""
        # Extract lines 64-175
        pass
    
    async def start_plugin(self, plugin_name: str) -> None:
        # Extract lines 176-214
        pass
    
    async def stop_plugin(self, plugin_name: str) -> None:
        # Extract lines 215-242
        pass
```

**Step 5**: Refactor core/plugin_manager.py
```python
# core/plugin_manager.py (SIMPLIFIED)

from kernel.plugin_registry import PluginRegistry
from kernel.plugin_lifecycle import PluginLifecycleManager
from kernel.plugin_loader import PluginManifestLoader
from kernel.plugin_sandbox import PluginSandbox

class PluginManager:
    """Facade for plugin management (thin wrapper)"""
    
    def __init__(self, runtime: CoreRuntime):
        self._runtime = runtime
        self._registry = PluginRegistry()
        self._sandbox = PluginSandbox()
        self._loader = PluginManifestLoader()
        self._lifecycle = PluginLifecycleManager(self._registry, self._sandbox, self._loader)
    
    # Delegate to components
    async def load_plugin(self, plugin: BasePlugin) -> None:
        await self._lifecycle.load_plugin(plugin, self._runtime)
    
    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._registry.get_plugin(name)
    
    # ... etc
```

---

## 2. OPERATIONS.PY → Split into 4 Files

### 2.1 Current State Analysis

**File**: core/operations.py (677 LOC)

**Classes** (6 total):
- OperationStatus (enum)
- OperationInitiatorKind (enum)
- OperationError (model)
- OperationInitiator (model)
- Operation (model + some logic)
- OperationManager (fat object)

**OperationManager Methods**:
```
Responsibility 1: HANDLER REGISTRATION
  - register_handler()
  - unregister_handler()
  - list_handler_types()
  - _find_handler()

Responsibility 2: EXECUTION / ROUTING
  - execute_operation()
  - _execute_handler()
  - Various error/retry logic

Responsibility 3: STORAGE / PERSISTENCE
  - store_operation()
  - get_operation()
  - list_operations()

Responsibility 4: AUDIT INTEGRATION
  - Audit logging in execute_operation
```

### 2.2 Split Strategy

```
core/operations.py (677 LOC)
    ↓
    ├─ modules/operations/models.py (100 LOC)
    │   - OperationStatus (enum)
    │   - OperationInitiatorKind (enum)
    │   - OperationError
    │   - OperationInitiator
    │   - Operation (dataclass only, no logic)
    │
    ├─ modules/operations/registry.py (150 LOC)
    │   - register_handler()
    │   - unregister_handler()
    │   - list_handler_types()
    │   - get_handler()
    │   - Holds _handlers dict
    │
    ├─ modules/operations/executor.py (250 LOC)
    │   - execute_operation() — main orchestration
    │   - _execute_handler()
    │   - _execute_with_retry()
    │   - Error handling + retries
    │   - Health monitoring integration
    │   - Uses registry to find handler
    │
    ├─ modules/operations/storage.py (100 LOC)
    │   - store_operation()
    │   - get_operation()
    │   - list_operations()
    │   - Queries against storage
    │
    └─ modules/operations/audit_integration.py (100 LOC)
        - emit_audit_event()
        - operation_to_audit_entry()
        - Coordinates with audit module
```

### 2.3 Migration Steps

**Step 1**: Create modules/operations/models.py
```python
# modules/operations/models.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

class OperationStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"

class OperationInitiatorKind(Enum):
    AGENT = "agent"
    ADMIN = "admin"
    SYSTEM = "system"

@dataclass
class OperationError:
    code: str
    message: str
    retryable: bool

@dataclass
class OperationInitiator:
    kind: OperationInitiatorKind
    name: str

@dataclass
class Operation:
    id: str
    type: str
    initiator: OperationInitiator
    status: OperationStatus
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[OperationError] = None
    timestamp: str = None
```

**Step 2**: Create modules/operations/registry.py
```python
# modules/operations/registry.py

class OperationHandlerRegistry:
    def __init__(self):
        self._handlers = {}
        self._lock = threading.RLock()
    
    def register(self, op_type: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[op_type] = handler
    
    def get_handler(self, op_type: str) -> Optional[Callable]:
        with self._lock:
            return self._handlers.get(op_type)
    
    def list_types(self) -> List[str]:
        with self._lock:
            return list(self._handlers.keys())
```

**Step 3**: Create modules/operations/executor.py
```python
# modules/operations/executor.py

class OperationExecutor:
    def __init__(self, registry: OperationHandlerRegistry, audit: AuditModule, runtime: CoreRuntime):
        self.registry = registry
        self.audit = audit
        self.runtime = runtime
        self._retryable_errors = {"timeout", "transient", "network", ...}
        self._health_monitor = ProviderHealthMonitor()
    
    async def execute(self, operation: Operation) -> Dict[str, Any]:
        """Execute operation with retry logic, health monitoring, etc."""
        # Extract from lines 250-350
        pass
    
    async def _execute_with_retry(self, operation: Operation, handler: Callable) -> Dict[str, Any]:
        """Retry logic"""
        # Extract retry code
        pass
```

**Step 4**: Create modules/operations/storage.py
```python
# modules/operations/storage.py

class OperationStorage:
    def __init__(self, runtime: CoreRuntime):
        self.runtime = runtime
    
    async def store(self, operation: Operation) -> None:
        """Persist operation to storage"""
        pass
    
    async def get(self, operation_id: str) -> Optional[Operation]:
        """Retrieve operation from storage"""
        pass
    
    async def list(self, filters: Dict) -> List[Operation]:
        """Query operations"""
        pass
```

**Step 5**: Refactor core/operations.py
```python
# core/operations.py (SIMPLIFIED)

from modules.operations.models import Operation, OperationStatus, ...
from modules.operations.registry import OperationHandlerRegistry
from modules.operations.executor import OperationExecutor
from modules.operations.storage import OperationStorage

class OperationManager:
    """Facade (thin wrapper)"""
    
    def __init__(self, runtime: CoreRuntime):
        self.registry = OperationHandlerRegistry()
        self.executor = OperationExecutor(self.registry, runtime.audit, runtime)
        self.storage = OperationStorage(runtime)
    
    async def execute_operation(self, operation: Operation) -> Dict[str, Any]:
        return await self.executor.execute(operation)
    
    def register_handler(self, op_type: str, handler: Callable) -> None:
        self.registry.register(op_type, handler)
    
    # ... delegation methods
```

---

## 3. RUNTIME.PY → Extract Kernel Primitives

### 3.1 Current State Analysis

**File**: core/runtime.py (531 LOC)

**Suspected responsibilities** (need to verify):
```
Responsibility 1: MAIN LOOP
  - Main event loop orchestration
  - Request handling

Responsibility 2: KERNEL INITIALIZATION
  - Vault init
  - Storage init
  - Audit init
  - Module loading

Responsibility 3: STATE MANAGEMENT
  - Epoch manager
  - Scheduler
  - System state

Responsibility 4: MODULE MANAGER
  - Direct module loading
  - Module state tracking
```

### 3.2 Extraction Targets

```
core/runtime.py (531 LOC) splits:
  ├─ kernel/epoch_manager.py (100 LOC) ← Extract EpochManager
  ├─ kernel/scheduler.py (150 LOC) ← Extract Scheduler
  ├─ core/runtime.py (281 LOC) ← Keep only main loop + bootstrap
```

**New core/runtime.py (SIMPLIFIED)**:
```python
class CoreRuntime:
    def __init__(self):
        # Kernel components
        self.vault = VaultManager()
        self.storage = StorageManager()
        self.audit = AuditLogger()
        self.epoch = EpochManager(self.storage)
        self.scheduler = Scheduler()
        self.event_bus = EventBus()
        
        # Module loader
        self.module_loader = ModuleLoader(self)
        self.plugin_manager = PluginManager(self)
        
        # Modules (loaded in init)
        self.modules = {}
    
    async def bootstrap(self):
        """Load system modules"""
        await self.module_loader.load_all_system_modules()
```

---

## 4. SECURE_STORAGE.PY + STORAGE_MANAGER.PY → Consolidate

### 4.1 Current Duplication

**Files**:
- core/secure_storage.py (479 LOC)
- core/storage_manager.py (269 LOC)
- core/storage_startup.py (269 LOC)
- core/storage_migrate.py (?) LOC

These likely have significant overlap.

### 4.2 Consolidation Plan

```
core/secure_storage.py (479 LOC)
core/storage_manager.py (269 LOC)
core/storage_startup.py (269 LOC)
core/storage_migrate.py (? LOC)
    ↓
kernel/storage.py (800 LOC total, organized by concern):
  ├─ StorageManager class
  ├─ TransactionManager
  ├─ MigrationManager
  ├─ StartupManager
  ├─ SecureStorage wrapper
```

**Action**:
1. Read secure_storage.py and storage_manager.py side-by-side
2. Identify unique functionality in each
3. Consolidate into kernel/storage.py
4. Delete duplicates

---

## 5. CAPABILITY_REGISTRY.PY → Split into 3 Files

### 5.1 Current State Analysis

**File**: core/capability_registry.py (442 LOC)

**Suspected responsibilities**:
```
Responsibility 1: CAPABILITY DEFINITIONS
  - List of capabilities
  - Metadata about each

Responsibility 2: GRANTS / TRACKING
  - Who has which capabilities
  - Grant storage

Responsibility 3: ENFORCEMENT / CHECKING
  - check_capability()
  - require_capability()
```

### 5.2 Split Strategy

```
core/capability_registry.py (442 LOC)
    ↓
    ├─ kernel/capability_model.py (120 LOC)
    │   - Capability class (name, scope, requirements)
    │   - CapabilitySet
    │   - STANDARD_CAPABILITIES list
    │
    ├─ kernel/capability_grants.py (120 LOC)
    │   - CapabilityGrants class (storage + query)
    │   - grant_capability()
    │   - revoke_capability()
    │   - list_grants()
    │
    └─ kernel/capability_enforcer.py (150 LOC)
        - check_capability()
        - require_capability()
        - enforce()
        - Usage: capability_enforcer.require('vault.read')
```

---

## 6. ACTION PLAN: Timeline

### Week 1: CRITICAL

- [ ] **Monday**: Analyze plugin_manager.py in detail (read all 852 lines)
  - Document each method's responsibility
  - Identify integration points
  - Draft dependency graph
  
- [ ] **Tuesday**: Create kernel/plugin_loader.py + plugin_registry.py
  - Move manifest loading
  - Move query methods
  - Write tests
  
- [ ] **Wednesday**: Create kernel/plugin_sandbox.py + plugin_lifecycle.py
  - Move sandbox creation
  - Move lifecycle orchestration
  - Write tests
  
- [ ] **Thursday**: Refactor core/plugin_manager.py into facade
  - Update imports in core/__init__.py
  - Test all plugin workflows
  - Verify backward compatibility
  
- [ ] **Friday**: Extract kernel/storage.py
  - Merge secure_storage.py, storage_manager.py, storage_startup.py
  - Test storage layer
  - Delete duplicate files

### Week 2: HIGH

- [ ] Split core/operations.py into 4 files (registry, executor, storage, models)
- [ ] Extract EpochManager + Scheduler from runtime.py
- [ ] Split capability_registry.py into 3 files
- [ ] Create core/modules/*/module.py base classes

### Week 3: VALIDATION

- [ ] Full test suite pass
- [ ] No circular imports
- [ ] Update documentation
- [ ] Create migration guide

---

## 7. VALIDATION AFTER REFACTORING

**Metrics**:
- [ ] All core/*.py files < 350 LOC
- [ ] No fat objects remain
- [ ] kernel/ contains only: vault, storage, audit, epoch, scheduler, event_bus, loader, plugin_*, capability_*
- [ ] modules/ organized by domain (credentials, security, operations, audit, agent)
- [ ] All imports within modules use event_bus (no direct calls)
- [ ] Test coverage maintained ≥ 85%
- [ ] No circular dependencies (verify with: `python -m py_compile` or import analysis)

---

## 8. TOOLS FOR VALIDATION

After refactoring, run:

```bash
# Check file sizes
find core -name "*.py" -exec wc -l {} + | sort -rn | head -20

# Check for circular imports
python -c "
import sys
sys.path.insert(0, '.')
import core
print('✅ No circular imports')
"

# Check module isolation
grep -r "from core.security" core/operations/
grep -r "from core.operations" core/security/
# Both should be empty (use event_bus instead)

# Line count tracking
git diff --stat HEAD~1

# Test coverage
pytest --cov=core tests/ --cov-report=term
```

---

**END OF REFACTORING PLAN**

This is the implementation roadmap. Ready to proceed with Phase 1 (Week 1) detailed work.
