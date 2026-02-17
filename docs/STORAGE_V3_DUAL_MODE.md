# Storage v3: Dual-Mode Architecture with Physical Vault Isolation

## Overview

Storage v3 introduces a **dual-mode architecture** that enables physical separation of sensitive vault data from core application storage. This provides:

- **Physical Isolation**: Vault data in a separate database/storage backend
- **Security Hardening**: Vault namespace enforcement prevents accidental core access
- **Backward Compatibility**: Single-mode (default) works exactly like previous versions
- **Flexible Backends**: SQLite or PostgreSQL for both core and vault storage
- **Automated Migration**: Migrate existing data from single to dual mode

## Architecture

### Single Mode (Default, Backward Compatible)

```
┌─────────────────────────┐
│   Core Runtime          │
├─────────────────────────┤
│   StorageManager        │
│   (mode="single")       │
├─────────────────────────┤
│   Core Storage          │
│   (SQLite/PostgreSQL)   │
├─────────────────────────┤
│   ALL DATA:             │
│   - app.config          │
│   - secrets.store       │
│   - oauth.tokens        │
│   - agent.* (all)       │
│   - ...                 │
└─────────────────────────┘
```

**Default behavior:**
- `StorageManager` wraps a single adapter
- All namespaces use the same storage
- Compatible with existing code (no changes required)

### Dual Mode (Storage v3)

```
┌─────────────────────────────────────────────────┐
│              Core Runtime                       │
├─────────────────────────────────────────────────┤
│              StorageManager                     │
│              (mode="dual")                      │
├──────────────────┬──────────────────────────────┤
│                  │                              │
│  Core Storage    │      Vault Storage           │
│  (SQLite/PgSQL)  │      (SQLite/PgSQL)          │
│                  │                              │
│  app.*           │      secrets.store           │
│  runtime.*       │      oauth.tokens            │
│  plugin.*        │      agent.private_keys      │
│  config.*        │      agent.enrollment        │
│  ...             │      ssh.credentials         │
│                  │      vault.*                 │
└──────────────────┴──────────────────────────────┘
```

**Key differences:**
- `StorageManager` manages TWO adapters
- **Namespace enforcement**: Critical vault namespaces MUST use vault storage
- **Auto-routing**: Vault write attempts → vault storage (automatic)
- **Explicit routing**: `manager.set(..., target="vault")` for explicit control
- Separate database files/connections/lifecycle

## Critical Vault Namespaces

The following namespaces are ALWAYS stored in vault storage when in dual mode:

```python
CRITICAL_VAULT_NAMESPACES = [
    "secrets.store",           # Encrypted secrets
    "agent.private_keys",      # Agent SSH/crypto keys
    "agent.enrollment",        # Agent enrollment tokens
    "oauth.tokens",            # OAuth2 access/refresh tokens
    "ssh.credentials",         # SSH login credentials
    "vault",                   # Vault-specific data
]
```

Any write to these namespaces in dual mode:
1. **Auto-routes** to vault storage (if no target specified)
2. **Raises `NamespaceViolationError`** if forced to core storage (target="core")

## Configuration

### Single Mode (Default)

```python
from core.config import Config

config = Config(
    storage_mode="single",           # Default
    storage_type="sqlite",           # or "postgresql"
    db_path="data/runtime.db",
)
```

**Environment variables:**
```bash
# Single mode (defaults)
RUNTIME_STORAGE_MODE=single          # (default)
RUNTIME_STORAGE_TYPE=sqlite
RUNTIME_DB_PATH=data/runtime.db
```

### Dual Mode

```python
from core.config import Config

config = Config(
    storage_mode="dual",
    
    # Core storage
    storage_type="sqlite",
    db_path="data/core.db",
    
    # Vault storage (required in dual mode)
    vault_storage_type="sqlite",
    vault_db_path="data/vault.db",
)
```

**Environment variables:**
```bash
# Dual mode with SQLite for both
RUNTIME_STORAGE_MODE=dual
RUNTIME_STORAGE_TYPE=sqlite
RUNTIME_DB_PATH=data/core.db
RUNTIME_VAULT_STORAGE_TYPE=sqlite
RUNTIME_VAULT_DB_PATH=data/vault.db
```

**Dual mode with mixed backends:**
```bash
# Core: PostgreSQL, Vault: SQLite
RUNTIME_STORAGE_MODE=dual
RUNTIME_STORAGE_TYPE=postgresql
RUNTIME_PG_DSN=postgresql://user:pass@localhost/core_db
RUNTIME_VAULT_STORAGE_TYPE=sqlite
RUNTIME_VAULT_DB_PATH=/secure/vault.db
```

**Dual mode with PostgreSQL for both:**
```bash
RUNTIME_STORAGE_MODE=dual
RUNTIME_STORAGE_TYPE=postgresql
RUNTIME_PG_DSN=postgresql://user:pass@localhost/core_db
RUNTIME_VAULT_STORAGE_TYPE=postgresql
RUNTIME_VAULT_PG_DSN=postgresql://user:pass@vault-server/vault_db
```

## Usage

### Creating StorageManager

```python
from core.config import Config
from core.storage_factory import create_storage_manager

# Load config from environment or constructor
config = Config.from_env()  # Reads RUNTIME_* env vars

# Create manager (handles single vs dual mode automatically)
manager = await create_storage_manager(config)
```

### Single Mode Operations

```python
# All operations use core storage
await manager.set("app.config", "feature_flags", {"enabled": True})
await manager.set("secrets.store", "api_key", {"key": "secret"})

# Both go to the same storage
value = await manager.get("app.config", "feature_flags")
secret = await manager.get("secrets.store", "api_key")
```

### Dual Mode Operations

#### Auto-Routing (Recommended)

```python
# Core namespace → core storage
await manager.set("app.config", "feature_flags", {"enabled": True})

# Vault namespace → vault storage (automatic!)
await manager.set("secrets.store", "api_key", {"key": "secret"})
await manager.set("oauth.tokens", "github", {"token": "ghp_..."})

# Reads are also auto-routed
feature = await manager.get("app.config", "feature_flags")  # From core
secret = await manager.get("secrets.store", "api_key")     # From vault
```

#### Explicit Routing

```python
# Force routing to specific storage
await manager.set(
    "app.config", 
    "setting", 
    {"value": "x"},
    target="core"    # Explicit core storage
)

await manager.set(
    "secrets.store",
    "password",
    {"pwd": "secret"},
    target="vault"   # Explicit vault storage
)

# Get from specific storage
value = await manager.get("app.config", "setting", target="core")
secret = await manager.get("secrets.store", "password", target="vault")
```

#### Error Handling

```python
from core.storage_errors import NamespaceViolationError, StorageConfigurationError

# This raises NamespaceViolationError in dual mode
# (vault namespace cannot use core storage)
try:
    await manager.set("secrets.store", "key", {"val": "x"}, target="core")
except NamespaceViolationError as e:
    print("Cannot write vault namespace to core storage!")
    # Vault storage only: raise e
```

## Migration from Single to Dual Mode

### Step 1: Enable Dual Mode in Config

```bash
# Set environment variables for dual mode
export RUNTIME_STORAGE_MODE=dual
export RUNTIME_VAULT_STORAGE_TYPE=sqlite
export RUNTIME_VAULT_DB_PATH=/path/to/vault.db
```

### Step 2: Run Migration Script

```bash
# Migrate existing data from core to vault storage
cd /path/to/core-runtime-service

# Option 1: Direct Python execution
python -m core.storage_migrate

# Option 2: As module
python -c "
import asyncio
from core.config import Config
from core.storage_migrate import migrate_to_dual_mode

config = Config.from_env()
count = asyncio.run(migrate_to_dual_mode(config))
print(f'Migrated {count} records to vault storage')
"
```

**Migration output example:**
```
INFO - Starting migration to dual-mode storage (core: sqlite, vault: sqlite)
INFO - Found 3 namespaces in core storage
INFO - Found 2 vault namespaces to migrate: ['secrets.store', 'oauth.tokens']
INFO - Migrating namespace 'secrets.store': 5 records
INFO -   ✓ secrets.store: copied=5, deleted=5, errors=0
INFO - Migrating namespace 'oauth.tokens': 2 records
INFO -   ✓ oauth.tokens: copied=2, deleted=2, errors=0
INFO - Migration complete: 7 total records migrated to vault storage
```

### Step 3: Check Migration Status

```python
from core.storage_migrate import check_migration_status
from core.config import Config
import asyncio

async def check():
    config = Config.from_env()
    core_count, vault_count = await check_migration_status(config)
    print(f"Core vault records: {core_count}")
    print(f"Vault storage records: {vault_count}")
    if core_count == 0:
        print("✓ Migration complete!")

asyncio.run(check())
```

### Step 4: Verify and Start

```bash
# Run validation
python scripts/validate_runtime.py

# If validation passes (exit code 0), start runtime
python main.py
```

## Runtime Integration

### In main.py

```python
from core.storage_factory import create_storage_manager
from core.config import Config

async def main():
    config = Config.from_env()
    
    # Create manager (works for both single and dual mode)
    storage_manager = await create_storage_manager(config)
    
    # Pass to CoreRuntime
    runtime = CoreRuntime(
        storage_manager=storage_manager,  # StorageManager instance
        config=config,
    )
    
    # Startup proceeds normally
    await runtime.startup()
```

### In SecretStore Integration

```python
from core.security.secret_store import SecretStore

# SecretStore MUST use vault storage in dual mode
async def create_secret_store(manager: StorageManager):
    # Get vault storage (same as core in single mode)
    vault_storage = manager.get_vault()
    
    secret_store = SecretStore(storage=vault_storage)
    await secret_store.initialize()
    return secret_store
```

## Security Invariants

### Physical Isolation

- **Vault storage never uses core adapter**: `manager.get_vault()` returns separate adapter
- **Namespace enforcement**: Vault namespaces cannot be written to core storage
- **Separate lifecycle**: Core and vault adapters initialized/closed independently

### Namespace Encryption

Even in single mode, vault namespaces should use `SecretStore` for encryption:

```python
from core.storage.secret_store import SecretStore

# Single mode: use SecretStore for vault namespaces
secret_store = SecretStore(storage=storage_adapter)

# Encrypts/decrypts with AES-256-GCM
await secret_store.set_secret("oauth.tokens", "github", token_dict)
token = await secret_store.get_secret("oauth.tokens", "github")
```

### Dual Mode Security Benefits

1. **Separate Access Control**: Vault storage can use different auth/permissions
2. **Different Backends**: Vault on encrypted volume, core on standard storage
3. **Namespace Enforcement**: API prevents accidental core storage access
4. **Audit Trail**: Separate logs for core vs vault operations (via adapter logging)

## Testing

Run the comprehensive test suite:

```bash
# Run Storage v3 tests
pytest tests/test_storage_v3_dual_mode.py -v

# Specific test class
pytest tests/test_storage_v3_dual_mode.py::TestStorageManagerInitialization -v

# Specific test
pytest tests/test_storage_v3_dual_mode.py::TestNamespaceEnforcement::test_vault_namespace_auto_routing_to_vault -v
```

## Backward Compatibility

### Existing Code Continues to Work

```python
# Old code using single adapter (still works!)
from adapters.sqlite_adapter import SQLiteAdapter

adapter = SQLiteAdapter("data/runtime.db")
await adapter.set("app.config", "setting", {"val": "x"})
```

### StorageManager Wraps Old Code

```python
from core.storage_manager import StorageManager

# Wrap existing adapter for new StrorageManager API
manager = StorageManager(core_storage=adapter, mode="single")
await manager.set("app.config", "setting", {"val": "x"})  # Works!
```

### Gradual Adoption

1. **Phase 1**: Deploy with `storage_mode="single"` (no changes)
2. **Phase 2**: Update code to use `StorageManager` API
3. **Phase 3**: Enable dual mode when ready
4. **Phase 4**: Run migration script

## Performance Considerations

### Single Mode (Default)

- **No change** from previous versions
- Single database connection pool
- Minimal overhead (StorageManager is thin wrapper)

### Dual Mode

- **Two concurrent adapters**: Core and Vault handling parallel writes
- **Separate connection pools**: No contention between core and vault
- **Recommended setup**:
  - Core: SQLite (faster for local dev)
  - Vault: PostgreSQL (production-grade for secrets)
  - Or both PostgreSQL for consistent performance

### Optimization Tips

```bash
# High-throughput dual mode
RUNTIME_STORAGE_MODE=dual
RUNTIME_STORAGE_TYPE=postgresql
RUNTIME_PG_DSN=postgresql://user:pass@localhost/core_db  # Connection pool
RUNTIME_VAULT_STORAGE_TYPE=postgresql
RUNTIME_VAULT_PG_DSN=postgresql://user:pass@vault-server/vault_db  # Dedicated connection pool
```

## Troubleshooting

### Configuration Validation Errors

```python
# Error: storage_mode='dual' requires vault_storage_type
# Fix: Set RUNTIME_VAULT_STORAGE_TYPE env var

# Error: vault_storage_type='sqlite' requires vault_db_path
# Fix: Set RUNTIME_VAULT_DB_PATH env var
```

### NamespaceViolationError During Migration

```python
# This shouldn't happen, but if it does:
from core.storage_migrate import migrate_to_dual_mode

# Check what records are in vault namespaces in core storage
config = Config.from_env()

# Run migration with DEBUG logging
import logging
logging.basicConfig(level=logging.DEBUG)

count = await migrate_to_dual_mode(config)
```

### Vault Storage Not Created

```bash
# Ensure vault directory exists and is writable
mkdir -p /path/to/vault
chmod 700 /path/to/vault

# Verify SQLite can create the database
touch /path/to/vault/vault.db
chmod 600 /path/to/vault/vault.db
```

## References

- [StorageManager API](../core/storage_manager.py)
- [Storage V3 Exceptions](../core/storage_errors.py)
- [Storage Factory](../core/storage_factory.py)
- [Migration Script](../core/storage_migrate.py)
- [Test Suite](../tests/test_storage_v3_dual_mode.py)
- [Config](../core/config.py)
