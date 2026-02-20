# Где хранятся секреты и storage (Security Store)

## Режимы хранения

### Single mode (по умолчанию)

Всё в **одной БД**:
- **Файл:** `data/runtime.db` (или `RUNTIME_DB_PATH`)
- В этой же БД лежат и обычные данные, и секреты (ключи вида `secrets.store.*`).
- **SecretStore** (модуль agent, credentials) шифрует значения AES-256-GCM и пишет в тот же адаптер (ту же БД). Соль и зашифрованные блобы — в `runtime.db`.

### Dual mode (раздельное хранилище)

Два хранилища:
- **Core:** `data/runtime.db` (или `RUNTIME_DB_PATH`) — метаданные, конфиг, состояние.
- **Vault (секреты):** отдельный файл или PostgreSQL.
  - SQLite: `RUNTIME_VAULT_DB_PATH` (например `data/vault.db`).
  - PostgreSQL: `RUNTIME_VAULT_PG_DSN`.

Включение dual mode:
```bash
export RUNTIME_STORAGE_MODE=dual
export RUNTIME_VAULT_STORAGE_TYPE=sqlite
export RUNTIME_VAULT_DB_PATH=data/vault.db
```

## Где что в коде

| Что | Файл / место |
|-----|----------------|
| Пути БД (core, vault) | `core/config.py` — `db_path`, `vault_db_path`; из env: `RUNTIME_DB_PATH`, `RUNTIME_VAULT_DB_PATH` |
| SecretStore (шифрование секретов) | `core/security/secret_store.py` — AES-256-GCM, passphrase → master key → DEK |
| Vault port / dual-mode логика | `core/storage_port.py` — `VaultStoragePort`; `core/secure_storage.py` — обёртка |
| Сборка storage (core + vault) | `adapters/storage_factory.py` — `build_storage_stack()` |
| Credentials (метаданные + секрет в vault) | `core/credentials/repository.py` — namespace `secrets.store` для секретов |

## Итог: «файл секретов»

- **Single mode:** секреты физически в **`data/runtime.db`** (в зашифрованном виде через SecretStore).
- **Dual mode:** секреты в отдельном vault — **`data/vault.db`** (или в PostgreSQL по `RUNTIME_VAULT_PG_DSN`).

Никакого отдельного «файла секретов» в виде одного текстового файла нет — всё идёт в SQLite/PostgreSQL через storage API и SecretStore.
