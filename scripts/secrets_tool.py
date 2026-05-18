#!/usr/bin/env python3
"""
Утилита низкоуровневого доступа к SecretStore и хранилищу Core Runtime.

Используется через `hc secrets` — CLI запускает этот скрипт внутри
контейнера (docker compose exec) или по SSH, читает JSON из stdout.

Команды:
  probe                         — проверить доступность БД и SecretStore
  list                          — список ключей в SecretStore
  get <key>                     — прочитать секрет (ТОЛЬКО в dev/debug)
  set <key>                     — записать секрет (значение из stdin)
  delete <key>                  — удалить секрет
  init                          — bootstrap: залить секреты из env в store
  rotate-csrf                   — ротация CSRF HMAC secret (grace period для старых токенов)

Все ответы — JSON в stdout. Ошибки — JSON { "ok": false, "error": "..." }.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure project root is importable when run directly (not as installed package)
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _out(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _err(msg: str, code: int = 1) -> None:
    _out({"ok": False, "error": msg})
    sys.exit(code)


async def _open_stack_and_store():
    """Открыть storage stack + SecretStore. Возвращает (store, storage_stack)."""
    from core.runtime.config import Config
    from core.runtime.state_engine import StateEngine
    from modules.storage.factory import build_storage_stack
    from app.env_bootstrap import load_dotenv, open_secret_store, probe_storage_read

    load_dotenv()
    config = Config.from_env()

    if config.storage_type == "sqlite":
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    if (
        config.storage_mode == "dual"
        and config.vault_storage_type == "sqlite"
        and config.vault_db_path
    ):
        Path(config.vault_db_path).parent.mkdir(parents=True, exist_ok=True)

    state_engine = StateEngine()
    storage_stack = await build_storage_stack(config, state_engine)
    await probe_storage_read(storage_stack)
    store = await open_secret_store(storage_stack)
    return store, storage_stack


async def _close(storage_stack) -> None:
    try:
        await storage_stack.manager.close()
    except Exception:
        pass


# ── команды ───────────────────────────────────────────────────────────────────

async def cmd_probe() -> None:
    store, stack = await _open_stack_and_store()
    keys = await store.list_secrets()
    await _close(stack)
    _out({"ok": True, "status": "store_accessible", "secret_count": len(keys)})


async def cmd_list() -> None:
    store, stack = await _open_stack_and_store()
    keys = await store.list_secrets()
    await _close(stack)
    _out({"ok": True, "keys": sorted(keys)})


async def cmd_get(key: str) -> None:
    env = (os.getenv("RUNTIME_ENV") or "production").lower()
    if env not in {"development", "dev", "test", "testing"}:
        _err("get is only allowed in dev/test environment (RUNTIME_ENV=development)")

    store, stack = await _open_stack_and_store()
    val = await store.get(key)
    await _close(stack)
    if val is None:
        _err(f"key not found: {key}")
    _out({"ok": True, "key": key, "value": val.decode("utf-8")})


async def cmd_set(key: str) -> None:
    value = sys.stdin.read().strip()
    if not value:
        _err("value must be provided via stdin (echo 'myvalue' | python secrets_tool.py set <key>)")

    store, stack = await _open_stack_and_store()
    await store.put(key, value.encode("utf-8"))
    await _close(stack)
    _out({"ok": True, "key": key, "action": "set"})


async def cmd_delete(key: str) -> None:
    store, stack = await _open_stack_and_store()
    deleted = await store.delete(key)
    await _close(stack)
    _out({"ok": True, "key": key, "deleted": deleted})


async def cmd_rotate_csrf() -> None:
    """Ручная ротация runtime.csrf_secret (текущий → previous + новый)."""
    store, stack = await _open_stack_and_store()
    report = await store.rotate_csrf_secret()
    await _close(stack)
    _out({"ok": True, "action": "rotate_csrf", **report})


async def cmd_init() -> None:
    """
    Bootstrap секреты: загружает из env в SecretStore (source_mode=store+env).
    Аналог запуска main.py с RUNTIME_SECRETS_SOURCE=store+env, но без
    полного старта runtime.
    """
    from app.env_bootstrap import bootstrap_runtime_secrets

    os.environ.setdefault("RUNTIME_SECRETS_SOURCE", "store+env")
    source_mode = (os.getenv("RUNTIME_SECRETS_SOURCE") or "store+env").strip().lower()

    store, stack = await _open_stack_and_store()
    report = await bootstrap_runtime_secrets(store, source_mode=source_mode, readonly=False)
    await _close(stack)

    _out({
        "ok": True,
        "source_mode": source_mode,
        "imported_from_env": report["imported_from_env"],
        "generated": report["generated"],
        "missing_required": report["missing_required"],
    })


# ── entrypoint ────────────────────────────────────────────────────────────────

_USAGE = """\
Usage: secrets_tool.py <command> [args]

Commands:
  probe              Check DB + SecretStore accessibility
  list               List all secret keys
  get <key>          Read a secret value (dev/test env only)
  set <key>          Write a secret (value from stdin)
  delete <key>       Delete a secret
  init               Bootstrap secrets from env into store
  rotate-csrf        Rotate CSRF HMAC secret (previous valid for grace period)
"""

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(_USAGE, file=sys.stderr)
        sys.exit(1)

    action = args[0]
    try:
        if action == "probe":
            asyncio.run(cmd_probe())
        elif action == "list":
            asyncio.run(cmd_list())
        elif action == "get":
            if len(args) < 2:
                _err("get requires <key>")
            asyncio.run(cmd_get(args[1]))
        elif action == "set":
            if len(args) < 2:
                _err("set requires <key>")
            asyncio.run(cmd_set(args[1]))
        elif action == "delete":
            if len(args) < 2:
                _err("delete requires <key>")
            asyncio.run(cmd_delete(args[1]))
        elif action == "init":
            asyncio.run(cmd_init())
        elif action == "rotate-csrf":
            asyncio.run(cmd_rotate_csrf())
        else:
            _err(f"unknown command: {action!r}. Run without args to see usage.")
    except SystemExit:
        raise
    except Exception as e:
        _err(str(e))
