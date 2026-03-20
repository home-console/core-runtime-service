# Architecture Migration Map (Finalization Plan)

## Goals
- Убрать плоский `core/*.py` монолит и перевести код на канонические package imports.
- Сохранить 100% backward compatibility на переходный период через thin wrappers.
- Завершить миграцию в 2 этапа: `imports first`, затем `wrappers removal`.

## Canonical Layers
- `core/kernel`: runtime lifecycle, module/plugin orchestration, boot contracts
- `core/platform`: infrastructure services (security, storage, http contracts, remote, eventing)
- `core/contracts`: stable interfaces/protocols/schemas/errors
- `core/shared`: context, logging helpers, util primitives

## Migration Principles
1. Новые импорты только из канонических пакетов.
2. Legacy wrappers в `core/*.py` остаются до полного перевода потребителей.
3. Тесты можно мигрировать отдельным батчем после стабилизации runtime imports.
4. Каждый батч завершается регрессионными тестами.

## Current Status (done)
- `core/runtime.py` -> `core/runtime/*` + compat wrapper
- `core/secure_storage.py` -> `core/secure_storage/*` + compat wrapper
- `core/capability_registry.py` -> `core/capability/*` + compat wrapper
- `core/http_registry.py` -> `core/http/*` + compat wrapper
- `core/service_registry.py` -> `core/service/*` + compat wrapper
- `core/dependency_resolver.py` -> `core/dependency/*` + compat wrapper
- `core/module_manager.py` -> `core/module/*` + compat wrapper
- `core/policy_engine.py` -> `core/policy/*` + compat wrapper
- Wave C warnings enabled for legacy wrapper imports
- Storage canonical import surface introduced as `core/storage_layer/*` (naming-safe alternative to `core/storage/*`)
- Trust migration bootstrap added: `core/security/trust/legacy_crypto.py` bridge for crypto trust stack

## Full Path Map (old -> canonical)

### Registry/Manager wrappers
- `core.service_registry` -> `core.service`
- `core.http_registry` -> `core.http`
- `core.capability_registry` -> `core.capability`
- `core.module_manager` -> `core.module`
- `core.dependency_resolver` -> `core.dependency`

### Security domain consolidation
- `core/security.py` -> `core/security/` split into:
  - `core/security/token_encryption.py`
  - `core/security/log_sanitizer.py`
  - `core/security/csrf.py`
  - `core/security/rate_limit.py`
  - `core/security/vault_session.py`
  - `core/security/vault_hardening.py`
  - `core/security/__init__.py` as canonical API
- Temporary wrapper: `core/security.py` reexports from `core.security`

### Trust unification (single source of truth)
- Canonical target: `core/security/trust/*`
- Keep compatibility facade from `core/trust/*` during transition:
  - `core/trust/__init__.py` reexport -> `core.security.trust`
  - `core/trust/signature.py` facade (if needed)
  - `core/trust/trust_store.py` facade (if needed)
  - `core/trust/verifier.py` facade (if needed)
- Stage 1 (done): migrated first production call sites to security namespace bridge (`modules/marketplace/installer.py`, `core/capability/security.py`).
- Stage 2 (done): migrated trust model tests to security namespace bridge (`tests/test_trust_model.py`).
- Stage 3 (done): direct production/test imports migrated; `core/trust/*` now compatibility wrappers over security-domain implementation.
- Stage 4 (in progress): keep compatibility wrappers through transition window, then remove per release plan.

### Storage consolidation
- Primary constraint: `core/storage.py` file name conflicts with `core/storage/` package in Python import resolution.
- Canonical migration path uses `core/storage_layer/__init__.py` as stable API surface.
- Stage 1 (done): moved production + runtime/context/exceptions + tests/scripts imports to `core.storage_layer`.
- Stage 2 (in progress): keep `core/storage*.py` internals on direct imports to avoid cycles while `storage_layer` remains the canonical external surface.

### Policy/Authz
- `core/policy_engine.py` -> `core/policy/engine.py`
- `core/policy/__init__.py` as canonical API
- `core/acl.py` -> `core/policy/acl.py`
- Temporary wrapper: `core/policy_engine.py` reexports from `core.policy`
- Temporary wrapper: `core/acl.py` reexports from `core.policy`

### Remote
- `core/remote_executor.py` -> `core/remote/executor.py`
- `core/remote_provider.py` -> `core/remote/provider.py`
- `core/remote_executor_interface.py` -> `core/remote/interface.py`
- `core/remote/__init__.py` canonical export

## Import Migration Waves

### Wave A (start now): runtime + production code imports
- Replace in runtime/core/modules/plugins/adapters/main/examples:
  - `from core.http_registry import ...` -> `from core.http import ...`
  - `from core.module_manager import ...` -> `from core.module import ...`
  - `from core.service_registry import ...` -> `from core.service import ...`
  - `from core.dependency_resolver import ...` -> `from core.dependency import ...`
  - `from core.capability_registry import ...` -> `from core.capability import ...`

### Wave B: test imports
- Migrate tests to canonical imports after Wave A stability.

### Wave C: wrapper deprecation hardening
- Add explicit deprecation comments and removal schedule.

### Wave D: wrapper removal
- Remove `core/*_registry.py`, `core/module_manager.py`, `core/dependency_resolver.py`, `core/service_registry.py` after zero usage in repo.

## Acceptance Criteria
- `rg` shows no production imports from legacy wrappers.
- Regression tests pass for core runtime suites.
- Full test suite passes or only known unrelated failures remain.
- Wrappers kept only for external backward compatibility until release cutoff.

## Release Plan
- Release N: canonical imports + wrappers retained
- Release N+1: wrappers emit warnings in docs/changelog
- Release N+2: remove wrappers
