"""
Bootstrap state: initialization flag, atomic claim, admin presence checks.

Shared by modules/auth/handlers.py and modules/admin/auth.py.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from modules.api.auth import AUTH_USERS_NAMESPACE

logger = logging.getLogger(__name__)

BOOTSTRAP_STATE_KEY = "initialized"
BOOTSTRAP_LOCK_KEY = "_init_lock"
AUTH_CONFIG_NAMESPACE = "auth_config"
AUTH_STATE_NAMESPACE = "auth"


def _state_cache_key() -> str:
    return f"{AUTH_STATE_NAMESPACE}.{BOOTSTRAP_STATE_KEY}"


def _resolve_storage_adapter(storage: Any) -> Any:
    """Walk wrappers (Storage, mirror, port) to the underlying adapter."""
    current = storage
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if callable(getattr(current, "set_if_absent", None)):
            return current
        nxt = getattr(current, "_adapter", None) or getattr(current, "_storage", None)
        if nxt is current:
            break
        current = nxt
    return storage


async def _read_persistent_initialized(storage: Any) -> bool:
    try:
        stored = await storage.get(AUTH_CONFIG_NAMESPACE, BOOTSTRAP_STATE_KEY)
        if isinstance(stored, dict):
            return bool(stored.get("value", False))
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "bootstrap_state: storage boundary reading persistent flag: %s",
            e,
            exc_info=True,
        )
    except Exception as e:
        logger.warning("bootstrap_state: failed to read persistent flag: %s", e, exc_info=True)
    return False


async def _has_admin_user(storage: Any) -> bool:
    """True if any user in AUTH_USERS_NAMESPACE has is_admin=True."""
    try:
        iter_ns = getattr(storage, "iter_namespace", None)
        if callable(iter_ns):
            async for _uid, user_data in iter_ns(AUTH_USERS_NAMESPACE):
                if isinstance(user_data, dict) and user_data.get("is_admin", False):
                    return True
            return False

        user_ids = await storage.list_keys(AUTH_USERS_NAMESPACE)
        for uid in user_ids:
            user_data = await storage.get(AUTH_USERS_NAMESPACE, uid)
            if isinstance(user_data, dict) and user_data.get("is_admin", False):
                return True
        return False
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "bootstrap_state: storage boundary scanning admins: %s", e, exc_info=True
        )
        return False
    except Exception as e:
        logger.warning("bootstrap_state: failed to scan admins: %s", e, exc_info=True)
        return False


async def check_initialized(runtime: Any) -> bool:
    """
    Check if system is initialized.

    Returns True if:
    1. State cache has auth.initialized = True, OR
    2. Persistent auth_config.initialized flag is set, OR
    3. At least one admin user exists (legacy fallback)
    """
    state_key = _state_cache_key()
    try:
        cached = await runtime.state.get(state_key)
        if cached is not None:
            return bool(cached.get("value", False))
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "check_initialized: storage boundary reading state cache: %s",
            e,
            exc_info=True,
        )
    except Exception as e:
        logger.warning("check_initialized: failed to read state cache: %s", e, exc_info=True)

    if await _read_persistent_initialized(runtime.storage):
        try:
            await runtime.state.set(state_key, {"value": True})
        except Exception:
            logger.debug("check_initialized: failed to warm state cache", exc_info=True)
        return True

    if await _has_admin_user(runtime.storage):
        await mark_initialized(runtime)
        return True

    return False


async def mark_initialized(runtime: Any) -> None:
    """Mark system as initialized in state and persistent storage."""
    state_key = _state_cache_key()
    try:
        await runtime.state.set(state_key, {"value": True})
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("mark_initialized: storage boundary (state): %s", e, exc_info=True)
    except Exception as e:
        logger.warning("mark_initialized: failed to set state cache: %s", e, exc_info=True)

    try:
        await runtime.storage.set(
            AUTH_CONFIG_NAMESPACE,
            BOOTSTRAP_STATE_KEY,
            {"value": True},
        )
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "mark_initialized: storage boundary persisting flag: %s", e, exc_info=True
        )
    except Exception as e:
        logger.warning("mark_initialized: failed to persist flag: %s", e, exc_info=True)


async def try_claim_bootstrap_lock(runtime: Any) -> bool:
    """
    Atomically claim one-shot bootstrap (compare-and-set on storage).

    Returns True if this caller won the claim and may proceed with initialize.
    """
    adapter = _resolve_storage_adapter(runtime.storage)
    set_if_absent = getattr(adapter, "set_if_absent", None)
    if not callable(set_if_absent):
        logger.warning("bootstrap_state: storage adapter has no set_if_absent; using soft lock")
        existing = await adapter.get(AUTH_CONFIG_NAMESPACE, BOOTSTRAP_LOCK_KEY)
        if existing is not None:
            return False
        await adapter.set(
            AUTH_CONFIG_NAMESPACE,
            BOOTSTRAP_LOCK_KEY,
            {"claimed_at": time.time()},
        )
        return True

    return await set_if_absent(
        AUTH_CONFIG_NAMESPACE,
        BOOTSTRAP_LOCK_KEY,
        {"claimed_at": time.time()},
    )


async def release_bootstrap_lock(runtime: Any) -> None:
    """Release bootstrap lock after a failed initialize attempt."""
    try:
        await runtime.storage.delete(AUTH_CONFIG_NAMESPACE, BOOTSTRAP_LOCK_KEY)
    except Exception:
        logger.debug("release_bootstrap_lock failed", exc_info=True)
