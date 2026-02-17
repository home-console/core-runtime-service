# STEP 16: Integration Guide - Linux Hardened Vault

## Overview

This guide shows exactly where and how to integrate the new vault modules into your existing codebase.

---

## Part 1: CoreRuntime Initialization

### File: `core/runtime.py` (or wherever CoreRuntime lives)

Add vault hardening at the very start of `CoreRuntime.start()`:

```python
from core.security import VaultHardening, HardeningStatus

class CoreRuntime:
    async def start(self):
        """Start runtime with hardened vault."""
        
        # ✅ Step 1: Enable process-level hardening FIRST
        # This must happen before any other initialization
        try:
            VaultHardening.enable()  # Disables core dumps, ptrace, locks memory
            status = HardeningStatus.report(verbose=True)
            self.logger.info(f"[Runtime] Vault hardening enabled: {status}")
        except RuntimeError as e:
            self.logger.error(f"[Runtime] Vault hardening FAILED: {e}")
            raise  # Fail hard if hardening fails
        
        # ✅ Step 2: Rest of initialization...
        await self.init_storage()
        await self.init_vault()
        await self.init_services()
```

**Why first?**
- Ensures ALL subsequent process memory is protected
- mlockall(MCL_FUTURE) catches new allocations
- No secrets can be created before hardening is enabled

---

## Part 2: Vault Session Creation

### File: `core/vault_manager.py` (new or existing)

Create a vault manager to handle session lifecycle:

```python
from core.security import VaultSession, HardeningStatus, SecretAccessDenied
from core.storage import StorageAdapter
import asyncio
from typing import Optional

class VaultManager:
    """Manages vault session lifecycle."""
    
    def __init__(self, storage: StorageAdapter):
        self._storage = storage
        self._session: Optional[VaultSession] = None
        self._lock = asyncio.Lock()
    
    async def initialize(self, vault_passphrase: str) -> None:
        """Initialize vault with passphrase."""
        async with self._lock:
            if self._session is not None:
                raise RuntimeError("Vault already initialized")
            
            # Create session
            self._session = VaultSession(
                ttl_seconds=900,  # 15 minutes
                argon2_time_cost=2,
                argon2_memory_cost=65536,
                parallelism=4,
            )
            
            # Unlock
            await self._session.unlock(vault_passphrase)
            logger.info("[Vault] Session unlocked successfully")
    
    async def get_session(self) -> VaultSession:
        """Get active session (or raise if not initialized)."""
        if self._session is None:
            raise RuntimeError("Vault not initialized - call initialize() first")
        
        if not self._session.is_unlocked():
            raise RuntimeError("Vault session expired - reinitialize")
        
        return self._session
    
    async def shutdown(self) -> None:
        """Shutdown vault (lock session)."""
        async with self._lock:
            if self._session:
                await self._session.lock()
                self._session = None
                logger.info("[Vault] Session locked")


# Global instance
_vault_manager: Optional[VaultManager] = None

async def init_vault(storage: StorageAdapter, passphrase: str) -> None:
    """Initialize global vault."""
    global _vault_manager
    _vault_manager = VaultManager(storage)
    await _vault_manager.initialize(passphrase)

async def get_vault() -> VaultSession:
    """Get global vault session."""
    if _vault_manager is None:
        raise RuntimeError("Vault not initialized")
    return await _vault_manager.get_session()

async def shutdown_vault() -> None:
    """Shutdown global vault."""
    global _vault_manager
    if _vault_manager:
        await _vault_manager.shutdown()
        _vault_manager = None
```

### Update CoreRuntime

```python
class CoreRuntime:
    async def start(self):
        # ... hardening enabled ...
        
        # Initialize vault
        vault_passphrase = os.environ.get("VAULT_PASSPHRASE")
        if not vault_passphrase:
            raise ValueError("VAULT_PASSPHRASE not set")
        
        await init_vault(self._storage, vault_passphrase)
        self.logger.info("[Runtime] Vault initialized")
    
    async def shutdown(self):
        await shutdown_vault()
        # ... rest of shutdown ...
```

---

## Part 3: SecretStore Integration

### File: `core/secrets/secret_store.py`

Update SecretStore to use vault session and policy:

```python
from core.security import (
    VaultSession,
    SecretAccessPolicy,
    create_default_policy,
    SecureBytes,
    SecretAccessDenied,
)
from core.vault_manager import get_vault
from typing import Optional, Dict, Any

class SecretStore:
    """Secure secret storage with vault-based key derivation."""
    
    def __init__(
        self,
        storage,
        policy: Optional[SecretAccessPolicy] = None,
    ):
        self._storage = storage
        self._policy = policy or create_default_policy()
        self._cache: Dict[str, bytes] = {}  # DEK cache per namespace
    
    async def _get_dek(self, namespace: str) -> bytes:
        """Get data encryption key for namespace (from vault)."""
        vault = await get_vault()
        
        if namespace not in self._cache:
            # Derive fresh from master key
            self._cache[namespace] = vault.derive_namespace_key(namespace)
        
        return self._cache[namespace]
    
    def _check_access(self, plugin_name: str, namespace: str) -> None:
        """Check if plugin can access namespace."""
        if not self._policy.is_allowed(plugin_name, namespace):
            raise SecretAccessDenied(
                f"Plugin '{plugin_name}' not allowed to access '{namespace}'"
            )
    
    async def get(
        self,
        plugin_name: str,
        namespace: str,
        key: str,
    ) -> bytes:
        """Get secret value (with access control)."""
        self._check_access(plugin_name, namespace)
        
        # Get from storage
        value = await self._storage.get(f"{namespace}:{key}")
        
        if value is None:
            return None
        
        # Decrypt if stored encrypted
        dek = await self._get_dek(namespace)
        decrypted = self._decrypt(value, dek)
        
        # Wrap in SecureBytes to prevent accidental logging
        return SecureBytes(decrypted)
    
    async def put(
        self,
        plugin_name: str,
        namespace: str,
        key: str,
        value: bytes,
    ) -> None:
        """Store secret (with access control)."""
        self._check_access(plugin_name, namespace)
        
        # Encrypt with namespace DEK
        dek = await self._get_dek(namespace)
        encrypted = self._encrypt(value, dek)
        
        # Store encrypted
        await self._storage.put(f"{namespace}:{key}", encrypted)
    
    async def delete(
        self,
        plugin_name: str,
        namespace: str,
        key: str,
    ) -> None:
        """Delete secret (with access control)."""
        self._check_access(plugin_name, namespace)
        await self._storage.delete(f"{namespace}:{key}")
    
    def _encrypt(self, plaintext: bytes, dek: bytes) -> bytes:
        """Encrypt with DEK (use your existing cipher)."""
        # E.g., fernet, AES-GCM, etc.
        from cryptography.fernet import Fernet
        cipher = Fernet(base64.b64encode(dek[:32]))
        return cipher.encrypt(plaintext)
    
    def _decrypt(self, ciphertext: bytes, dek: bytes) -> bytes:
        """Decrypt with DEK."""
        from cryptography.fernet import Fernet
        cipher = Fernet(base64.b64encode(dek[:32]))
        return cipher.decrypt(ciphertext)


# Global instance
_secret_store: Optional[SecretStore] = None

async def init_secret_store(
    storage,
    policy: Optional[SecretAccessPolicy] = None,
) -> None:
    """Initialize global secret store."""
    global _secret_store
    _secret_store = SecretStore(storage, policy=policy)

async def get_secret_store() -> SecretStore:
    """Get global secret store."""
    if _secret_store is None:
        raise RuntimeError("SecretStore not initialized")
    return _secret_store
```

### Update CoreRuntime

```python
from core.secrets.secret_store import init_secret_store, get_secret_store

class CoreRuntime:
    async def start(self):
        # ... hardening enabled ...
        # ... vault initialized ...
        
        # Initialize secret store
        await init_secret_store(self._storage)
        self.logger.info("[Runtime] SecretStore initialized with vault")
```

---

## Part 4: Agent/Client Access

### Example: How agents use secrets

```python
from core.secrets.secret_store import get_secret_store

class AgentRuntime:
    async def initialize_credentials(self):
        """Load secrets for this agent."""
        secret_store = await get_secret_store()
        
        # Get OAuth token (will check policy)
        try:
            oauth_token = await secret_store.get(
                plugin_name="my_agent",
                namespace="oauth",
                key="access_token",
            )
            # oauth_token is now a SecureBytes wrapper
            # Accessing it logs [***] instead of actual value
        except SecretAccessDenied:
            self.logger.error("Agent not authorized for oauth namespace")
            raise
```

---

## Part 5: Custom Policy Configuration

### File: `core/config/vault_policy.py`

```python
from core.security import SecretAccessPolicy

def create_custom_policy() -> SecretAccessPolicy:
    """Create custom access policy for your deployment."""
    policy = SecretAccessPolicy()
    
    # Core runtime permissions
    policy.allow("core.runtime", [
        "core.app_key",
        "core.db_password",
        "core.api_key",
    ])
    
    # OAuth provider permissions
    policy.allow("oauth.provider", [
        "oauth.client_secret",
        "oauth.jwt_key",
    ])
    
    # Agent control plane permissions
    policy.allow("agent.control", [
        "agent.master_key",
        "agent.signing_key",
    ])
    
    # Trust store permissions
    policy.allow("trust", [
        "trust.root_cert",
        "trust.intermediate_certs",
    ])
    
    # Marketplace (limited)
    policy.allow("marketplace", [
        "marketplace.api_key",
    ])
    
    return policy


# Usage in CoreRuntime
from core.config.vault_policy import create_custom_policy

class CoreRuntime:
    async def start(self):
        # ... vault initialized ...
        
        # Initialize secret store with custom policy
        policy = create_custom_policy()
        await init_secret_store(self._storage, policy=policy)
```

---

## Part 6: Environment Configuration

### `.env` (for local development)

```bash
# Vault passphrase - CHANGE IN PRODUCTION
VAULT_PASSPHRASE=development-use-strong-passphrase-in-prod

# Vault TTL (seconds)
VAULT_TTL_SECONDS=900

# Logging (SecureBytes wrapping)
LOG_LEVEL=INFO

# Startup
ENABLE_VAULT_HARDENING=true
```

### `docker-compose.yml` (for Docker)

```yaml
core-runtime:
  environment:
    VAULT_PASSPHRASE: ${VAULT_PASSPHRASE}  # From secrets manager
    ENABLE_VAULT_HARDENING: "true"
  
  # Allow mlock capability
  cap_add:
    - IPC_LOCK
  
  # Set memory limit high enough
  mem_limit: 2g
  
  # ulimit for locked memory
  ulimits:
    memlock: -1
```

### Kubernetes (for production)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: core-runtime
spec:
  containers:
  - name: runtime
    image: homeconsole/core-runtime:latest
    
    env:
    - name: VAULT_PASSPHRASE
      valueFrom:
        secretKeyRef:
          name: vault-secrets
          key: passphrase
    
    # Security context for mlock
    securityContext:
      capabilities:
        add:
        - IPC_LOCK
      runAsNonRoot: true
      runAsUser: 1000
    
    # Resource limits
    resources:
      requests:
        memory: "512Mi"
        limits:
          memory: "1Gi"
```

---

## Part 7: Testing the Integration

### File: `tests/test_vault_integration.py`

```python
import pytest
import asyncio
from core.runtime import CoreRuntime
from core.vault_manager import get_vault
from core.secrets.secret_store import get_secret_store
from core.storage import InMemoryStorage

@pytest.mark.asyncio
async def test_vault_integration_flow():
    """Integration test: Runtime → Vault → SecretStore → Secrets."""
    
    # Setup
    storage = InMemoryStorage()
    runtime = CoreRuntime(storage)
    
    # Simulate setting vault passphrase
    import os
    os.environ["VAULT_PASSPHRASE"] = "test-passphrase"
    
    try:
        # Start runtime (enables hardening, initializes vault)
        await runtime.start()
        
        # Get vault session
        vault = await get_vault()
        assert vault.is_unlocked()
        
        # Get secret store
        secret_store = await get_secret_store()
        
        # Store a secret
        await secret_store.put(
            plugin_name="core.runtime",
            namespace="core.app_key",
            key="primary",
            value=b"secret123",
        )
        
        # Retrieve it
        result = await secret_store.get(
            plugin_name="core.runtime",
            namespace="core.app_key",
            key="primary",
        )
        
        # Result is SecureBytes wrapper
        assert result.bytes == b"secret123"
        
        # Cannot access without permission
        with pytest.raises(SecretAccessDenied):
            await secret_store.get(
                plugin_name="unauthorized_plugin",
                namespace="core.app_key",
                key="primary",
            )
    
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_vault_session_expiration():
    """Test TTL-based session expiration."""
    
    import os
    os.environ["VAULT_PASSPHRASE"] = "test-passphrase"
    
    storage = InMemoryStorage()
    runtime = CoreRuntime(storage)
    
    try:
        await runtime.start()
        vault = await get_vault()
        
        # Session should be unlocked
        assert vault.is_unlocked()
        info = vault.get_session_info()
        assert info['ttl_seconds'] == 900
        
        # Simulate TTL expiration (don't actually wait)
        # Just lock manually
        await vault.lock()
        
        # Should now be locked
        assert not vault.is_unlocked()
        
        # Attempting to use should fail
        with pytest.raises(RuntimeError):
            await get_vault()  # Manager checks unlocked status
    
    finally:
        await runtime.shutdown()
```

Run:
```bash
pytest tests/test_vault_integration.py -v -s
```

---

## Part 8: Monitoring and Logs

### Vault Status Endpoint

```python
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.get("/api/v1/vault/status")
async def vault_status():
    """Check vault status (for monitoring)."""
    try:
        from core.security import HardeningStatus
        from core.vault_manager import get_vault
        
        hardening = HardeningStatus.report()
        vault = await get_vault()
        
        return {
            "hardening": hardening,
            "vault": {
                "is_unlocked": vault.is_unlocked(),
                "ttl_remaining": vault._get_seconds_remaining(),
            },
            "status": "ready",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Logs to expect at startup

```
[Runtime] Vault hardening enabled: {
  'hardening_enabled': True,
  'core_dumps_disabled': True,
  'ptrace_disabled': True,
  'memory_locked': True,
}
[Runtime] Vault initialized
[Runtime] SecretStore initialized with vault
[Runtime] System ready
```

---

## Troubleshooting

### Issue: "mlock() failed: errno=12 (ENOMEM)"
**Cause**: Memory limit too low
**Fix**: Increase ulimit
```bash
ulimit -l unlimited
```

### Issue: "Vault session expired"
**Cause**: TTL exceeded (default 900s)
**Fix**: Increase TTL or re-unlock
```python
session = VaultSession(ttl_seconds=3600)  # 1 hour
await session.unlock(passphrase)
```

### Issue: "Plugin not allowed to access namespace"
**Cause**: Access policy denies permission
**Fix**: Add plugin to policy
```python
policy.allow("my_plugin", ["namespace"])
```

### Issue: "Cannot find libc.so.6"
**Cause**: Non-glibc system or libc not found
**Fix**: This is Linux-glibc only; check platform

---

## Security Checklist

- [ ] VaultHardening.enable() called at startup
- [ ] VAULT_PASSPHRASE set securely (not hardcoded)
- [ ] SecretStore initialized before any secret access
- [ ] Access policy configured correctly
- [ ] TTL configured appropriately (900s safe default)
- [ ] Docker/K8s configured with CAP_IPC_LOCK
- [ ] Core dumps disabled on system
- [ ] ptrace disabled on system
- [ ] Logging uses SecureBytes wrapper (prevents repr)
- [ ] Tests passing with vault integration

---

## Next Steps

1. **Testing**: Run full integration tests
   ```bash
   pytest tests/test_vault_integration.py -v
   pytest tests/test_vault_linux_hardening.py -v
   ```

2. **Deployment**: Update Docker/K8s manifests with CAP_IPC_LOCK

3. **Monitoring**: Set up alerts for vault unlock failures

4. **Documentation**: Update API docs to mention SecretAccessDenied exceptions
