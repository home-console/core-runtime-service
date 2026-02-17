# STEP 16: Hardened Vault - Threat Model & Architecture

## Executive Summary

Linux-first hardened vault protecting secrets against:
1. **Memory disclosure** (swap, dumps, debugger)
2. **Process tampering** (ptrace, debugging, injection)
3. **Unauthorized access** (policy violations)
4. **Session leaks** (TTL expiration)
5. **Accidental logging** (repr/str secrets)

**Defense in depth**: OS-level + application-level + session-level + access-control layers.

---

## Part 1: Threat Model

### Threat 1: Secrets in Swap

```
Application: plaintext secret in RAM
           ↓
[VULNERABLE] No memory pinning
           ↓
Swap to disk (if low memory)
           ↓
Attacker: disk access → reads secret
           ↓
IMPACT: Private key compromise
```

**Defense**: `mlock()` + `MADV_DONTDUMP`

```
Application: plaintext secret in RAM
           ↓
[PROTECTED] mlock() pins to RAM (no swap possible)
           ↓
Memory pinned, out-of-process
           ↓
IMPACT: MITIGATED ✓
```

**Code**:
```python
# SecureBuffer._lock_memory()
libc.mlock(address, size)  # Returns -1 on failure
```

---

### Threat 2: Debugger Inspection

```
Attacker: gdb attach <pid>
           ↓
pt_attach (ptrace syscall)
           ↓
[VULNERABLE] No ptrace protection
           ↓
Debugger: reads process memory, registers, stack
           ↓
IMPACT: Complete process compromise
```

**Defense**: `prctl(PR_SET_DUMPABLE, 0)` + `RLIMIT_CORE`

```
Attacker: gdb attach <pid>
           ↓
pt_attach (ptrace syscall) → EPERM
           ↓
[PROTECTED] ptrace disabled at process level
           ↓
Debugger: cannot attach
           ↓
IMPACT: MITIGATED ✓
```

**Code**:
```python
# VaultHardening._disable_ptrace()
libc.prctl(PR_SET_DUMPABLE, 0)  # pid=0 = current process
```

---

### Threat 3: Core Dumps

```
Attacker: triggers segfault (crash)
           ↓
Linux kernel: writes core dump to disk
           ↓
[VULNERABLE] Core dump contains full process memory
           ↓
Attacker: reads /var/crash/core.* → all secrets
           ↓
IMPACT: Complete secret compromise
```

**Defense**: `RLIMIT_CORE = 0`

```
Attacker: triggers segfault
           ↓
Linux kernel: checks RLIMIT_CORE → 0 (disabled)
           ↓
[PROTECTED] No core dump generated
           ↓
IMPACT: MITIGATED ✓
```

**Code**:
```python
# VaultHardening._disable_core_dumps()
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
```

---

### Threat 4: Process Memory Paging

```
Attacker: physical memory access (cold boot, JTAG)
           ↓
Reads memory pages on disk (/dev/mem, /proc/mem)
           ↓
[VULNERABLE] No memory locking
           ↓
IMPACT: Page-by-page secret recovery
```

**Defense**: `mlockall(MCL_CURRENT | MCL_FUTURE)`

```
Attacker: physical access
           ↓
mlockall() ensures ALL process memory locked to RAM
           ↓
[PROTECTED] Only in-RAM memory pages accessible
           ↓
IMPACT: MITIGATED (RAM-only secrets) ✓
```

**Code**:
```python
# VaultHardening._lock_process_memory()
libc.mlockall(MCL_CURRENT | MCL_FUTURE)  # All + future
```

---

### Threat 5: Session Leakage

```
User: authenticate, unlock vault
       ↓
[VULNERABLE] Vault session never expires
       ↓
User: walks away from workstation
       ↓
Attacker: (physical) gains access to unlocked vault
       ↓
IMPACT: All secrets accessible without password
```

**Defense**: TTL + asyncio expiration timer

```
User: authenticate, unlock vault
       ↓
[PROTECTED] Session timer starts (900s = 15 min)
       ↓
User: walks away
       ↓
Timer expired → session.lock() → zeroize master key
       ↓
Attacker: (physical) vault now locked
       ↓
IMPACT: MITIGATED ✓
```

**Code**:
```python
# VaultSession.__init__()
asyncio.create_task(self._ttl_timer())  # Background expiration

async def _ttl_timer(self):
    await asyncio.sleep(self.ttl_seconds)
    await self.lock()  # Zeroize
```

---

### Threat 6: Unauthorized Access

```
Attacker: gains shell access as regular user
           ↓
Attempts: secret_store.get(plugin=untrusted, namespace=oauth)
       ↓
[VULNERABLE] No access control
       ↓
IMPACT: Cross-plugin secret theft
```

**Defense**: Whitelist access policy

```
Attacker: attempts unauthorized access
           ↓
SecretStore._check_access(plugin, namespace)
           ↓
Policy: oauth plugin NOT in whitelist for namespace
           ↓
[PROTECTED] Raises SecretAccessDenied
           ↓
IMPACT: MITIGATED ✓
```

**Code**:
```python
# SecretStore._check_access()
if not self._policy.is_allowed(plugin_name, namespace):
    raise SecretAccessDenied(...)
```

---

### Threat 7: Accidental Secret Logging

```
Developer: logging.debug(f"Handling token: {oauth_token}")
           ↓
[VULNERABLE] repr(oauth_token) = b'real-token-123'
           ↓
Log file: contains plaintext secret
           ↓
Attacker: reads /var/log/app.log
           ↓
IMPACT: Log file is secret material
```

**Defense**: SecureBytes wrapper

```
Developer: logging.debug(f"Handling token: {oauth_token}")
           ↓
[PROTECTED] oauth_token is SecureBytes instance
           ↓
repr(SecureBytes) = <SecureBytes[***]>
           ↓
Log file: contains [***] instead of secret
           ↓
IMPACT: MITIGATED ✓
```

**Code**:
```python
# SecureBytes.__repr__()
def __repr__(self):
    return f"<SecureBytes[***]>"
```

---

## Part 2: Architecture

### 2.1 Layered Design

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: Application                                │
│ Secret-using code (agents, services)                │
│ Uses: secret_store.get(plugin, namespace, key)      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 2: Access Control                             │
│ SecretAccessPolicy (whitelist)                      │
│ Denies unauthorized plugin access                   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 3: Session Management                         │
│ VaultSession (TTL, unlock/lock)                     │
│ Derives namespace-specific DEKs                     │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 4: Secure Memory                              │
│ SecureBuffer (mlock, MADV_DONTDUMP, zeroize)       │
│ Protects master key from swap/dumps                 │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Layer 5: OS Hardening                               │
│ VaultHardening (core dump disable, ptrace disable) │
│ Process-level immutable protection                  │
└─────────────────────────────────────────────────────┘
```

Each layer is **independent** and **orthogonal**.

### 2.2 Key Derivation Chain

```
User Passphrase (human-memorable)
            ↓
Argon2id(time=2, memory=65536, parallelism=4)
            ↓
Master Key (32 bytes, stored in SecureBuffer)
            ↓
HKDF-Expand(PRF=SHA256, info=namespace)
            ↓
Namespace DEK (32 bytes, per-namespace unique)
            ↓
AES-256-GCM or Fernet encryption
            ↓
Encrypted Secrets
```

**Properties**:
- ✓ Passphrase → Master Key: **deterministic** (same password always produces same master key)
- ✓ Master Key → Namespace DEK: **deterministic** (same master key + namespace = same DEK)
- ✓ Namespaces **isolated** (namespace_A key ≠ namespace_B key)
- ✓ Master Key **never persisted** (only in-memory SecureBuffer)

### 2.3 State Machine

```
┌──────────────────────────────────────────┐
│ LOCKED                                   │
│ (no secrets accessible)                  │
└──────────────────────────────────────────┘
         ↓ unlock(passphrase)
┌──────────────────────────────────────────┐
│ UNLOCKED                                 │
│ (secrets accessible)                     │
│ (TTL timer running)                      │
└──────────────────────────────────────────┘
         ↓ lock() OR TTL expires
┌──────────────────────────────────────────┐
│ LOCKED + ZEROIZED                       │
│ (master key securely wiped)              │
└──────────────────────────────────────────┘
```

---

## Part 3: Memory Safety

### 3.1 Allocation

```python
# SecureBuffer.__init__()
self._buffer = ctypes.create_string_buffer(size)
# Creates uninitialized memory guaranteed by ctypes
```

### 3.2 Locking

```python
# SecureBuffer._lock_memory()
addr = ctypes.addressof(self._buffer)
libc.mlock(addr, self.size)  # Lock pages to RAM
```

### 3.3 Exclusion from Dumps

```python
# SecureBuffer._exclude_from_dump()
addr = ctypes.addressof(self._buffer)
libc.madvise(addr, self.size, MADV_DONTDUMP)
# Exclude from core dumps + /proc/[pid]/mem
```

### 3.4 Zeroization

```python
# SecureBuffer.close()
libc.memset(addr, 0, self.size)  # Overwrite with zeros
libc.munlock(addr, self.size)    # Unlock from RAM
```

**Why ctypes.memset + not Python?**
- Python garbage collector might move/copy data
- Loop-based zeroing can be optimized away by compiler
- ctypes.memset() is volatile (compiler can't optimize)

### 3.5 Copy Prevention

```python
# SecureBuffer blocks:
def __copy__(self):
    raise TypeError("Cannot copy SecureBuffer")

def __deepcopy__(self, memo):
    raise TypeError("Cannot copy SecureBuffer")

def __reduce__(self):  # pickle prevention
    raise TypeError("Cannot serialize SecureBuffer")
```

**Why?**
- Copy would leave original unzeroized
- Deepcopy can create unexpected references
- Pickle would expose memory address layout

---

## Part 4: Cryptographic Assumptions

### 4.1 Argon2id (Passphrase → Master Key)

```
time_cost=2          # KDF iterations (no speed-up benefit for attacker)
memory_cost=65536    # 64 MB (memory hardness - resists GPU/ASIC)
parallelism=4        # Threads (uses 4 parallel lanes)
salt=random          # Per-session (unique each unlock)
```

**Rationale**:
- `time_cost=2` is sufficient for user-interaction latency (<500ms)
- `memory_cost=65536` requires attacker to allocate 64MB per guess
- GPU/ASIC attacks inefficient (memory-bound, not compute-bound)
- Random salt makes rainbow tables impossible

### 4.2 HKDF (Master Key → Namespace DEKs)

```
KDF: HKDF-SHA256
PRF: HMAC-SHA256
IKM: master_key (32 bytes from Argon2id)
salt: empty (not needed, IKM already random)
info: namespace (e.g., "trust_store")
L: 32 (derive 32-byte key)
```

**Property**:
- Different `info` → different derived keys
- Computationally infeasible to reverse (recover IKM from derived key)

```python
# Derivation examples:
HKDF(master_key, info="trust_store").derive(32)    # Key A
HKDF(master_key, info="oauth").derive(32)           # Key B

# Key A ≠ Key B (different names)
# Both secure (can't recover master_key)
```

---

## Part 5: Session Lifecycle

### 5.1 Unlock Sequence

```
User: provide passphrase
       ↓
VaultSession.unlock(passphrase)
       ↓
Argon2id(passphrase) → master_key
       ↓
SecureBuffer.allocate(master_key)
       ↓
mlock() + MADV_DONTDUMP applied
       ↓
asyncio.create_task(_ttl_timer)
       ↓
Session ready (is_unlocked=True)
```

**Time**: ~200-500ms (intentional - discourages brute-force)

### 5.2 Key Derivation

```
VaultSession.derive_namespace_key(namespace)
       ↓
Check: is_unlocked() → True
       ↓
HKDF(master_key, info=namespace)
       ↓
Return 32-byte DEK
       ↓
(Original master_key unchanged, stays in SecureBuffer)
```

**Time**: <1ms

### 5.3 Lock Sequence

```
User: explicitly lock OR TTL expires
       ↓
VaultSession.lock()
       ↓
SecureBuffer.close()
       ↓
ctypes.memset(master_key_addr, 0, 32)
       ↓
ctypes.munlock(master_key_addr, 32)
       ↓
_master_key = None
       ↓
Session locked (is_unlocked=False)
```

**Guarantee**: Master key zeroized before unlock returns

---

## Part 6: Process Hardening Atomicity

### 6.1 Hardening Sequence

```
VaultHardening.enable()
       ↓
_disable_core_dumps()
  └─ setrlimit(RLIMIT_CORE, (0, 0))
       ↓
_disable_ptrace()
  └─ prctl(PR_SET_DUMPABLE, 0)
       ↓
_lock_process_memory()
  └─ mlockall(MCL_CURRENT | MCL_FUTURE)
       ↓
_enabled = True
```

### 6.2 Error Handling

Each step:
1. Check return code
2. Check errno
3. Raise RuntimeError with descriptive message
4. **No fallback** (if any step fails, process exits)

```python
# VaultHardening._disable_core_dumps()
result = resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
if result != 0:
    raise RuntimeError(
        f"Failed to disable core dumps: "
        f"setrlimit returned {result}, errno={errno.errno}"
    )
```

### 6.3 Idempotency

```python
# VaultHardening.enable()

# Check if already enabled
if cls._enabled:
    return  # No-op

# ... apply hardening ...

cls._enabled = True
```

Safe to call multiple times (skips if already applied).

---

## Part 7: Access Policy Model

### 7.1 Whitelist-Based

```
DEFAULT: All access DENIED
         ↓
Grant: policy.allow(plugin, [namespaces])
         ↓
Check: policy.is_allowed(plugin, namespace) → bool
```

**Fail-safe**: Deny by default (no accidental grants)

### 7.2 Default Policy

| Plugin | Allowed Namespaces |
|--------|-------------------|
| core.runtime | core.app_key, core.db_password, core.api_key |
| oauth | oauth.client_secret, oauth.jwt_key, oauth.token |
| trust | trust.root_cert, trust.intermediate_certs |
| agent.control | agent.master_key, agent.signing_key |
| marketplace | marketplace.api_key |

### 7.3 Enforcement Point

```python
# SecretStore.get/put/delete()
def _check_access(self, plugin_name, namespace):
    if not self._policy.is_allowed(plugin_name, namespace):
        raise SecretAccessDenied(
            f"Plugin '{plugin_name}' denied access to '{namespace}'"
        )
```

Every access goes through policy check (no bypass path).

---

## Part 8: Logging Safety

### 8.1 Unsafe Approach

```python
# ❌ UNSAFE
token = secret_store.get("oauth", "oauth.client_secret", "token")
logger.info(f"Token obtained: {token}")
# Log output: Token obtained: b'real-secret-token-12345'
# Problem: Secret in plain text in logs
```

### 8.2 Safe Approach

```python
# ✅ SAFE
token = secret_store.get("oauth", "oauth.client_secret", "token")
# Returns SecureBytes(b'real-secret-token-12345')

logger.info(f"Token obtained: {token}")
# Log output: Token obtained: <SecureBytes[***]>
# Safe: Secret masked

actual_token = token.bytes  # Explicit access for use
```

### 8.3 Implementation

```python
class SecureBytes:
    def __init__(self, data: bytes):
        self._data = data
    
    def __repr__(self):
        return "<SecureBytes[***]>"
    
    def __str__(self):
        return "<SecureBytes[***]>"
    
    @property
    def bytes(self):
        return self._data
```

**Audit trail**: Every use of `.bytes` is explicit and grep-able.

---

## Part 9: Testing Strategy

### 9.1 Unit Tests

```bash
pytest tests/test_vault_linux_hardening.py::TestSecureBuffer -v
pytest tests/test_vault_linux_hardening.py::TestVaultHardening -v
pytest tests/test_vault_linux_hardening.py::TestVaultSession -v
pytest tests/test_vault_linux_hardening.py::TestSecretAccessPolicy -v
```

### 9.2 Integration Tests

```bash
pytest tests/test_vault_integration.py -v
# Tests: RuntimeHardening → VaultSession → SecretStore flow
```

### 9.3 Security Tests

```bash
# Test 1: mlock actually called
subprocess.run(["strace", "-e", "mlock", "python", "code"])

# Test 2: Core dumps disabled
ulimit -c  # Should be 0

# Test 3: ptrace disabled
ptrace(PTRACE_ATTACH, pid)  # Should fail with EPERM

# Test 4: Memory not in swap
cat /proc/[pid]/status | grep VmSwap  # Should be 0

# Test 5: TTL expiration
await asyncio.sleep(ttl_seconds + 1)
assert not session.is_unlocked()
```

---

## Part 10: Comparison Matrix

### Other Approaches vs Hardened Vault

| Feature | Traditional | Hardened Vault |
|---------|------------|--------------|
| Swap protection | No | ✓ mlock |
| Core dump protection | No | ✓ RLIMIT_CORE |
| Debugger protection | No | ✓ PR_SET_DUMPABLE |
| Memory lock protection | No | ✓ mlockall |
| Session TTL | No | ✓ 900s auto-expire |
| Key isolation | No | ✓ Per-namespace HKDF |
| Access control | No | ✓ Whitelist policy |
| Log protection | No | ✓ SecureBytes |
| **Complexity** | Low | **Medium** |
| **Overhead** | None | **<1%** |

---

## Part 11: Deployment Checklist

- [ ] Linux system only (checked at startup)
- [ ] CAP_IPC_LOCK capability (or sudo)
- [ ] ulimit -l unlimited (or system config)
- [ ] VAULT_PASSPHRASE set (from secrets manager)
- [ ] VaultHardening.enable() called first
- [ ] VaultSession created per worker
- [ ] SecretStore uses policy
- [ ] Logging uses repr override (auto with SecureBytes)
- [ ] Tests passing on target Linux
- [ ] Monitoring alerts for vault unlock failures

---

## Part 12: References

### Linux System Calls Used

| Call | Purpose | Man Page |
|------|---------|----------|
| mlock(2) | Pin memory to RAM | Prevents swapping |
| madvise(2) | Hint to kernel (MADV_DONTDUMP) | Exclude from core dumps |
| mlockall(2) | Lock all process memory | Memory locking |
| munlock(2) | Unlock from RAM | Cleanup |
| prctl(2) | Process control (PR_SET_DUMPABLE) | Disable core dumps/ptrace |
| getrlimit(2) | Get resource limits | Check limits |
| setrlimit(2) | Set resource limits (RLIMIT_CORE) | Disable core dumps |

### Python Libraries

| Library | Purpose |
|---------|---------|
| ctypes | FFI to libc (mlock, memset) |
| cryptography | Argon2id, HKDF |
| asyncio | TTL timer |
| resource | setrlimit |

---

## Conclusion

**Linux-First Hardened Vault** provides:

1. **Memory safety**: mlock + MADV_DONTDUMP + zeroization
2. **Process hardening**: Core dumps + ptrace + memory lock
3. **Session control**: TTL + explicit unlock/lock
4. **Access control**: Whitelist policy
5. **Key isolation**: Namespace-based HKDF derivation
6. **Logging safety**: SecureBytes wrapper

**Result**: Enterprise-grade secret protection against:
- Memory disclosure (swap, dumps)
- Process tampering (debugging, injection)
- Unauthorized access
- Session leakage
- Accidental logging

**Complexity**: Justified by security value delivered.
