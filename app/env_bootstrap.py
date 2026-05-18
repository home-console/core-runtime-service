"""
Bootstrap окружения для Home Console Runtime.

Всё, что связано с env: загрузка .env, чтение master key,
открытие SecretStore, bootstrap секретов, preflight-проверки.

main.py только оркестрирует — сюда не заглядывает.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Callable, Optional


# ── .env ─────────────────────────────────────────────────────────────────────

def load_dotenv(*extra_paths: Path) -> None:
    """Загрузить .env в os.environ (без перезаписи уже выставленных значений)."""
    candidates: list[Path] = [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
        *extra_paths,
    ]
    for path in candidates:
        _load_dotenv_file(path)


def _load_dotenv_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        with open(path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"").replace("\\n", "\n").strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


# ── Утилиты для чтения флагов ─────────────────────────────────────────────────

def env_flag(name: str, default: bool = False) -> bool:
    """Прочитать булевый флаг из env (1/true/yes/on → True)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def secrets_source_mode() -> str:
    """
    RUNTIME_SECRETS_SOURCE:
        store       — только SecretStore
        store+env   — SecretStore wins; env как fallback при миграции (default)
        env         — только env
    """
    mode = (os.getenv("RUNTIME_SECRETS_SOURCE") or "store+env").strip().lower()
    if mode not in {"store", "store+env", "env"}:
        raise RuntimeError(
            "RUNTIME_SECRETS_SOURCE must be one of: store, store+env, env"
        )
    return mode


# ── Master key ────────────────────────────────────────────────────────────────

from modules.security.master_key import has_master_key, resolve_master_key_passphrase  # noqa: F401


# ── Storage read probe ────────────────────────────────────────────────────────

async def probe_storage_read(storage_stack: object) -> None:
    """
    Read-only smoke: проверяем, что core БД (и vault БД в dual-mode)
    доступны на чтение до любых операций записи.
    """
    core_port = getattr(storage_stack, "core_port", None)
    if core_port is None:
        raise RuntimeError("Storage probe failed: core_port is not available")
    await core_port.get("bootstrap_probe", "core_ping")

    vault_port = getattr(storage_stack, "vault_port", None)
    if vault_port is not None:
        await vault_port.get("bootstrap_probe", "vault_ping")


# ── SecretStore open ──────────────────────────────────────────────────────────

async def open_secret_store(storage_stack: object) -> object:
    """
    Открыть (или инициализировать первый раз) SecretStore
    на правильном backend (vault в dual-mode, иначе core).
    """
    from modules.security import SecretStore, SecretStoreStorageAdapter

    backend = (
        storage_stack.manager.get_vault()
        if storage_stack.manager.is_dual_mode
        else storage_stack.manager.get_core()
    )
    store = SecretStore(SecretStoreStorageAdapter(backend))
    passphrase = resolve_master_key_passphrase()
    try:
        await store.open_with_passphrase(passphrase)
    except RuntimeError as e:
        if "not initialized" in str(e).lower():
            await store.initialize(passphrase)
        else:
            raise
    return store


# ── Runtime secrets bootstrap ─────────────────────────────────────────────────

def _make_oauth_key() -> str:
    from sdk.security import TokenEncryption
    return TokenEncryption.generate_key()


# (env_key, store_key, generator_or_None, required)
_SECRET_SPECS: list[tuple[str, str, Optional[Callable[[], str]], bool]] = [
    ("CSRF_SECRET",          "runtime.csrf_secret",          lambda: secrets.token_hex(32), True),
    ("OAUTH_ENCRYPTION_KEY", "runtime.oauth_encryption_key", _make_oauth_key,               True),
    ("YANDEX_CLIENT_SECRET", "yandex.client_secret",         None,                          False),
]


async def bootstrap_runtime_secrets(
    secret_store: object,
    *,
    source_mode: str,
    readonly: bool,
) -> dict[str, list[str]]:
    """
    Разрешить runtime-секреты (CSRF_SECRET, OAUTH_ENCRYPTION_KEY, …) и
    выставить их в os.environ для legacy-читателей.

    source_mode:
        store      — только SecretStore; генерировать если нет (запись при первом старте)
        store+env  — SecretStore wins; при отсутствии берём из env и импортируем в store
        env        — только env; генерировать локально (не персистировать)

    readonly:
        True  — ничего не записывать; отсутствующие required ключи попадают в missing_required
    """
    imported_from_env: list[str] = []
    generated: list[str] = []
    missing_required: list[str] = []

    async def _resolve(
        env_key: str,
        store_key: str,
        generator: Optional[Callable[[], str]],
        required: bool,
    ) -> None:
        env_val = (os.getenv(env_key) or "").strip()
        store_val = ""

        if source_mode in {"store", "store+env"}:
            raw = await secret_store.get(store_key)  # type: ignore[attr-defined]
            if raw:
                store_val = raw.decode("utf-8")

        resolved = ""
        if source_mode == "store":
            resolved = store_val
            if not resolved and not readonly and generator:
                resolved = generator()
                await secret_store.put(store_key, resolved.encode())  # type: ignore[attr-defined]
                generated.append(env_key)

        elif source_mode == "store+env":
            if store_val:
                resolved = store_val
            elif env_val:
                resolved = env_val
                if not readonly:
                    await secret_store.put(store_key, resolved.encode())  # type: ignore[attr-defined]
                    imported_from_env.append(env_key)
            elif not readonly and generator:
                resolved = generator()
                await secret_store.put(store_key, resolved.encode())  # type: ignore[attr-defined]
                generated.append(env_key)

        else:  # env
            resolved = env_val
            if not resolved and not readonly and generator:
                resolved = generator()
                generated.append(env_key)

        if resolved:
            os.environ[env_key] = resolved
        elif required:
            missing_required.append(env_key)

    for spec in _SECRET_SPECS:
        await _resolve(*spec)

    csrf_rotated: list[str] = []
    if source_mode in {"store", "store+env"}:
        from modules.security.csrf_secret import maybe_auto_rotate_csrf_secret, sync_csrf_secrets_to_env

        rotation = await maybe_auto_rotate_csrf_secret(
            secret_store,  # type: ignore[arg-type]
            readonly=readonly,
        )
        if rotation is not None:
            csrf_rotated.append("CSRF_SECRET")
        else:
            await sync_csrf_secrets_to_env(secret_store)  # type: ignore[arg-type]

    return {
        "imported_from_env": imported_from_env,
        "generated": generated,
        "missing_required": missing_required,
        "csrf_rotated": csrf_rotated,
    }


# ── Preflight check ───────────────────────────────────────────────────────────

def preflight_check() -> None:
    """
    Fail-fast после bootstrap: все обязательные секреты должны быть
    в os.environ (выставлены из store или env).
    Печатает warnings из check_security_env().
    """
    from modules.security import check_security_env

    missing: list[str] = []

    if not has_master_key():
        missing.append("RUNTIME_MASTER_KEY (or RUNTIME_MASTER_KEY_FILE)")

    csrf_enabled = (os.getenv("RUNTIME_CSRF_ENABLED") or "true").lower().strip() == "true"
    if csrf_enabled:
        for key in ("CSRF_SECRET", "OAUTH_ENCRYPTION_KEY"):
            if not (os.getenv(key) or "").strip():
                missing.append(key)

    if missing:
        raise RuntimeError(
            "Missing required secrets:\n" + "\n".join(f"  - {k}" for k in missing)
        )

    result = check_security_env()
    for warning in result.get("warnings", []):
        print(f"[Runtime][Security Warning] {warning}")
