P0 STORAGE HARDENING - ARCHITECTURE DEEP DIVE
==============================================

## System Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                          │
│  (Plugins, Agents, Admin UI)                                   │
│                                                                 │
│  Critical:                    Non-critical:                     │
│  await secure.secure_set()    await secure.set()               │
│  await secure.secure_delete() await secure.get()               │
└────────┬─────────────────────────────────────────────────────┬─┘
         │                                                       │
         │ (Namespace: trust_store, agent_registry, etc.)       │
         │                                                       │
         ▼                                                       ▼
┌────────────────────────────────────┐    ┌──────────────────────┐
│                                    │    │ Validation + Type    │
│  SecureStorageWrapper              │    │ checks (optional)    │
│  (core/secure_storage.py)          │    │                      │
│                                    │    └──────────────────────┘
│  ┌──────────────────────────────┐  │
│  │ Atomic Transaction Manager   │  │
│  │ - BEGIN/COMMIT/ROLLBACK      │  │
│  │ - All or nothing guarantee   │  │
│  └──────────────────────────────┘  │
│         ↓         ↓        ↓        │
│    ┌────────┐ ┌──────┐ ┌────────┬─────────────┐
│    │ Bump   │ │Append│ │Write  │ Recalculate │
│    │ Epoch  │ │Audit │ │Value  │ Merkle Root │
│    │        │ │Log   │ │       │             │
│    └────────┘ └──────┘ └────────┴─────────────┘
│                                    │
└─────────────────────────────────────┤
             ↓                        │
┌─────────────────────────────────────┴─────── ─────────────┐
│                                                           │
│  StorageAdapter Layer                                    │
│  (sqlite_adapter.py / postgresql_adapter.py)             │
│                                                           │
│  ┌─────────────────────────────────────────────────┐     │
│  │ Thread-local / Connection Pool Management       │     │
│  │ - SQLite: thread-local connections              │     │
│  │ - PostgreSQL: asyncpg pool                       │     │
│  └─────────────────────────────────────────────────┘     │
│         ↓                       ↓                         │
│   ┌──────────────────┐    ┌─────────────────┐            │
│   │  PRAGMA Setup    │    │  JSONB Setup    │            │
│   │  (SQLite)        │    │  (PostgreSQL)   │            │
│   │                  │    │                 │            │
│   │ • synchronous=   │    │ • JSONB auto    │            │
│   │   FULL           │    │   validates     │            │
│   │ • journal_mode=  │    │ • Connection    │            │
│   │   WAL            │    │   pooling       │            │
│   │ • cache_size=    │    │ • SSL support   │            │
│   │   64000          │    │                 │            │
│   │ • foreign_keys=  │    │                 │            │
│   │   ON             │    │                 │            │
│   │                  │    │                 │            │
│   └────┬─────────────┘    └────────┬────────┘            │
│        │ Validates on GET/SET       │                    │
│        ▼                            ▼                    │
│   ┌─────────────────────────────────────┐               │
│   │ Error Handling Layer                │               │
│   │                                     │               │
│   │ JSON Parse Error →                │               │
│   │   StorageCorruptionError            │               │
│   │                                     │               │
│   │ Type Mismatch (not dict) →        │               │
│   │   StorageCorruptionError            │               │
│   │                                     │               │
│   │ Invalid Value →                   │               │
│   │   StorageCorruptionError            │               │
│   └──────────────────┬──────────────────┘               │
└──────────────────────┼────────────────────────────────────┘
                       ▼
           ┌───────────────────────────┐
           │  Filesystem / Database    │
           │                           │
           │ ┌─────────────────────┐   │
           │ │ storage table       │   │
           │ │ namespace | key | v │   │
           │ └─────────────────────┘   │
           │         ↓                 │
           │ ┌─────────────────────┐   │
           │ │ WAL journal         │   │
           │ │ (SQLite)            │   │
           │ │ Ensures durability  │   │
           │ └─────────────────────┘   │
           └───────────────────────────┘
```

## Data Flow: Secure Set Operation

```
Application calls:
  await secure_storage.secure_set("trust_store", "key_1", {"level": 100})
         ↓
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
  ATOMIC TRANSACTION BEGINS (all or nothing)
│                                                         │
  ├─ Step 1: Acquire lock
  │  (Prevent concurrent secure_set operations)
  │
  ├─ Step 2: BEGIN TRANSACTION
  │  (Start atomic operation)
  │
  ├─ Step 3: BUMP EPOCH
  │  Old _system.meta.global_epoch = 41
  │        ↓
  │  New _system.meta.global_epoch = 42
  │  Persisted to storage
  │
  ├─ Step 4: APPEND AUDIT LOG
  │  New entry: {
  │    id: 123,
  │    epoch: 42,
  │    namespace: "trust_store",
  │    key: "key_1",
  │    operation: "SET",
  │    hash: SHA256({"level": 100}),
  │    timestamp: "2026-02-17T10:00:00Z",
  │    prev_hash: <previous_entry_hash>,
  │    entry_hash: SHA256(prev_hash + entry_data)
  │  }
  │  Persisted to _system.audit_log.123
  │
  ├─ Step 5: WRITE VALUE
  │  New storage record:
  │  storage[namespace="trust_store", key="key_1"] = {"level": 100}
  │  Persisted to storage table
  │
  ├─ Step 6: RECALCULATE MERKLE ROOT
  │  For each namespace (except _system):
  │    For each key in namespace:
  │      key_hash = SHA256(canonical_json(value))
  │    namespace_root = merkle_tree(sorted(key_hashes))
  │  global_root = merkle_tree(sorted(namespace_roots))
  │  
  │  Result: "a8f4e7c2d9b1..." (new root hash)
  │  
  │  Persisted to _system.root_hash.current
  │
  ├─ Step 7: COMMIT TRANSACTION
  │  All changes persisted atomically
  │
│└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
  
  IF ANY STEP FAILS:
    → ROLLBACK TRANSACTION (everything reverts)
    → Release lock
    → Raise exception

Success:
  Returned to application
  new_value = await secure_storage.get("trust_store", "key_1")
             = {"level": 100}
```

## State Verification on Startup

```
System starts:
  ┌─────────────────────────────────────────────────────┐
  │ StorageInitializer.initialize()                     │
  └─────────────────────────────────────────────────────┘
         ↓
  ┌─────────────────────────────────────────────────────┐
  │ 1. STARTUP CHECKS                                   │
  │                                                     │
  │ ├─ SQLite: Check PRAGMA synchronous=FULL            │
  │ ├─ Filesystem: Check ≥1GB free space                │
  │ ├─ Docker: Check not on overlayfs                   │
  │ ├─ Configuration: Check production safety           │
  │ └─ Result: ✓ OK or ✗ FATAL EXIT                     │
  └─────────────────────────────────────────────────────┘
         ↓
  ┌─────────────────────────────────────────────────────┐
  │ 2. CREATE ADAPTER                                   │
  │                                                     │
  │ ├─ SQLiteAdapter(db_path)                           │
  │ │  └─ apply PRAGMAS on first connection             │
  │ │     • synchronous=FULL                            │
  │ │     • journal_mode=WAL                            │
  │ │     • cache_size=-64000                           │
  │ │     • etc.                                        │
  │ │                                                   │
  │ └─ PostgreSQLAdapter(dsn)                           │
  │    └─ create connection pool                        │
  │       with SSL if production                        │
  └─────────────────────────────────────────────────────┘
         ↓
  ┌─────────────────────────────────────────────────────┐
  │ 3. WRAP WITH SECURE STORAGE                         │
  │                                                     │
  │ SecureStorageWrapper(adapter)                       │
  │   ├─ Load current epoch                             │
  │   │  epoch_record = storage.get("_system.meta",    │
  │   │                              "global_epoch")    │
  │   │  self._current_epoch = epoch_record["epoch"]    │
  │   │                                                 │
  │   └─ Initialize state                              │
  │      (if first run, create epoch=0)                │
  └─────────────────────────────────────────────────────┘
         ↓
  ┌──────────────────────────────────────────────────────┐
  │ 4. VERIFY STORAGE INTEGRITY                         │
  │                                                      │
  │ stored_root = storage.get("_system.root_hash",     │
  │                           "current")                │
  │                                                      │
  │ IF stored_root is NULL:                             │
  │   ├─ First run detected                             │
  │   ├─ Calculate initial merkle root                  │
  │   └─ Save it                                        │
  │                                                      │
  │ ELSE IF stored_root exists:                         │
  │   ├─ Recalculate current merkle root from all data  │
  │   ├─ IF current_root == stored_root["root_hash"]    │
  │   │  → Integrity verified ✓                         │
  │   └─ ELSE                                           │
  │      → StorageCorruptionError (FATAL)               │
  │      → "[SecureStorage] Root hash mismatch!"        │
  │      → Application cannot start                     │
  └──────────────────────────────────────────────────────┘
         ↓
  ┌──────────────────────────────────────────────────────┐
  │ 5. READY TO USE                                     │
  │                                                      │
  │ return secure_storage                               │
  │        ├─ Epoch counter is loaded                   │
  │        ├─ Root hash is verified                     │
  │        ├─ Audit log is intact                       │
  │        └─ All data is authentic                     │
  └──────────────────────────────────────────────────────┘
```

## Attack Scenarios

### Scenario 1: Power Loss During Write

```
BEFORE (without P0 patch):
  Process: Write record A to DB
           → SQLite writes to memory
           → Power fails
  Result: Data lost silently ✗

AFTER (with P0 patch):
  Process: Write record A to DB
           → Adapter has PRAGMA synchronous=FULL
           → Every COMMIT triggers fsync()
           → fsync() blocks until data on disk
           → Power fails
  Result: Data persists ✓
```

### Scenario 2: Attacker Reverts Database

```
BEFORE:
  Day 1: trust_store.key_1 = {level: 1}
         Persisted to disk
  
  Day 10: trust_store.key_1 = {level: 100}
          (promoted user after verification)
  
  Attack: Restore backup from Day 1
          Revert to trust_store.key_1 = {level: 1}
  
  Result: User's permissions reverted silently ✗

AFTER:
  Day 1: trust_store.key_1 = {level: 1}
         _system.meta.epoch = 1
  
  Day 10: trust_store.key_1 = {level: 100}
          _system.meta.epoch = 150
  
  Attack: Restore backup from Day 1
          Revert to _system.meta.epoch = 1
  
  On Startup:
    Load current epoch = 1 (from backup)
    Verify integrity...
    
  System verifies:
    "Wait, last time I saw epoch=150"
    "Something changed this epoch!"
    
  Optional: Add cached_epoch check:
    cached_epoch_in_memory = 150 (from startup config)
    current_epoch_in_db = 1
    IF current_epoch < cached_epoch:
      raise StorageRollbackDetected (FATAL)
  
  Result: Attack detected ✓
```

### Scenario 3: Attacker Modifies JSON Directly

```
BEFORE:
  marketplace.transactions.tx_001 = {
    "amount": 100,
    "recipient": "alice@example.com"
  }
  
  Attack:
    Attacker edits DB file directly:
    marketplace.transactions.tx_001 = {
      "amount": 1000000,  ← Increased by 10000x!
      "recipient": "attacker@evil.com"
    }
  
  Result: Silent fraud ✗

AFTER:
  marketplace.transactions.tx_001 = {
    "amount": 100,
    "recipient": "alice@example.com"
  }
  
  Initial merkle root = merkle_tree(all_values)
  root_hash_1 = "a8f4e7..." (saved to _system.root_hash)
  
  Attack:
    Attacker edits DB file:
    marketplace.transactions.tx_001 = {
      "amount": 1000000,
      "recipient": "attacker@evil.com"
    }
  
  On Startup:
    Recalculate merkle root from all current data
    new root_hash = recalc_merkle_tree(all_values)
                 = "b9g5f8..." (different!)
    
    Stored root_hash_1 = "a8f4e7..."
    
    IF new != stored:
      raise StorageCorruptionError
      "[SecureStorage] Root hash mismatch!"
      Application cannot start
  
  Result: Attack detected before any damage ✓
```

### Scenario 4: Attacker Modifies Audit Log

```
Audit Log Chain:
  Entry 1:
    prev_hash = SHA256("")
    operation: SET key_1
    entry_hash = SHA256(prev_hash + entry_1_data)
             = "hash_1"
  
  Entry 2:
    prev_hash = "hash_1"  ← Links to Entry 1
    operation: SET key_2
    entry_hash = SHA256(prev_hash + entry_2_data)
             = "hash_2"
  
  Entry 3:
    prev_hash = "hash_2"  ← Links to Entry 2
    operation: SET key_3
    entry_hash = SHA256(prev_hash + entry_3_data)
             = "hash_3"

Attack:
  Attacker modifies Entry 2:
    prev_hash = "XXXXXXX"  ← Forges link
    operation: DELETE key_1  ← Erases evidence
    entry_hash = ???
  
Verification on Startup:
  Verify Entry 1:
    calculated entry_hash = SHA256(SHA256("") + entry_1_data)
    stored entry_hash = "hash_1"
    ✓ Match
  
  Verify Entry 2:
    expected prev_hash = Entry 1's entry_hash = "hash_1"
    actual prev_hash = "XXXXXXX"
    ✗ MISMATCH
    
  Audit log chain broken → Corruption detected ✓
```

## Merkle Tree Example

```
Consider 4 values in trust_store:
  key_a: {value: 1}  → hash: aa11
  key_b: {value: 2}  → hash: bb22
  key_c: {value: 3}  → hash: cc33
  key_d: {value: 4}  → hash: dd44

Merkle Tree Construction:
  
  Layer 0 (leaf hashes):
    aa11    bb22    cc33    dd44
  
  Layer 1 (pair hashes):
    hash(aa11+bb22)   hash(cc33+dd44)
    = aabb             = ccdd
  
  Layer 2 (root):
    hash(aabb+ccdd)
    = root_hash
    = abcd

This root_hash represents all 4 values.

If attacker changes key_b's value:
  Original hash: bb22
  New hash: bb99
  
  New merkle root would be:
    hash(aa11+bb99)   hash(cc33+dd44)
    = aaff             = ccdd
    
    hash(aaff+ccdd)
    = xyzw (different!)

So any change propagates to root_hash.
```

## Type Safety: StorageCorruptionError

```python
# BAD (old behavior):
try:
    value = await storage.get("trust", "key")
except Exception:
    pass
# Silently returns None, corruption hidden

# GOOD (new behavior):
try:
    value = await storage.get("trust", "key")
except StorageCorruptionError as e:
    # Corruption detected explicitly
    log.error(f"Storage corruption: {e}")
    sys.exit(1)  # Fail fast
```

This pattern ensures corruption is **never silent**.

## Concurrency Guarantees

```
Multiple Tasks / Threads:

Task A: secure_set("trust_store", "key_a", ...)
Task B: secure_set("trust_store", "key_b", ...)
Task C: get("trust_store", "key_a")

Timeline:
  T0: Task A acquires lock
  T1: Task A does full atomic operation
  T2: (Task B blocked on lock)
  T3: Task A releases lock
  T4: Task B acquires lock
  T5: Task B does full atomic operation
  T6: (Task C reads freely, gets consistent view)
  T7: Task B releases lock

Result:
  - Epoch monotonically increases: 1 → 2 → 3
  - Merkle root reflects all changes
  - Audit log is contiguous
  - No partial states
```

---

This architecture ensures that **the security invariants are impossible to violate**
through normal operations, and violations are immediately and obviously detected.
