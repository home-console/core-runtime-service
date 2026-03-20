# Stage 1 Architecture Audit

## Scope

- Find runtime imports from `modules` inside `core/` and `plugins/`.
- Classify them by subsystem.
- Mark criticality.
- Keep this stage read-only for business logic.

## CLI Check

```bash
rg "from modules\.|import modules\." core plugins
```

## Summary

- Total direct `modules` imports in `core/` and `plugins/`: 24 files.
- Highest-risk area: `core/runtime/runtime.py` and the plugin subsystem shims in `core/plugins/*`.
- The majority of storage imports are compatibility wrappers around `modules.storage.*`.
- Plugins have two direct runtime imports into `modules`.

## Grouped Findings

### Plugin system

- `core/plugin_schema.py` -> `modules.plugins.schema` -> schema validation re-export -> HIGH
- `core/plugin_isolation.py` -> `modules.plugins.isolation` -> isolation proxy re-export -> HIGH
- `core/plugins/__init__.py` -> `modules.plugins.*` -> compatibility package for plugin subsystem -> CRITICAL
- `core/plugins/manager.py` -> `modules.plugins.manager` -> plugin manager re-export -> CRITICAL
- `core/kernel/plugin_sandbox.py` -> `modules.plugins.isolation` -> sandbox proxy wiring -> CRITICAL

### Storage

- `core/storage_crypto.py` -> `modules.storage.crypto` -> hash / canonical JSON helpers -> HIGH
- `core/storage_manager.py` -> `modules.storage.manager` -> storage manager re-export -> HIGH
- `core/storage_port.py` -> `modules.storage.port` -> storage port re-export -> HIGH
- `core/storage_abstraction.py` -> `modules.storage.abstraction` -> storage backend interface re-export -> HIGH
- `core/storage.py` -> `modules.storage.storage` -> storage API re-export -> HIGH
- `core/storage_errors.py` -> `modules.storage.errors` -> storage error re-export -> HIGH
- `core/storage_exceptions.py` -> `modules.storage.exceptions` -> storage exception re-export -> HIGH
- `core/storage_mirror.py` -> `modules.storage.mirror` -> mirror wrapper re-export -> HIGH
- `core/storage_migrate.py` -> `modules.storage.migrate` -> migration helpers re-export -> HIGH
- `core/adapters/storage_factory.py` -> `modules.storage.*` -> adapter assembly depends on storage module implementations -> HIGH
- `core/adapters/postgresql_adapter.py` -> `modules.storage.exceptions` -> map backend errors to storage errors -> MEDIUM
- `core/adapters/sqlite_adapter.py` -> `modules.storage.exceptions` -> map backend errors to storage errors -> MEDIUM
- `core/security/secret_store_adapter.py` -> `modules.storage` -> backend adapter for SecretStore -> HIGH
- `core/audit/binder.py` -> `modules.storage.secure` -> tamper-evident audit persistence -> HIGH

### Policy / security

- `core/security/mfa/service.py` -> `modules.credentials.abuse_detection` -> MFA self-defense hook -> MEDIUM

### Execution / operations

- `plugins/oauth_yandex/plugin.py` -> `modules.operations.handlers` -> best-effort oauth refresh registration -> MEDIUM

### Other

- `core/runtime/runtime.py` -> `modules.agent.*` -> agent control plane bootstrap inside runtime -> CRITICAL
- `core/runtime/runtime_context.py` -> `modules.storage` -> runtime context storage handle -> HIGH
- `plugins/yandex_smart_home/sync/device_status.py` -> `modules.devices.services` -> online/offline device lookup -> MEDIUM

## Temporary Workarounds

- Keep compatibility shims in `core/*` for storage and plugin package exports until stage 2 migrates call sites.
- Route plugin callbacks through `service_registry` or `operations` adapters instead of direct `modules` imports.
- For runtime agent bootstrap, keep the current wiring isolated behind a thin adapter until `KernelContext` exists.
- For `core/security/mfa/service.py`, keep the dependency behind `TYPE_CHECKING` or a narrow injected adapter if the runtime path can be removed later.

## TODO for Stage 2

- `core/runtime/runtime.py` -> remove direct agent bootstrap -> move to `KernelContext` and module registration.
- `core/plugins/__init__.py` / `core/plugins/manager.py` / `core/plugin_schema.py` / `core/plugin_isolation.py` / `core/kernel/plugin_sandbox.py` -> replace compatibility imports with core-owned plugin contracts.
- `core/storage*.py` -> retire compatibility exports after modules-owned storage contracts are canonical.
- `core/adapters/storage_factory.py` -> decouple adapter assembly from `modules.storage` internals.
- `plugins/oauth_yandex/plugin.py` and `plugins/yandex_smart_home/sync/device_status.py` -> move to public service access instead of direct `modules` imports.