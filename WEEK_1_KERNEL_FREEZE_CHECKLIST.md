# WEEK 1 ACTION PLAN: Kernel Architecture Freeze

**Date**: 2026-02-18  
**Duration**: Week 1 (5 working days)  
**Goal**: Reorganize core/ into kernel/modules/sdk structure; deliver FROZEN architecture

---

## DAY 1 (MONDAY): DEEP ANALYSIS

### Task 1.1: Finalize plugin_manager.py Split Decision

**Action**: Read and annotate plugin_manager.py

```bash
# Read entire file with annotations
cd core-runtime-service
cat -n core/plugin_manager.py | less -S
# Mark lines by responsibility:
# 52-100: Isolation setup (SANDBOX)
# 64-175: load_plugin() orchestration (LIFECYCLE)
# 176-214: start_plugin() (LIFECYCLE)
# ... etc
```

**Deliverable**: Text file `PLUGIN_MANAGER_SPLIT_MAP.txt` with line ranges for each responsibility

### Task 1.2: Finalize operations.py Split Decision

**Action**: Read and annotate operations.py

```bash
cat -n core/operations.py | less -S
# Mark lines by responsibility
```

**Deliverable**: Text file `OPERATIONS_SPLIT_MAP.txt` with line ranges for each responsibility

### Task 1.3: Verify Dependency Graph

**Action**: Check imports between plugin_manager and operations

```bash
cd core-runtime-service
grep -n "^from\|^import" core/plugin_manager.py | head -30
grep -n "^from\|^import" core/operations.py | head -30
```

**Deliverable**: List of external dependencies for each fat object

---

## DAY 2 (TUESDAY): KERNEL DIRECTORY STRUCTURE

### Task 2.1: Create Physical Directories

```bash
cd core-runtime-service

# Create kernel/ subdirectory
mkdir -p core/kernel
touch core/kernel/__init__.py

# Create modules/ subdirectories
mkdir -p core/modules/{credentials,security,operations,audit,agent,marketplace}
for dir in core/modules/*/; do touch "$dir/__init__.py"; done

# Create sdk/ subdirectory
mkdir -p core/sdk
touch core/sdk/__init__.py

# List structure
tree core -L 2 -I '__pycache__'
```

**Deliverable**: Physical directory structure created and verified

### Task 2.2: Extract KERNEL COMPONENTS (non-fat)

**Action**: Move files that are obviously kernel-level

```bash
cd core-runtime-service

# Move to kernel/ (these are safe, no changes needed)
mv core/vault.py core/kernel/ 2>/dev/null || echo "vault.py not found"
# (repeat for other clearly-kernel files once identified)

# Create core/kernel/__init__.py with exports
cat > core/kernel/__init__.py << 'EOF'
"""
KERNEL: Irreducible core system

Contains:
  - Vault (master secrets management)
  - Storage (durability + transactions)
  - Audit (immutable event log)
  - Epoch (versioning)
  - Scheduler (task management)
  - EventBus (internal messaging)
  - Loader (module + plugin lifecycle)
  - CapabilitySystem (permission enforcement)
"""

# Exports will be added after refactoring
EOF
```

**Deliverable**: core/kernel/__init__.py created with documentation

---

## DAY 3 (WEDNESDAY): PLUGIN_MANAGER EXTRACTION

### Task 3.1: Create kernel/plugin_loader.py

**Action**: Extract discovery + manifest loading

```python
# Based on PLUGIN_MANAGER_SPLIT_MAP from Day 1
# Extract lines X-Y from core/plugin_manager.py
# Create new file core/kernel/plugin_loader.py
```

**Steps**:
1. Create core/kernel/plugin_loader.py
2. Copy PluginManifestLoader class (from plugin_manager.py)
3. Copy topological_sort() method
4. Add imports-
5. Write unit tests in tests/test_plugin_loader.py
6. Run: `pytest tests/test_plugin_loader.py -v`

**Deliverable**: core/kernel/plugin_loader.py (250 LOC) tested

### Task 3.2: Create kernel/plugin_registry.py

**Action**: Extract query + state tracking

```python
# Extract:
#   - _plugins dict
#   - _states dict
#   - _block_reasons dict
#   - get_plugin()
#   - get_plugin_state()
#   - list_plugins()
#   - get_plugin_block_reason()
```

**Deliverable**: core/kernel/plugin_registry.py (150 LOC) tested

---

## DAY 4 (THURSDAY): PLUGIN_MANAGER REFACTORING

### Task 4.1: Create kernel/plugin_sandbox.py

**Action**: Extract isolation logic

**Deliverable**: core/kernel/plugin_sandbox.py (200 LOC) tested

### Task 4.2: Create kernel/plugin_lifecycle.py

**Action**: Extract lifecycle orchestration

**Deliverable**: core/kernel/plugin_lifecycle.py (200 LOC) tested

### Task 4.3: Refactor core/plugin_manager.py

**Action**: Convert to thin facade

```python
# core/plugin_manager.py (SIMPLIFIED)

from core.kernel.plugin_registry import PluginRegistry
from core.kernel.plugin_lifecycle import PluginLifecycleManager
# ... other imports

class PluginManager:
    """Thin facade for plugin management"""
    
    def __init__(self, runtime):
        self._registry = PluginRegistry()
        self._lifecycle = PluginLifecycleManager(self._registry, ...)
    
    # Delegate all methods to components
```

**Verification**:
```bash
cd core-runtime-service
pytest tests/test_plugin_manager.py -v
# Should all pass (backward compatible)
```

**Deliverable**: plugin_manager.py refactored (< 200 LOC), tests passing

---

## DAY 5 (FRIDAY): STORAGE CONSOLIDATION + KERNEL EXPORTS

### Task 5.1: Consolidate Storage Files

**Action**: Merge 3-4 storage-related files

```bash
cd core-runtime-service

# Analyze what's in each:
wc -l core/secure_storage.py core/storage_manager.py core/storage_startup.py

# Read to understand duplication
grep -n "^class\|^async def\|^def" core/secure_storage.py | head -20
grep -n "^class\|^async def\|^def" core/storage_manager.py | head -20
```

**Create** core/kernel/storage.py by merging:
1. Identify unique classes/functions in each
2. Create single kernel/storage.py with all
3. Delete duplicates

**Deliverable**: core/kernel/storage.py (800+ LOC), old files deleted

### Task 5.2: Create core/kernel/__init__.py Final Exports

```python
# core/kernel/__init__.py

from core.kernel.vault import VaultManager
from core.kernel.storage import StorageManager, TransactionManager
from core.kernel.audit import AuditLogger
from core.kernel.epoch import EpochManager
from core.kernel.scheduler import Scheduler
from core.kernel.event_bus import EventBus
from core.kernel.plugin_loader import PluginManifestLoader
from core.kernel.plugin_registry import PluginRegistry
from core.kernel.plugin_lifecycle import PluginLifecycleManager
from core.kernel.plugin_sandbox import PluginSandbox
from core.kernel.capability_model import Capability, CapabilitySet
from core.kernel.capability_enforcer import CapabilityEnforcer

__all__ = [
    'VaultManager',
    'StorageManager',
    'AuditLogger',
    'EpochManager',
    'Scheduler',
    'EventBus',
    'PluginManifestLoader',
    'PluginRegistry',
    'PluginLifecycleManager',
    'PluginSandbox',
    'Capability',
    'CapabilitySet',
    'CapabilityEnforcer',
]
```

**Deliverable**: core/kernel/__init__.py with clean exports

### Task 5.3: Update core/__init__.py

```python
# core/__init__.py — point to new locations

from core.kernel import *  # Re-export kernel components
from core.modules import *  # (once modules are created)
```

---

## VALIDATION AT END OF WEEK 1

### Checkpoint 1: Directory Structure

```bash
tree core/kernel -L 1
# Should show:
#   ├── __init__.py
#   ├── vault.py
#   ├── storage.py
#   ├── audit.py
#   ├── epoch.py
#   ├── scheduler.py
#   ├── event_bus.py
#   ├── plugin_loader.py
#   ├── plugin_registry.py
#   ├── plugin_lifecycle.py
#   ├── plugin_sandbox.py
#   ├── capability_model.py
#   ├── capability_enforcer.py
#   └── plugin_manifest.py

# Files should all be < 300 LOC
find core/kernel -name '*.py' -exec wc -l {} + | sort -rn | head -5
# Expected: all < 300
```

### Checkpoint 2: Test Suite

```bash
cd core-runtime-service

# Run all tests
pytest tests/ -v --tb=short 2>&1 | tail -20

# Expected: ✅ All tests passing
```

### Checkpoint 3: Import Validation

```bash
cd core-runtime-service

# Verify no circular imports
python3 -c "
import sys
sys.path.insert(0, '.')
import core.kernel
import core.plugin_manager
import core.operations
print('✅ Import structure clean')
" 2>&1

# Expected: ✅ Import structure clean
```

### Checkpoint 4: Fat Object Removal

```bash
# Check that old files are no longer fat
wc -l core/*.py | sort -rn | head -10

# Expected: no file > 500 LOC (except runtime.py which we'll handle Week 2)
```

---

## COMMIT STRATEGY

At end of each day (or logical unit), commit:

```bash
git add core/kernel/ core/__init__.py tests/test_*
git commit -m "refactor(kernel): extract plugin_loader.py from plugin_manager.py"

# Day-end summary
git log --oneline -5
```

---

## DELIVERABLES BY END OF WEEK 1

| Day | Task | Deliverable | Status |
|-----|------|-------------|--------|
| Mon | Analysis | PLUGIN_MANAGER_SPLIT_MAP.txt + OPERATIONS_SPLIT_MAP.txt | TODO |
| Tue | Structure | core/kernel/ + core/modules/ + core/sdk/ dirs created | TODO |
| Wed | Extract | plugin_loader.py + plugin_registry.py ready, tested | TODO |
| Thu | Facade | plugin_manager.py refactored, tests passing | TODO |
| Fri | Storage | kernel/storage.py consolidated, __init__.py exported | TODO |

---

## CONTINGENCY PLAN

If something goes wrong:

1. **plugin_manager.py split fails?**
   - Revert last commit
   - Re-analyze split points
   - Try different boundaries

2. **Tests fail after refactoring?**
   - Check imports (likely "from core.X import" → should be "from core.kernel.X")
   - Update test imports
   - Re-run

3. **Time pressure?**
   - Prioritize: plugin_manager (most critical) > operations > storage
   - Storage can be left for Week 2 if needed
   - Don't compromise module/__init__.py (must be done)

---

## SUCCESS CRITERIA

At EOW:
- ✅ core/kernel/ exists with 12+ files, each < 300 LOC
- ✅ plugin_manager.py reduced from 852 LOC to < 200 LOC
- ✅ All tests passing
- ✅ No circular imports
- ✅ core/kernel/__init__.py exports all public API
- ✅ Git history clean (logical commits per file)

---

**NEXT**: Week 2 focuses on operations.py split + runtime.py extraction.

Ready to begin Day 1? (Confirm by pushing this checklist to repo)
