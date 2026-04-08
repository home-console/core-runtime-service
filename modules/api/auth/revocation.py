"""
Revocation — отзыв API keys, sessions и refresh tokens.
"""

import hashlib
import time
from typing import Any

from .audit import audit_log_auth_event
from .constants import (
    AUTH_API_KEYS_NAMESPACE,
    AUTH_REFRESH_TOKENS_NAMESPACE,
    AUTH_REVOKED_NAMESPACE,
    AUTH_SESSIONS_NAMESPACE,
    AUTH_STORAGE_BOUNDARY_ERRORS,
)
import logging
logger = logging.getLogger(__name__)


async def revoke_api_key(runtime: Any, api_key: str) -> None:
    """
    Отзывает API key.

    Args:
        runtime: экземпляр CoreRuntime
        api_key: API ключ для отзыва
    """
    try:
        # Сохраняем в revoked list
        revoked_entry = {"revoked_at": time.time(), "type": "api_key"}
        revoked_key = hashlib.sha256(api_key.encode()).hexdigest()
        await runtime.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, revoked_entry)

        # Удаляем из активных ключей
        try:
            await runtime.storage.delete(AUTH_API_KEYS_NAMESPACE, api_key)
        except AUTH_STORAGE_BOUNDARY_ERRORS:
            logger.warning("revoke_api_key: active key delete failed", exc_info=True)

        # Логируем
        await audit_log_auth_event(
            runtime,
            "key_revoked",
            api_key[:16] + "...",
            {"type": "api_key"},
            success=True,
        )

    except AUTH_STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("revoke_api_key storage error: %s", e, exc_info=True)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking API key: {e}",
                module="api",
            )
        except Exception:
            logger.warning("logger.log service call failed", exc_info=True)
    except Exception as e:
        logger.exception("revoke_api_key unexpected: %s", e)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking API key: {e}",
                module="api",
            )
        except Exception:
            logger.warning("logger.log service call failed", exc_info=True)


async def revoke_session(runtime: Any, session_id: str) -> None:
    """
    Отзывает session.

    Args:
        runtime: экземпляр CoreRuntime
        session_id: ID сессии для отзыва
    """
    try:
        # Сохраняем в revoked list
        revoked_entry = {"revoked_at": time.time(), "type": "session"}
        revoked_key = hashlib.sha256(session_id.encode()).hexdigest()
        await runtime.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, revoked_entry)

        # Удаляем из активных сессий
        try:
            await runtime.storage.delete(AUTH_SESSIONS_NAMESPACE, session_id)
        except AUTH_STORAGE_BOUNDARY_ERRORS:
            logger.warning("revoke_session: active session delete failed", exc_info=True)

        # Логируем
        await audit_log_auth_event(
            runtime,
            "session_revoked",
            session_id[:16] + "...",
            {"type": "session"},
            success=True,
        )

    except AUTH_STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("revoke_session storage error: %s", e, exc_info=True)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking session: {e}",
                module="api",
            )
        except Exception:
            logger.warning("logger.log service call failed", exc_info=True)
    except Exception as e:
        logger.exception("revoke_session unexpected: %s", e)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking session: {e}",
                module="api",
            )
        except Exception:
            logger.warning("logger.log service call failed", exc_info=True)


async def revoke_refresh_token(runtime: Any, refresh_token: str) -> None:
    """
    Отзывает refresh token.

    Args:
        runtime: экземпляр CoreRuntime
        refresh_token: refresh token для отзыва
    """
    try:
        # Сохраняем в revoked list
        revoked_entry = {"revoked_at": time.time(), "type": "refresh_token"}
        revoked_key = hashlib.sha256(refresh_token.encode()).hexdigest()
        await runtime.storage.set(AUTH_REVOKED_NAMESPACE, revoked_key, revoked_entry)

        # Удаляем из активных токенов
        try:
            await runtime.storage.delete(AUTH_REFRESH_TOKENS_NAMESPACE, refresh_token)
        except AUTH_STORAGE_BOUNDARY_ERRORS:
            logger.warning("revoke_refresh_token: active token delete failed", exc_info=True)

        # Audit logging
        await audit_log_auth_event(
            runtime,
            "refresh_token_revoked",
            refresh_token[:16] + "...",
            {"type": "refresh_token"},
            success=True,
        )

    except AUTH_STORAGE_BOUNDARY_ERRORS as e:
        logger.warning("revoke_refresh_token storage error: %s", e, exc_info=True)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking refresh token: {e}",
                module="api",
            )
        except Exception:
            logger.warning("logger.log service call failed", exc_info=True)
    except Exception as e:
        logger.exception("revoke_refresh_token unexpected: %s", e)
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error revoking refresh token: {e}",
                module="api",
            )
        except Exception:
            logger.warning("logger.log service call failed", exc_info=True)


async def is_revoked(runtime: Any, identifier: str, revoke_type: str) -> bool:
    """
    Проверяет, отозван ли ключ, сессия или токен.

    Args:
        runtime: экземпляр CoreRuntime
        identifier: API key, session_id или refresh_token
        revoke_type: "api_key", "session" или "refresh_token"

    Returns:
        True если отозван или состояние revocation нельзя достоверно проверить,
        False если точно не отозван
    """
    try:
        revoked_key = hashlib.sha256(identifier.encode()).hexdigest()
        revoked_entry = await runtime.storage.get(AUTH_REVOKED_NAMESPACE, revoked_key)

        if revoked_entry is None:
            return False

        if not isinstance(revoked_entry, dict):
            return False

        # Проверяем тип
        entry_type = revoked_entry.get("type")
        if entry_type != revoke_type:
            return False

        return True

    except AUTH_STORAGE_BOUNDARY_ERRORS:
        logger.debug(
            "is_revoked: storage error, fail-closed",
            exc_info=True,
        )
        return True
    except Exception:
        logger.exception("is_revoked: unexpected error, fail-closed")
        return True
