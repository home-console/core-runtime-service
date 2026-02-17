# 🔍 ХОЛОДНОЕ ХРАНИЛИЩЕ — ГЛУБОКИЙ АРХИТЕКТУРНЫЙ АУДИТ

**Дата**: 17 февраля 2026  
**Scope**: Storage layer (SQLite, PostgreSQL adapters) + StateEngine + SecretStore + Marketplace Transactions  
**Цель**: Выявить проблемы crash-safety, atomicity, corruption, rollback attacks.

---

## 1️⃣ STORAGE MODEL ARCHITECTURE

### A. Типы Storage Adapter

#### SQLiteAdapter
```python
# adapters/sqlite_adapter.py
- Type: SQLite file-based (or :memory:)
- Schema: namespace | key | value (JSON as TEXT)
- Connection Model: thread-local (check_same_thread=True)
- WAL Mode: ✓ PRAGMA journal_mode=WAL (enabled)
- Transactions: ✓ BEGIN/COMMIT/ROLLBACK
- Fsync: ❌ **CRITICAL DEFAULT: PRAGMA synchronous=OFF** (if not overridden)
- Atomic Write: ⚠️ Implicit (SQLite handles it)
- Batching: ✓ batch_set() exists
- Locking: ✓ Thread-local implicit DB lock + WAL reader-writer lock
```

**KEY ISSUE**: Default SQLite pragmas NOT set in code!

```python
# Current code shows WAL but NO explicit fsync:
self._local.conn.execute("PRAGMA journal_mode=WAL")
# MISSING:
# - PRAGMA synchronous=FULL  (default is OFF)
# - PRAGMA cache_size=-64000  (default -2000)
# - PRAGMA busy_timeout=30000 (exists but timeout=30.0 seconds)
```

#### PostgreSQLAdapter
```python
# adapters/postgresql_adapter.py
- Type: Network PostgreSQL database
- Schema: namespace | key | value (JSONB)
- Connection Model: asyncpg connection pool
- Transactions: ✓ Built-in ACID
- Fsync: ✓ Configurable via synchronous_commit GUC (depends on DB config)
- Atomic Write: ✓ ACID guarantees
- Batching: ✓ executemany()
- Locking: ✓ MVCC + implicit transaction lock
- JSON Validation: ✓ JSONB validates server-side
```

**Advantage**: PostgreSQL handles durability/atomicity at DB level.  
**Disadvantage**: Network latency, requires PostgreSQL service.

---

### B. Write Atomicity Analysis

#### SQLite: Single Writer Pattern

```
┌──────────────────────────────────────────────────────┐
│ Application calls: await adapter.set("ns", "key", {}) │
└──────────────────────────────────────────────────────┘
                          ↓
                   asyncio.to_thread()
                          ↓
┌──────────────────────────────────────────────────────┐
│ _set_sync():                                         │
│ 1. Get thread-local connection                       │
│ 2. INSERT OR REPLACE (single SQL statement)          │
│ 3. If NOT in_transaction: conn.commit()              │
│ 4. Return                                            │
└──────────────────────────────────────────────────────┘
```

**Atomicity Guarantee**:
- ✓ Single SQL statement (INSERT OR REPLACE) is atomic at SQLite level
- ✓ SQLite WAL ensures write-ahead logging
- ❌ **BUT**: commit() without `PRAGMA synchronous=FULL` is **NOT durable**

**Crash Scenarios**:

| Scenario | Current Behavior | Outcome |
|----------|------------------|---------|
| Crash after INSERT, before commit | ✓ SQLite WAL rolls back | Data lost (OK) |
| Crash after commit, before fsync | ❌ Data in memory buffer | **Data lost on power loss** |
| Crash during commit | ❌ Partially written WAL | **Possible corruption on restart** |
| Two threads concurrent SET | ✓ Thread-local conns + implicit DB lock | Safe (but slow) |

---

#### PostgreSQL: Full ACID

```
┌────────────────────────────────────────────────────────┐
│ Application calls: await adapter.set("ns", "key", {}) │
└────────────────────────────────────────────────────────┘
                          ↓
                     Pool connection
                          ↓
┌────────────────────────────────────────────────────────┐
│ asyncpg:                                               │
│ 1. Parse and validate JSONB                            │
│ 2. INSERT...ON CONFLICT DO UPDATE                      │
│ 3. Implicit transaction commit (if autocommit=true)    │
│ 4. fsync (depends on synchronous_commit)               │
│ 5. Return                                              │
└────────────────────────────────────────────────────────┘
```

**Atomicity Guarantee**:
- ✓ ACID transactional semantics
- ✓ JSONB validation at DB level
- ⚠️ Durability depends on PostgreSQL `synchronous_commit` config (defaults to `on`)

**Advantage**: Synchronous by default in PostgreSQL 12+.

---

## 2️⃣ ATOMICITY DEEP DIVE

### A. SecretStore.put() — Critical Path

```python
# Current flow:
async def put(self, key: str, value: bytes) -> None:
    encrypted = encrypt(value, self._dek)  # AES-256-GCM
    await self._storage.set(
        "secrets.store",
        key,
        {
            "nonce": encrypted.nonce.hex(),
            "ciphertext": encrypted.ciphertext.hex(),
            "tag": encrypted.tag.hex(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
        }
    )
```

**Crash Scenarios with SQLite**:

| Point | State | Recovery |
|-------|-------|----------|
| Before encrypt | Secret not written | ✓ OK |
| After encrypt, before Storage.set() | In-memory encrypted data | ✓ OK (lost on crash) |
| During _set_sync() INSERT | WAL has partial data | ✓ WAL rolls back on startup |
| After INSERT, before commit | Data in page buffer | ❌ **Not durable without fsync** |
| After commit (sync=OFF) | Data in OS buffer | ❌ **power loss = data loss** |
| After commit (sync=FULL) | Data in fsync'd DB | ✓ OK |

**Risk Level**: **P0 — CRITICAL**

> **Problem**: Without `PRAGMA synchronous=FULL`, secret keys can be lost on power failure.

---

### B. Marketplace Transaction — State Machine

```python
# Typical transaction flow:
async def create_transaction(self, ...):
    # Step 1: Create transaction record
    await storage.set("marketplace.transactions", tx_id, {
        "state": "created",
        "items": [...],
        "timestamp": now,
    })
    
    # Step 2: Process payment
    payment_result = await process_payment(...)
    
    # Step 3: Update state
    await storage.set("marketplace.transactions", tx_id, {
        "state": "paid",
        "payment_id": payment_result.id,
    })
    
    # Step 4: Install items
    await install_items(...)
    
    # Step 5: Final state
    await storage.set("marketplace.transactions", tx_id, {
        "state": "completed",
    })
```

**Crash Scenarios**:

| Crash Point | State in DB | Problem |
|-------------|-------------|---------|
| After step 1 | `state="created"` | ✓ Retryable on restart |
| Between step 2-3 (payment SUCCESS, before state update) | `state="created"` but payment charged | ❌ **Dangling payment** (user charged but install not started) |
| Between step 3-4 (install FAILED, before state update) | `state="paid"` but install failed | ⚠️ Unclear (retry? abandon?) |
| Between step 4-5 (install complete, before final state) | `state="paid"` but items installed | ⚠️ On restart, may re-install same items |

**Risk Level**: **P0 — CRITICAL**

> **Problem**: No atomic state machine. Individual updates can fail mid-flow.

---

### C. Agent Registry — Heartbeat & Enrollment

```python
# Current architecture:
in-memory: AgentRegistry (with status tracking)
persistent: storage.set("agent.*", agent_id, metadata)

# Heartbeat update:
async def heartbeat(self, agent_id: str):
    # Only updates in-memory registry
    self._agents[agent_id]["last_heartbeat"] = now()
    # But never persists to cold storage!
```

**Problem**:
- ❌ Heartbeats NOT persisted
- ⚠️ On restart, lost all agent status
- ⚠️ Clients unaware of lost agents

**Risk Level**: **P1 — IMPORTANT**

> **Problem**: Heartbeat state only in-memory. Restart = loss of liveness information.

---

## 3️⃣ CORRUPTION ANALYSIS

### A. JSON Corruption Scenarios

#### Scenario 1: File Truncated

```python
# Current validation in get():
try:
    return json.loads(value)
except (json.JSONDecodeError, ValueError, TypeError) as e:
    print(f"[SQLiteAdapter] Error parsing JSON: {e}")
    return None  # Silently returns None
```

**Impact**:
- JSON parsing error → silently return None
- Application sees "key not found" instead of "corrupted"
- No indication that data was lost

**Example**:
```json
// Proper:
{"secret_key": "abc123xyz789", "created_at": "2026-02-17T10:00:00Z"}

// Truncated (crash during write):
{"secret_key": "abc123xyz789", "created_
```

> Silently returning `None` hides corruption.

---

#### Scenario 2: Simultaneous Write from Two Threads (SQLite)

```python
# Thread-local connections should prevent, but WAL mode adds complexity:

Thread A:                    Thread B:
set(ns, k1, v1)            set(ns, k2, v2)
  _set_sync()                 _set_sync()
    INSERT (thread-local)       INSERT (thread-local)
    commit()                      commit()
    [Page A modified]           [Page A modified]
    [WAL lock acquired]         [WAL lock acquired]  ← Contention
```

**Result**:
- ⚠️ WAL reader-writer lock serializes writes
- ✓ If both writes to SAME key: Row-level lock prevents corruption
- ❌ If writes to DIFFERENT keys: Both succeed but slow

**Risk**: Low (SQLite WAL handles it), but performance is bad.

---

#### Scenario 3: Power Loss Mid-Write

```
SQLite Page Cache:
┌─────────────────────┐
│ Page 1: namespace   │
│ Page 2: key, value  │ ← Partial write during crash
│ Page 3: index       │
└─────────────────────┘
         ↓ (no fsync)
OS Buffer: Not yet written to disk
         ↓ Power loss
Hard Drive: Old version of page still on disk

Restart:
SQLite reads old data from disk, WAL is corrupted
```

**Result**:
- ❌ If `synchronous=OFF`, old data is read
- ❌ If `synchronous=NORMAL`, more likely to recover but not guaranteed
- ✓ If `synchronous=FULL`, WAL prevents corruption

---

### B. Validation Gaps

| Aspect | Current | Status |
|--------|---------|--------|
| **Integrity Checksum** | ❌ None | No way to detect corruption |
| **Version Field** | ⚠️ Partial (secrets only) | Most namespaces lack version |
| **Migration Model** | ❌ None | No schema versioning |
| **Validation on Load** | ❌ JSON only | No semantic validation |
| **Backup Verification** | ❌ None | Can't verify backup integrity |

---

## 4️⃣ ROLLBACK ATTACKS

### A. Attack Vector: Copy Old Database File

```bash
# Attacker gets access to disk (stolen laptop, cloud backup, etc.)
$ cp data.db data.db.bak
$ cp storage_backup_from_last_week.db data.db
# Restart application

# Application restarts with OLD storage
```

### B. Vulnerable Scenarios

#### Scenario 1: Rollback Trust Store

```json
// Current trust store entry:
{
  "plugin_id": "yandex_device_auth",
  "trust_level": "CORE",
  "signature": "...",
  "updated_at": "2026-02-17T15:00:00Z"
}

// Rollback to week-old version:
{
  "plugin_id": "yandex_device_auth",
  "trust_level": "DEVELOPER",  ← Downgraded!
  "signature": "...",
  "updated_at": "2026-02-10T15:00:00Z"  ← Old timestamp
}
```

**Attack Success**: ✓ Yes! Plugin trust level rolled back.

**Risk**: **P0 — CRITICAL**

---

#### Scenario 2: Rollback Agent Enrollment

```json
// Current:
{
  "agent_id": "laptop_123",
  "status": "DEREGISTERED",  ← Recently revoked
  "revoked_at": "2026-02-17T14:30:00Z"
}

// Rollback to when agent was enrolled:
{
  "agent_id": "laptop_123",
  "status": "ONLINE",  ← Restored to active!
  "enrolled_at": "2026-02-01T10:00:00Z"
}
```

**Attack Success**: ✓ Yes! Deregistered agent is active again.

**Risk**: **P0 — CRITICAL**

---

#### Scenario 3: Rollback Secret Keys

```json
// Current:
{
  "namespace": "secrets.store",
  "key": "oauth_yandex_token",
  "value": {/* rotated token */},
  "rotated_at": "2026-02-17T12:00:00Z"
}

// Rollback to old token:
{
  "namespace": "secrets.store",
  "key": "oauth_yandex_token",
  "value": {/* OLD expired token */},
  "rotated_at": "2026-02-01T12:00:00Z"
}
```

**Attack Success**: ⚠️ Partially. Token revocation bypassed, but Yandex API will reject old token.

**Risk**: **P1 — IMPORTANT** (mitigated by external validation)

---

### C. Rollback Defense Mechanisms

| Mechanism | Current | Status |
|-----------|---------|--------|
| **Monotonic Counter** | ❌ None | No sequence number |
| **Timestamp Validation** | ❌ None | Timestamps not verified |
| **Append-Only Log** | ❌ None | No audit trail |
| **Hash Chain** | ❌ None | No previous hash linking |
| **Signed State** | ❌ None | No cryptographic proof |
| **Version Epoch** | ✓ Partial | Trust store has version, others don't |

---

## 5️⃣ CONCURRENCY SAFETY

### A. Lock Types Used

```python
# SQLiteAdapter:
self._local = threading.local()  # Thread-local storage
# Implicit SQLite WAL reader-writer lock

# PostgreSQLAdapter:
self._pool = asyncpg.create_pool()  # Connection pool
# Implicit MVCC + row-level locks

# SecretStore:
self._lock = asyncio.Lock()  # Async mutex for key initialization

# CapabilityRegistry (after recent fix):
self._lock = threading.Lock()  # Threading lock for sync methods
```

### B. Race Condition Analysis

| Race Scenario | Participant | Current Protection | Risk |
|---------------|-------------|-------------------|------|
| **put() + get()** | Storage | DB implicit lock | ✓ Safe (ACID) |
| **rotate() + get()** | SecretStore | asyncio.Lock | ⚠️ Partial |
| **transaction + installer** | Marketplace | No synchronization | ❌ **Race possible** |
| **agent heartbeat + deregister** | AgentRegistry | In-memory only | ⚠️ No persistence |

#### Scenario: Rotate Secret While Client Reading

```python
# Thread A: Client
value = await secret_store.get("oauth_token")

# Thread B: Rotation
async def rotate():
    await secret_store.put("oauth_token", new_key)  # Acquires lock

# Result:
# - Thread A may get old key (before rotation)
# - Thread A may get new key (after rotation)
# - Both are acceptable outcomes (old key still valid)

# But what if Thread A gets partially rotated data?
```

**Current Protection**: `asyncio.Lock` in SecretStore.  
**Race Window**: Minimal (only during put to storage).

---

### C. Storage Transaction Race

```python
# App expects transactions to be atomic:
async with storage.transaction():
    await storage.set("ns", "key1", val1)
    await storage.set("ns", "key2", val2)
    # Both should succeed or both fail

# But if installer runs concurrently:
installer_thread: await storage.set("ns", "key3", val3)
# installer_thread is NOT part of transaction!

# Result: Partial state visible to installer
```

**Risk**: **P1 — IMPORTANT** (app assuming isolation guarantees)

---

## 6️⃣ DURABILITY & CRASH SAFETY

### A. SQLite Durability Matrix

```python
# No explicit pragma configuration in code!
# Defaults are DANGEROUS:

┌─────────────────────┬──────────────┬──────────────┬──────────────┐
│ PRAGMA          │ Current      │ Safe Value   │ Trade-off    │
├─────────────────────┼──────────────┼──────────────┼──────────────┤
│ synchronous     │ OFF (default)│ FULL         │ 3-5x slower  │
│ journal_mode    │ WAL (✓)      │ WAL (✓)      │ None         │
│ cache_size      │ -2000 (tiny!)│ -64000       │ +128MB RAM   │
│ busy_timeout    │ 30000ms (✓)  │ 30000ms (✓)  │ None         │
│ foreign_keys    │ OFF (default)│ ON           │ +1% slowdown │
│ integrity_check │ Never        │ Periodic     │ +0.1% CPU    │
└─────────────────────┴──────────────┴──────────────┴──────────────┘
```

**Critical Missing**: `PRAGMA synchronous=FULL`

Without it:
- ❌ Data loss on power failure
- ❌ Potential corruption on crash
- ✓ Good performance (reason for default OFF)

---

### B. Crash-Safety Scenarios

| OS / Filesystem | SQLite (sync=OFF) | SQLite (sync=FULL) | PostgreSQL |
|-----------------|---|----|---|
| **Linux ext4** | ❌ Data loss | ✓ Safe | ✓ Safe |
| **macOS APFS** | ❌ Data loss | ⚠️ Depends | ✓ Safe |
| **NFS** | ❌ Very risky | ❌ Risky | ↔️ Network dependent |
| **Docker overlay FS** | ❌ Data loss | ⚠️ Risky (no fsync guarantee) | ⚠️ Risky |

**Problem**: No guarantee of fsync propagation to disk on all filesystems.

---

### C. Fsync Guarantee Assessment

```
┌──────────────┐
│ conn.commit()│ ← SQLite method
└──────────────┘
        ↓
┌──────────────────────────────────────┐
│ if sync=OFF:                         │
│   - Write to page cache              │
│   - Return immediately (no fsync)    │
│   - Risk: power loss = data loss     │
└──────────────────────────────────────┘
        ↓
┌──────────────────────────────────────┐
│ if sync=FULL:                        │
│   - Write to page cache              │
│   - fsync() system call              │
│   - Wait for disk confirmation       │
│   - Return (durable)                 │
└──────────────────────────────────────┘
```

**Current code**: ❌ Using default (OFF)

---

## 7️⃣ STORAGE ISOLATION

### A. Namespace Isolation Physical Separation

```python
# Current: All namespaces in SAME table
sql> CREATE TABLE storage (
    namespace TEXT,
    key TEXT,
    value TEXT,
    PRIMARY KEY (namespace, key)
)

# Result:
# ✓ Logical separation (different namespace values)
# ❌ Physical separation (all in same file/table)
# ⚠️ One corrupted entry can affect entire table
```

### B. Path Traversal Risk

```python
# Storage API validates namespace/key:
if not isinstance(namespace, str) or not namespace:
    raise ValueError(...)  # Good!

# But what if attacker passes:
namespace = "marketplace.transactions"
key = "../../etc/passwd"
# Result:
# ✓ SQLite doesn't allow directory traversal
# ✓ Key stored as-is in DB
# ✓ No filesystem access (it's just text)
```

**Risk**: ✓ LOW (no filesystem access)

---

### C. Namespace Collision Risk

```json
// marketplace namespace:
{"marketplace.transactions": {"tx_123": {...}}}

// Could attacker write to marketplace namespace?
await storage.set("marketplace.transactions", "tx_999", ...)  // ❌ Blocked? 

// Current architecture relies on:
// 1. Plugin isolation (plugins can't call arbitrary set())
// 2. Service registry (only registered services allow set())
```

**Risk**: ⚠️ MEDIUM (if plugin isolation is weak)

---

### D. Prefix Collision

```python
# Keys in same namespace could collide:
namespace "agent"
  key: "abc"         → stored value for "abc"
  key: "abc_123"     → stored value for "abc_123"

# If someone queries "key starts with abc":
# They get both unintentionally
```

**Current**: ❌ No query "starts_with" API (only exact key match)  
**Risk**: ✓ LOW

---

## 8️⃣ THREAT MODEL: COLD DATA

### A. Threat: Disk Image Stolen

**Attacker has**: Raw disk copy (from laptop theft, cloud backup, etc.)

| Data | Protection | Outlook |
|------|-----------|---------|
| **Trust Store** | ❌ Plaintext JSON |🔴 Readable |
| **Secret Store** | ✓ AES-256-GCM | 🟢 Protected (if passphrase strong) |
| **Agent Registry** | ❌ Plaintext JSON | 🔴 Readable (can see enrolled agents) |
| **Marketplace Transactions** | ❌ Plaintext JSON | 🔴 Readable (can see user purchases) |
| **OAuth Tokens** | ✓ Encrypted (per plugin code) | 🟢 Protected |

---

### B. Threat: Root Attacker

**Attacker has**: Root access on running system

| Scenario | Protection |
|----------|-----------|
| Read files while runtime running | ❌ Can read unencrypted storage directly |
| Dump process memory | ❌ DEK in memory during runtime |
| Intercept network traffic | ⚠️ Depends on TLS (not storage's problem) |

---

### C. Threat: Backup Compromise

**Attacker has**: Copy of backup file (old or current)

| Scenario | Protection |
|----------|-----------|
| Restore old backup | ❌ No rollback protection (monotonic counter) |
| Modify backup + restore | ❌ No signature/HMAC to detect tampering |
| Extract secrets from backup | ✓ AES-256-GCM (if backup-at-rest encryption enabled) |

---

### D. Threat: Snapshot Restore

**Attacker has**: VMware/Docker snapshot from past state

| Scenario | Protection |
|----------|-----------|
| Restore snapshot | ❌ No epoch/lease to detect stale snapshot |
| Rollback agent revocation | ❌ No monotonic counter |
| Replay old transaction | ⚠️ No idempotency key |

---

## 9️⃣ SECURITY SUMMARY: P0 / P1 / P2

### 🔴 P0 — ARCHITECTURAL PROBLEMS (Must Fix)

1. **SQLite synchronous=OFF by default**
   - **Impact**: Data loss on power failure
   - **Example**: Secret keys lost, marketplace transactions incomplete
   - **Fix**: Set `PRAGMA synchronous=FULL`
   - **Cost**: 3-5x slower writes (acceptable for cold storage)

2. **No Rollback Protection**
   - **Impact**: Attacker can restore old DB file to downgrade trust level, reactivate agents, restore old secrets
   - **Example**: Deregistered agent becomes active again
   - **Fix**: Add monotonic counter + timestamp validation OR signed state
   - **Cost**: +1 column per record, +validation logic

3. **Marketplace Transaction State Not Atomic**
   - **Impact**: Dangling payments (user charged but install not started)
   - **Example**: System crashes between payment confirmation and state update
   - **Fix**: Use explicit transaction() context manager for entire flow
   - **Cost**: Better error handling required

4. **No Corruption Detection Mechanism**
   - **Impact**: Silent data corruption (truncated JSON returns None)
   - **Example**: Secret key corrupted but no alert
   - **Fix**: Add integrity checksum + periodic verification
   - **Cost**: +HMAC per record, +validation CPU

---

### 🟡 P1 — IMPORTANT IMPROVEMENTS (Should Fix)

5. **Agent Heartbeat Not Persisted**
   - **Impact**: On restart, lose all liveness information
   - **Example**: Agents appear offline after kernel restart
   - **Fix**: Periodic flush of heartbeat timestamps to storage
   - **Cost**: Extra I/O (can be batched)

6. **No Audit Log / Append-Only Mechanism**
   - **Impact**: Can't verify what changed and when
   - **Example**: Attacker modifies trust store, no trace
   - **Fix**: Add append-only audit log (separate from cold storage)
   - **Cost**: Extra storage, periodic cleanup

7. **No Version Epoch for Snapshots**
   - **Impact**: Can't detect stale snapshots
   - **Example**: Docker container restored from 1-week-old snapshot
   - **Fix**: Add epoch/lease validation before accepting state
   - **Cost**: Network call to timestamp service (optional)

8. **Storage Namespace Collision Risk (If Plugins Can Write)**
   - **Impact**: Plugin could overwrite marketplace data
   - **Example**: Malicious plugin sets marketplace.transactions records
   - **Fix**: Enforce namespace write ACL + plugin signing
   - **Cost**: +ACL table, +signature verification

---

### 💚 P2 — NICE TO HAVE (Can Defer)

9. **NFS Durability Concerns**
   - **Fix**: Document NFS limitations or add explicit NFS fsync detection
   - **Cost**: Platform-specific logic

10. **SQLite Cache Size Too Small**
    - **Fix**: Increase `-cache_size` from -2000 to -64000
    - **Cost**: +128MB RAM

11. **No Backup Verification**
    - **Fix**: Add backup integrity check script
    - **Cost**: Optional utility

12. **Docker Overlay FS Risky for SQLite**
    - **Fix**: Recommend PostgreSQL for containerized deployments
    - **Cost**: Deployment docs update

---

## 🎯 PRIORITY ROADMAP

### Phase 1: Quick Wins (1-2 hours)

- [ ] **1.1**: Enable `PRAGMA synchronous=FULL` in SQLiteAdapter
- [ ] **1.2**: Add integrity checksum to secret store
- [ ] **1.3**: Wrap marketplace transaction flow in explicit `async with storage.transaction()`

### Phase 2: Rollback Protection (4-6 hours)

- [ ] **2.1**: Add `monotonic_counter` field to all critical namespaces
- [ ] **2.2**: Implement timestamp validation (reject if < stored timestamp)
- [ ] **2.3**: Add `_version` field to trust store, agent registry, marketplace records

### Phase 3: Observability (3-4 hours)

- [ ] **3.1**: Add periodic integrity verification script
- [ ] **3.2**: Log corruption events (not silent failures)
- [ ] **3.3**: Implement heartbeat flush to storage (every 60s)

### Phase 4: Defense in Depth (2-3 weeks)

- [ ] **4.1**: Append-only audit log
- [ ] **4.2**: Signed state (Ed25519 signature on critical records)
- [ ] **4.3**: Epoch/lease validation for snapshots

---

## 📊 COMPARISON: SQLite vs PostgreSQL vs Other Options

| Aspect | SQLite | PostgreSQL | RocksDB | FoundationDB |
|--------|--------|------------|---------|---|
| **Crash-Safe (with sync=FULL)** | ✓ | ✓ | ✓ | ✓ |
| **Rollback Resistant** | ❌ | ❌ | ❌ | ✓ (append-only) |
| **Corruption Detection** | ⚠️ | ✓ | ✓ | ✓ |
| **Setup Complexity** | ✓ Easy | ⚠️ Medium | ✓ Easy | 🔴 Hard |
| **Deployment Size** | 1MB | 50MB+ | 5MB | 100MB+ |
| **Suitable for OS** | ✓ Yes | ✓ Yes (prod) | ⚠️ Embedded | 🔴 No |

**Recommendation**: 
- **Dev/Test**: SQLite (with sync=FULL)
- **Production**: PostgreSQL + append-only audit log
- **Embedded Systems**: RocksDB + custom audit loop

---

## ✅ CONCLUSION

**Cold storage is the foundation of your system.**

Current state:
- ✓ Architecture is sound (namespace + key + value)
- ✓ WAL mode enabled
- ✓ Thread-local connections avoid race conditions
- ❌ **Missing durability guarantees** (sync=OFF default)
- ❌ **Vulnerable to rollback attacks** (no monotonic counter)
- ❌ **No corruption detection** (silently returns None)

**With fixes**, your storage layer becomes enterprise-grade:
1. Crash-safe (Phase 1)
2. Rollback-resistant (Phase 2)
3. Observable & auditable (Phase 3-4)

This transforms cold storage **from a risk to a strength**.

---

**Next Steps**: 
1. Review P0 issues with team
2. Implement Phase 1 fixes (1-2 hours)
3. Run chaos testing (kill -9, power loss simulation)
4. Move to Phase 2 (rollback protection)

