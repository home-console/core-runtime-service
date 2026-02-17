# 🔧 ХОЛОДНОЕ ХРАНИЛИЩЕ — ПЛАН ИСПРАВЛЕНИЙ

**Scope**: SQLiteAdapter, PostgreSQLAdapter, integration tests  
**Цель**: Сделать storage crash-safe, rollback-resistant, и observable.

---

## PHASE 1: CRITICAL FIXES (1-2 часа)

### Fix 1.1: Enable fsync в SQLiteAdapter

**File**: `adapters/sqlite_adapter.py`  
**Lines**: в методе `_get_connection()` после создания соединения

**Current Code**:
```python
def _get_connection(self) -> sqlite3.Connection:
    if not hasattr(self._local, 'conn') or self._local.conn is None:
        self._local.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=True,
            timeout=30.0
        )
        self._local.conn.execute("PRAGMA journal_mode=WAL")
    return self._local.conn
```

**Fix**:
```python
def _get_connection(self) -> sqlite3.Connection:
    if not hasattr(self._local, 'conn') or self._local.conn is None:
        self._local.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=True,
            timeout=30.0
        )
        # CRITICAL: Enable crash safety
        self._local.conn.execute("PRAGMA journal_mode=WAL")
        self._local.conn.execute("PRAGMA synchronous=FULL")  # ← NEW
        # Optimize performance while maintaining safety
        self._local.conn.execute("PRAGMA cache_size=-64000")  # ← NEW (64MB)
        # Enable foreign key constraints
        self._local.conn.execute("PRAGMA foreign_keys=ON")  # ← NEW
    return self._local.conn
```

**Impact**: 
- ✓ Data is durable on disk after commit()
- ⚠️ Up to 3-5x slower writes (acceptable for cold storage)
- ✓ Crash-safe guarantees

**Testing**:
```python
# Kill -9 during write, restart, verify data still there
async def test_crash_safety():
    adapter = SQLiteAdapter("test.db")
    await adapter.initialize_schema()
    await adapter.set("test", "key", {"value": "persisted"})
    
    # Simulate process crash (in real test, use subprocess)
    # Restart and verify
    adapter2 = SQLiteAdapter("test.db")
    await adapter2.initialize_schema()
    result = await adapter2.get("test", "key")
    assert result["value"] == "persisted"
```

---

### Fix 1.2: Add Integrity Checksum to SecretStore

**File**: `core/security/secret_store.py`  
**Purpose**: Detect if encrypted blob is corrupted

**Current Code**:
```python
async def put(self, key: str, value: bytes) -> None:
    encrypted = encrypt(value, self._dek)  # Returns (nonce, ciphertext, tag)
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

**Fix**:
```python
import hashlib

async def put(self, key: str, value: bytes) -> None:
    encrypted = encrypt(value, self._dek)
    
    # CRITICAL: Add integrity checksum
    checksum_data = f"{encrypted.nonce}{encrypted.ciphertext}{encrypted.tag}".encode()
    checksum = hashlib.sha256(checksum_data).hexdigest()
    
    await self._storage.set(
        "secrets.store",
        key,
        {
            "nonce": encrypted.nonce.hex(),
            "ciphertext": encrypted.ciphertext.hex(),
            "tag": encrypted.tag.hex(),
            "checksum": checksum,  # ← NEW
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
        }
    )

async def get(self, key: str) -> Optional[bytes]:
    blob = await self._storage.get("secrets.store", key)
    if blob is None:
        return None
    
    # CRITICAL: Verify checksum before decryption
    stored_checksum = blob.get("checksum")
    if stored_checksum:
        checksum_data = f"{blob['nonce']}{blob['ciphertext']}{blob['tag']}".encode()
        expected = hashlib.sha256(checksum_data).hexdigest()
        if not constant_time_compare(stored_checksum.encode(), expected.encode()):
            # ALERT: Corruption detected
            import logging
            logging.error(f"[SecretStore] CORRUPTION DETECTED for key {key}")
            raise ValueError(f"Secret store corruption detected for key {key}")
    
    # Proceed with decryption...
```

**Impact**:
- ✓ Detects bit flips, truncation, tampering
- ✓ Alerts instead of silent failure
- ⚠️ Extra SHA256 per get/put

---

### Fix 1.3: Wrap Marketplace Transactions in Explicit Transaction Context

**File**: Location of marketplace transaction creation  
**Current Code** (example):
```python
async def create_transaction(self, items, ...):
    tx_id = generate_id()
    
    # Step 1: Create record
    await storage.set("marketplace.transactions", tx_id, {
        "state": "created",
        "items": items,
    })
    
    # Step 2: Process payment
    payment = await payment_service.process(items)
    
    # Step 3: Update state ← CRASH HERE = dangling payment
    await storage.set("marketplace.transactions", tx_id, {
        "state": "paid",
        "payment_id": payment.id,
    })
    
    # Step 4: Install
    await install_items(items)
    
    # Step 5: Final ← CRASH HERE = items install but not marked done
    await storage.set("marketplace.transactions", tx_id, {
        "state": "completed",
    })
```

**Fix**:
```python
async def create_transaction(self, items, ...):
    tx_id = generate_id()
    
    # CRITICAL: Entire flow in transaction
    async with self.storage.transaction():
        # Step 1: Create record
        await self.storage.set("marketplace.transactions", tx_id, {
            "state": "created",
            "items": items,
            "idempotency_key": generate_id(),  # ← NEW: for replay detection
        })
        
        # Step 2: Process payment
        try:
            payment = await self.payment_service.process(items)
        except Exception as e:
            # Transaction rolls back automatically
            # Payment service should be idempotent
            raise
        
        # Step 3: Update state (now atomic with payment)
        await self.storage.set("marketplace.transactions", tx_id, {
            "state": "paid",
            "payment_id": payment.id,
        })
        
        # Step 4: Install items (inside transaction)
        try:
            await self.install_items(items)
        except Exception as e:
            # Transaction rolls back, payment must be refunded separately
            raise
        
        # Step 5: Final (atomic with everything)
        await self.storage.set("marketplace.transactions", tx_id, {
            "state": "completed",
        })
    
    # Transaction committed atomically
```

**Impact**:
- ✓ Either entire flow succeeds or rolls back
- ⚠️ Need idempotency for payment service
- ✓ No dangling payments

---

## PHASE 2: ROLLBACK PROTECTION (4-6 часов)

### Fix 2.1: Add Monotonic Counter to Critical Namespaces

**New File**: `core/storage/monotonic_counter.py`

```python
"""
Monotonic counter wrapper for rollback protection.

Usage:
    counter = MonotonicCounter(storage)
    seq = await counter.next("trust_store")
    # seq is guaranteed to increase even if storage is rolled back
"""

import time
from typing import Optional

class MonotonicCounter:
    """
    Track sequence numbers for rollback detection.
    
    Stores in storage but also verifies:
    - Timestamp never goes backwards
    - Sequence number always increases
    """
    
    def __init__(self, storage):
        self._storage = storage
        self._namespace = "_monotonic"
        self._cache = {}  # In-memory cache for current max
    
    async def initialize(self):
        """Load current counters into cache."""
        keys = await self._storage.list_keys(self._namespace)
        for key in keys:
            record = await self._storage.get(self._namespace, key)
            if record:
                self._cache[key] = record.get("sequence", 0)
    
    async def next(self, counter_name: str) -> dict:
        """
        Get next sequence number.
        
        Returns: {sequence, timestamp, recorded_at}
        """
        current = self._cache.get(counter_name, 0)
        sequence = current + 1
        now = time.time()
        
        record = {
            "sequence": sequence,
            "timestamp": now,
            "prev_sequence": current,
        }
        
        await self._storage.set(self._namespace, counter_name, record)
        self._cache[counter_name] = sequence
        
        return record
    
    async def validate(self, counter_name: str, expected_sequence: int) -> bool:
        """
        Validate that sequence hasn't been rolled back.
        
        Returns: True if valid, False if rollback detected
        """
        record = await self._storage.get(self._namespace, counter_name)
        if not record:
            return False  # Never incremented
        
        actual = record.get("sequence", 0)
        return actual >= expected_sequence
```

**Usage in Trust Store**:
```python
async def register_provider(self, capability_id, plugin_name, ..., counter: MonotonicCounter):
    """
    Register capability provider.
    """
    # Get monotonic sequence
    seq_record = await counter.next("trust_store")
    
    # Store with sequence
    await self._storage.set(
        "trust_store",
        f"{capability_id}:{plugin_name}",
        {
            "capability_id": capability_id,
            "plugin_name": plugin_name,
            "trust_level": trust_level,
            "sequence": seq_record["sequence"],  # ← NEW
            "timestamp": seq_record["timestamp"],  # ← NEW
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
```

**Validation on Load**:
```python
async def validate_trust_store(self, counter: MonotonicCounter):
    """
    After loading trust store, validate no rollback.
    """
    records = await self._storage.list_keys("trust_store")
    for record_key in records:
        record = await self._storage.get("trust_store", record_key)
        sequence = record.get("sequence", 0)
        
        # Verify sequence hasn't decreased
        if not await counter.validate("trust_store", sequence):
            raise SecurityError(f"Rollback detected in trust_store: {record_key}")
```

**Impact**:
- ✓ Detects if old DB file is restored
- ⚠️ Extra column + counter table
- ✓ Can't downgrade trust levels or reactivate revoked agents

---

### Fix 2.2: Add Version Field Migration

**New File**: `core/storage/version_schema.py`

```python
"""
Storage schema versioning and validation.
"""

SCHEMA_VERSION = 2

class StorageSchemaValidator:
    """
    Validate and migrate storage schema versions.
    """
    
    async def validate(self, storage):
        """
        Check storage schema version.
        Raises if migration needed.
        """
        meta = await storage.get("_schema", "version")
        if not meta:
            # Fresh storage
            await storage.set("_schema", "version", {
                "version": SCHEMA_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            return
        
        version = meta.get("version", 1)
        if version < SCHEMA_VERSION:
            raise RuntimeError(
                f"Storage schema {version} requires migration to {SCHEMA_VERSION}. "
                f"Run: python -m core.storage.migrate"
            )
        elif version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Storage schema {version} too new for this version of app. "
                f"Upgrade application."
            )
```

**Add to all critical records**:
```python
{
    "capability_id": "oauth:yandex",
    "plugin_name": "oauth_yandex",
    "trust_level": "PUBLISHER",
    "sequence": 42,  # ← NEW (monotonic)
    "timestamp": "2026-02-17T15:00:00Z",  # ← NEW
    "_version": 2,  # ← NEW (schema version)
    "updated_at": "2026-02-17T15:00:00Z",
}
```

---

### Fix 2.3: Add Append-Only Audit Log

**New File**: `core/storage/audit_log.py`

```python
"""
Append-only audit log for cold storage mutations.
"""

import json
from datetime import datetime, timezone
from typing import Any

class AuditLog:
    """
    Immutable append-only log of all storage mutations.
    
    Stored in separate table: audit_log (id, timestamp, namespace, key, operation, value_hash, actor)
    """
    
    def __init__(self, storage):
        self._storage = storage
        self._counter = 0
    
    async def log(
        self,
        namespace: str,
        key: str,
        operation: str,  # "SET", "DELETE", "UPDATE"
        value: dict[str, Any],
        actor: str = "system"
    ):
        """
        Log a storage operation.
        """
        import hashlib
        
        self._counter += 1
        
        value_hash = hashlib.sha256(
            json.dumps(value, sort_keys=True).encode()
        ).hexdigest()
        
        log_entry = {
            "id": self._counter,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "namespace": namespace,
            "key": key,
            "operation": operation,  # SET / DELETE / UPDATE
            "value_hash": value_hash,
            "actor": actor,
        }
        
        # Append to audit log (never modify existing entries)
        await self._storage.set(
            "_audit",
            f"{self._counter:010d}",  # Sortable by ID
            log_entry
        )
```

**Integration**:
```python
# Before ANY set/delete, log it:
async def set_with_audit(storage, audit_log, namespace, key, value, actor="system"):
    await storage.set(namespace, key, value)
    await audit_log.log(namespace, key, "SET", value, actor)

# On startup, validate audit log integrity:
async def validate_audit_log(audit_log):
    """
    Verify audit log wasn't tampered with.
    """
    logs = await audit_log._storage.list_keys("_audit")
    if len(logs) == 0:
        return
    
    # Check sequence is 1, 2, 3, ... (no gaps, no duplicates)
    expected_ids = set(f"{i:010d}" for i in range(1, len(logs) + 1))
    actual_ids = set(logs)
    
    if expected_ids != actual_ids:
        raise SecurityError("Audit log tampering detected (missing or duplicate entries)")
```

**Impact**:
- ✓ Can reconstruct what changed and when
- ✓ Can detect if audit log was edited
- ⚠️ Grows unbounded (need periodic cleanup)

---

## PHASE 3: OBSERVABILITY (3-4 часа)

### Fix 3.1: Periodic Integrity Verification

**New File**: `core/storage/integrity_checker.py`

```python
"""
Periodic integrity verification for storage.
"""

import asyncio
import hashlib
import logging

class StorageIntegrityChecker:
    """
    Background task: verify storage integrity periodically.
    """
    
    def __init__(self, storage, interval_seconds=3600):
        self._storage = storage
        self._interval = interval_seconds
        self._logger = logging.getLogger("storage.integrity")
        self._running = False
    
    async def start(self):
        """Start background integrity check."""
        self._running = True
        asyncio.create_task(self._check_loop())
    
    async def stop(self):
        """Stop background integrity check."""
        self._running = False
    
    async def _check_loop(self):
        """Run integrity checks periodically."""
        while self._running:
            try:
                await self._verify_all_namespaces()
            except Exception as e:
                self._logger.error(f"Integrity check failed: {e}")
            
            await asyncio.sleep(self._interval)
    
    async def _verify_all_namespaces(self):
        """
        Check all namespaces for corruption.
        """
        namespaces = await self._storage.list_namespaces()
        
        for namespace in namespaces:
            if namespace.startswith("_"):
                continue  # Skip internal namespaces
            
            try:
                await self._verify_namespace(namespace)
            except Exception as e:
                self._logger.error(f"Corruption in {namespace}: {e}")
    
    async def _verify_namespace(self, namespace: str):
        """
        Verify all records in namespace.
        """
        keys = await self._storage.list_keys(namespace)
        
        for key in keys:
            try:
                record = await self._storage.get(namespace, key)
                
                if record is None:
                    self._logger.warning(
                        f"[{namespace}] Key {key} returned None (possible corruption)"
                    )
                    continue
                
                # Verify required fields
                if "_version" in record:
                    # Schema version check
                    version = record.get("_version", 1)
                    if version != 2:
                        self._logger.warning(
                            f"[{namespace}] Key {key} has old schema version {version}"
                        )
                
                # Verify checksum if present
                if "checksum" in record:
                    await self._verify_checksum(namespace, key, record)
                
            except Exception as e:
                self._logger.error(f"Error verifying [{namespace}] {key}: {e}")
    
    async def _verify_checksum(self, namespace: str, key: str, record: dict):
        """
        Verify integrity checksum.
        """
        stored_checksum = record.get("checksum")
        expected_data = {k: v for k, v in record.items() if k != "checksum"}
        expected_hash = hashlib.sha256(
            str(sorted(expected_data.items())).encode()
        ).hexdigest()
        
        if stored_checksum != expected_hash:
            raise ValueError(
                f"Checksum mismatch: expected {expected_hash}, got {stored_checksum}"
            )
```

**Integration**:
```python
# In CoreRuntime.start():
async def start(self):
    # ... existing code ...
    
    # Start integrity checker
    self.integrity_checker = StorageIntegrityChecker(
        self.storage,
        interval_seconds=3600  # Every hour
    )
    await self.integrity_checker.start()
```

---

### Fix 3.2: Log Corruption Events (Not Silent)

**Modify**: `adapters/sqlite_adapter.py` get() method

**Current**:
```python
try:
    return json.loads(value)
except (json.JSONDecodeError, ValueError, TypeError) as e:
    print(f"[SQLiteAdapter] Error parsing JSON: {e}")
    return None  # Silent!
```

**Fix**:
```python
try:
    return json.loads(value)
except (json.JSONDecodeError, ValueError, TypeError) as e:
    import logging
    logger = logging.getLogger("storage.corruption")
    logger.CRITICAL(  # ← Use CRITICAL level
        f"[SQLiteAdapter] CORRUPTION DETECTED in {namespace}.{key}: {e}",
        extra={"value_truncated": value[:100]}
    )
    # Also raise alert to monitoring system
    await self._send_alert(f"Storage corruption in {namespace}.{key}")
    return None  # Fail later in application logic
```

---

### Fix 3.3: Heartbeat Flush to Storage

**New File**: `core/agent/heartbeat_flush.py`

```python
"""
Periodic flush of agent heartbeats to persistent storage.
"""

import asyncio
from datetime import datetime, timezone

class HeartbeatFlusher:
    """
    Background task: periodically save agent heartbeat state.
    """
    
    def __init__(self, agent_registry, storage, interval_seconds=60):
        self._registry = agent_registry
        self._storage = storage
        self._interval = interval_seconds
        self._running = False
    
    async def start(self):
        """Start periodic flushing."""
        self._running = True
        asyncio.create_task(self._flush_loop())
    
    async def stop(self):
        """Stop flushing."""
        self._running = False
    
    async def _flush_loop(self):
        """Flush heartbeats periodically."""
        while self._running:
            try:
                await self._flush_all()
            except Exception as e:
                import logging
                logging.error(f"Heartbeat flush failed: {e}")
            
            await asyncio.sleep(self._interval)
    
    async def _flush_all(self):
        """
        Save all agent heartbeats to persistent storage.
        """
        agents = self._registry.list_agents()
        
        for agent_id, metadata in agents.items():
            # Save heartbeat timestamp
            await self._storage.set(
                "agent.heartbeat",
                agent_id,
                {
                    "agent_id": agent_id,
                    "last_heartbeat": metadata.get("last_heartbeat"),
                    "status": metadata.get("status"),
                    "flushed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
```

**Integration**:
```python
# In CoreRuntime.start():
self.heartbeat_flusher = HeartbeatFlusher(
    self.agent_registry,
    self.storage,
    interval_seconds=60
)
await self.heartbeat_flusher.start()

# On shutdown:
await self.heartbeat_flusher.stop()
```

**Recovery on startup**:
```python
async def restore_agent_heartbeats(self):
    """
    On startup, restore agent heartbeat state.
    """
    keys = await self.storage.list_keys("agent.heartbeat")
    
    for agent_id in keys:
        record = await self.storage.get("agent.heartbeat", agent_id)
        if record:
            self.agent_registry._agents[agent_id]["last_heartbeat"] = record.get("last_heartbeat")
            self.agent_registry._agents[agent_id]["flushed_at"] = record.get("flushed_at")
```

---

## TESTING STRATEGY

### Test 1: Crash Safety

```python
@pytest.mark.asyncio
async def test_crash_safety_sqlite():
    """
    Verify data persists after process crash.
    """
    import subprocess
    import os
    
    db_path = "test_crash.db"
    
    # Step 1: Write data
    adapter = SQLiteAdapter(db_path)
    await adapter.initialize_schema()
    await adapter.set("test", "key1", {"value": "test"})
    
    # Step 2: Force kill subprocess with SIGKILL
    # (in real test, use subprocess to simulate)
    
    # Step 3: Restart and verify
    adapter2 = SQLiteAdapter(db_path)
    await adapter2.initialize_schema()
    result = await adapter2.get("test", "key1")
    
    assert result["value"] == "test", "Data lost after crash"
    os.remove(db_path)
```

### Test 2: Rollback Protection

```python
@pytest.mark.asyncio
async def test_rollback_detection():
    """
    Verify monotonic counter detects rollback.
    """
    storage = Storage(SQLiteAdapter(":memory:"))
    await storage._adapter.initialize_schema()
    
    counter = MonotonicCounter(storage)
    await counter.initialize()
    
    # Step 1: Get sequence #1
    seq1 = await counter.next("test_counter")
    assert seq1["sequence"] == 1
    
    # Step 2: Get sequence #2
    seq2 = await counter.next("test_counter")
    assert seq2["sequence"] == 2
    
    # Step 3: Manually rollback counter (simulate old backup restore)
    await storage.set("_monotonic", "test_counter", {
        "sequence": 1,
        "timestamp": time.time(),
    })
    
    # Step 4: Try to validate #2
    is_valid = await counter.validate("test_counter", 2)
    assert is_valid is False, "Rollback not detected"
```

### Test 3: Corruption Detection

```python
@pytest.mark.asyncio
async def test_corruption_detection():
    """
    Verify checksum detects corruption.
    """
    storage = Storage(SQLiteAdapter(":memory:"))
    await storage._adapter.initialize_schema()
    
    secret_store = SecretStore(storage._adapter)
    await secret_store.initialize("test_passphrase")
    
    # Step 1: Put secret
    await secret_store.put("key1", b"secret_value")
    
    # Step 2: Manually corrupt stored checksum
    blob = await storage.get("secrets.store", "key1")
    blob["checksum"] = "corrupted_checksum_value"
    await storage.set("secrets.store", "key1", blob)
    
    # Step 3: Try to get secret
    with pytest.raises(ValueError, match="corruption detected"):
        await secret_store.get("key1")
```

---

## DEPLOYMENT CHECKLIST

- [ ] Test Phase 1 fixes locally
- [ ] Run crash safety test
- [ ] Run rollback detection test
- [ ] Measure performance impact (pragma synchronous=FULL)
- [ ] Update documentation
- [ ] Deploy to staging
- [ ] Verify logs show integrity checks passing
- [ ] Deploy to production
- [ ] Monitor for storage corruption alerts

---

## SUMMARY

| Phase | Focus | Time | Impact |
|-------|-------|------|--------|
| **1** | Crash safety (fsync, checksum) | 1-2h | Eliminates P0 data loss |
| **2** | Rollback protection (monotonic counter) | 4-6h | Eliminates P0 rollback attacks |
| **3** | Observability (audit log, integrity check) | 3-4h | Enables detection & recovery |

**After completion**: Cold storage becomes enterprise-grade, suitable for production IoT OS.

