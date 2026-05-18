"""
Admin auth services.

Moved from AdminModule for architectural clarity.
Behavior is unchanged.
"""
from typing import Any, Dict, List, Optional
import time

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from modules.auth.bootstrap_state import check_initialized, try_claim_bootstrap_lock, mark_initialized, release_bootstrap_lock
from modules.api.auth import (
    create_api_key,
    create_user,
    set_password,
    change_password,
    list_sessions,
    revoke_session,
    revoke_all_sessions,
    revoke_api_key,
    rotate_api_key,
    validate_user_exists,
    verify_user_password,
    generate_access_token,
    create_refresh_token,
    get_or_create_jwt_secret,
    refresh_access_token,
    AUTH_API_KEYS_NAMESPACE,
    AUTH_USERS_NAMESPACE,
    AUTH_SESSIONS_NAMESPACE,
)
import logging
logger = logging.getLogger(__name__)


async def admin_auth_create_api_key(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Create new API key."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    scopes = body.get("scopes", [])
    is_admin = body.get("is_admin", False)
    subject = body.get("subject")
    expires_at = body.get("expires_at")
    user_id = body.get("user_id")

    try:
        api_key = await create_api_key(runtime, scopes, is_admin, subject, expires_at, user_id)
        return {"ok": True, "api_key": api_key}
    except Exception as e:
        logger.warning("admin_auth_create_api_key failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_list_api_keys(runtime: Any) -> List[Dict[str, Any]]:
    """List all API keys (without actual keys, with metadata)."""
    try:
        keys = await runtime.storage.list_keys(AUTH_API_KEYS_NAMESPACE)
        result = []
        current_time = time.time()

        for key_id in keys:
            try:
                key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, key_id)
                if isinstance(key_data, dict):
                    expires_at = key_data.get("expires_at")
                    is_expired = expires_at is not None and current_time > expires_at

                    if is_expired:
                        continue

                    key_info = {
                        "id": key_id[:16] + "...",
                        "subject": key_data.get("subject"),
                        "scopes": key_data.get("scopes", []),
                        "is_admin": key_data.get("is_admin", False),
                        "created_at": key_data.get("created_at"),
                        "last_used": key_data.get("last_used"),
                        "expires_at": expires_at,
                        "is_expired": is_expired,
                    }
                    result.append(key_info)
            except STORAGE_BOUNDARY_ERRORS as e:
                logger.warning(
                    "admin_auth_list_api_keys: storage boundary reading key %s: %s",
                    key_id,
                    e,
                    exc_info=True,
                )
            except Exception as e:
                logger.warning(
                    "admin_auth_list_api_keys: unexpected error reading key %s: %s",
                    key_id,
                    e,
                    exc_info=True,
                )

        result.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return result
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "admin_auth_list_api_keys: storage boundary (list_keys): %s", e, exc_info=True
        )
        return []
    except Exception as e:
        logger.warning("admin_auth_list_api_keys failed: %s", e, exc_info=True)
        return []


async def admin_auth_create_user(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Create new user."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id")
    if not user_id:
        return {"ok": False, "error": "user_id required"}

    scopes = body.get("scopes", [])
    is_admin = body.get("is_admin", False)
    username = body.get("username")
    password = body.get("password")

    try:
        await create_user(runtime, user_id, scopes, is_admin, username, password)
        return {"ok": True, "user_id": user_id}
    except Exception as e:
        logger.warning("admin_auth_create_user failed for user_id=%s: %s", user_id, e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_list_users(runtime: Any) -> List[Dict[str, Any]]:
    """List all users."""
    try:
        user_ids = await runtime.storage.list_keys(AUTH_USERS_NAMESPACE)
        result = []
        for user_id in user_ids:
            try:
                user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
                if isinstance(user_data, dict):
                    result.append({
                        "user_id": user_id,
                        "username": user_data.get("username"),
                        "scopes": user_data.get("scopes", []),
                        "is_admin": user_data.get("is_admin", False),
                        "created_at": user_data.get("created_at"),
                    })
            except STORAGE_BOUNDARY_ERRORS as e:
                logger.warning(
                    "admin_auth_list_users: storage boundary reading user %s: %s",
                    user_id,
                    e,
                    exc_info=True,
                )
            except Exception as e:
                logger.warning(
                    "admin_auth_list_users: unexpected error reading user %s: %s",
                    user_id,
                    e,
                    exc_info=True,
                )
        return result
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "admin_auth_list_users: storage boundary (list_keys): %s", e, exc_info=True
        )
        return []
    except Exception as e:
        logger.warning("admin_auth_list_users failed: %s", e, exc_info=True)
        return []


async def admin_auth_initialize(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Initialize system by creating first admin user (public endpoint, no auth required)."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id", "admin")
    username = body.get("username", "Administrator")
    password = body.get("password")

    if not password:
        return {"ok": False, "error": "password required"}

    if await check_initialized(runtime):
        return {"ok": False, "error": "System already initialized. Admin user exists."}

    claimed = await try_claim_bootstrap_lock(runtime)
    if not claimed:
        return {"ok": False, "error": "System already initialized or bootstrap in progress"}

    try:
        if await check_initialized(runtime):
            return {"ok": False, "error": "System already initialized. Admin user exists."}

        await create_user(
            runtime,
            user_id,
            ["admin.*"],
            is_admin=True,
            username=username,
            password=password,
        )
        await mark_initialized(runtime)
        return {"ok": True, "user_id": user_id, "message": "System initialized successfully"}
    except ValueError as e:
        await release_bootstrap_lock(runtime)
        return {"ok": False, "error": str(e)}
    except STORAGE_BOUNDARY_ERRORS as e:
        await release_bootstrap_lock(runtime)
        logger.error(
            "System initialization failed (storage boundary): %s", e, exc_info=True
        )
        return {"ok": False, "error": f"Initialization failed: {str(e)}"}
    except Exception as e:
        await release_bootstrap_lock(runtime)
        logger.error("System initialization failed: %s", e, exc_info=True)
        return {"ok": False, "error": f"Initialization failed: {str(e)}"}


async def admin_auth_login(runtime: Any, body: Any = None, request: Any = None, response: Any = None) -> Dict[str, Any]:
    """Login with password authentication, sets HttpOnly cookies with tokens."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id")
    password = body.get("password")

    if not user_id:
        return {"ok": False, "error": "user_id required"}

    if not password:
        return {"ok": False, "error": "password required"}

    if not await validate_user_exists(runtime, user_id):
        return {"ok": False, "error": "invalid_credentials"}

    if not await verify_user_password(runtime, user_id, password):
        return {"ok": False, "error": "invalid_credentials"}

    try:
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
        if not isinstance(user_data, dict):
            return {"ok": False, "error": "user data not found"}

        scopes = user_data.get("scopes", [])
        is_admin = user_data.get("is_admin", False)

        client_ip = body.get("client_ip")
        user_agent = body.get("user_agent")

        secret = await get_or_create_jwt_secret(runtime)
        access_token = generate_access_token(user_id, scopes, is_admin, secret)

        refresh_token = await create_refresh_token(
            runtime,
            user_id,
            client_ip=client_ip,
            user_agent=user_agent
        )

        if response is not None:
            import secrets
            cfg = getattr(runtime, "_config", None)
            cookies_samesite = getattr(cfg, "cookies_samesite", "lax") if cfg is not None else "lax"
            cookies_domain = getattr(cfg, "cookies_domain", "localhost") if cfg is not None else "localhost"
            secure_cfg = getattr(cfg, "cookies_secure", None) if cfg is not None else None
            req_scheme = getattr(getattr(request, "url", None), "scheme", "http") if request is not None else "http"
            secure_cookie = (req_scheme == "https") if secure_cfg is None else bool(secure_cfg)
            csrf_cookie_name = getattr(cfg, "csrf_cookie_name", "csrf_token") if cfg is not None else "csrf_token"

            csrf_token = secrets.token_urlsafe(32)

            response.set_cookie(
                key="access_token",
                value=access_token,
                max_age=900,
                httponly=True,
                secure=secure_cookie,
                samesite=cookies_samesite,
                domain=cookies_domain,
                path="/"
            )
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                max_age=2592000,
                httponly=True,
                secure=secure_cookie,
                samesite=cookies_samesite,
                domain=cookies_domain,
                path="/"
            )
            response.set_cookie(
                key=csrf_cookie_name,
                value=csrf_token,
                max_age=2592000,
                httponly=False,
                secure=secure_cookie,
                samesite=cookies_samesite,
                domain=cookies_domain,
                path="/"
            )

        return {
            "ok": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": 900,
            "token_type": "Bearer"
        }
    except Exception as e:
        logger.error("Login failed for user_id=%s: %s", user_id, e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_refresh(runtime: Any, body: Any = None, request: Any = None, response: Any = None) -> Dict[str, Any]:
    """Refresh access token using refresh token from cookie or body."""
    refresh_token = None
    if request is not None:
        refresh_token = request.cookies.get("refresh_token")

    if not refresh_token and isinstance(body, dict):
        refresh_token = body.get("refresh_token")

    if not refresh_token:
        return {"ok": False, "error": "refresh_token required"}

    try:
        access_token, new_refresh_token = await refresh_access_token(
            runtime,
            refresh_token,
            rotate_refresh=True
        )

        if response is not None:
            import secrets
            cfg = getattr(runtime, "_config", None)
            cookies_samesite = getattr(cfg, "cookies_samesite", "lax") if cfg is not None else "lax"
            cookies_domain = getattr(cfg, "cookies_domain", "localhost") if cfg is not None else "localhost"
            secure_cfg = getattr(cfg, "cookies_secure", None) if cfg is not None else None
            req_scheme = getattr(getattr(request, "url", None), "scheme", "http") if request is not None else "http"
            secure_cookie = (req_scheme == "https") if secure_cfg is None else bool(secure_cfg)
            csrf_cookie_name = getattr(cfg, "csrf_cookie_name", "csrf_token") if cfg is not None else "csrf_token"

            csrf_token = secrets.token_urlsafe(32)

            response.set_cookie(
                key="access_token",
                value=access_token,
                max_age=900,
                httponly=True,
                secure=secure_cookie,
                samesite=cookies_samesite,
                domain=cookies_domain,
                path="/"
            )
            if new_refresh_token:
                response.set_cookie(
                    key="refresh_token",
                    value=new_refresh_token,
                    max_age=2592000,
                    httponly=True,
                    secure=secure_cookie,
                    samesite=cookies_samesite,
                    domain=cookies_domain,
                    path="/"
                )
            response.set_cookie(
                key=csrf_cookie_name,
                value=csrf_token,
                max_age=2592000,
                httponly=False,
                secure=secure_cookie,
                samesite=cookies_samesite,
                domain=cookies_domain,
                path="/"
            )

        result = {
            "ok": True,
            "access_token": access_token,
            "expires_in": 900,
            "token_type": "Bearer"
        }

        if new_refresh_token:
            result["refresh_token"] = new_refresh_token

        return result
    except ValueError as e:
        logger.warning("Token refresh failed: %s", e)
        return {"ok": False, "error": str(e)}
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.error(
            "Token refresh error (storage boundary): %s", e, exc_info=True
        )
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("Token refresh error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_set_password(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Set password for user."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id")
    password = body.get("password")

    if not user_id:
        return {"ok": False, "error": "user_id required"}

    if not password:
        return {"ok": False, "error": "password required"}

    try:
        await set_password(runtime, user_id, password)
        return {"ok": True, "user_id": user_id}
    except Exception as e:
        logger.warning("admin_auth_set_password failed for user_id=%s: %s", user_id, e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_change_password(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Change password for user (requires old password)."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id")
    old_password = body.get("old_password")
    new_password = body.get("new_password")

    if not user_id:
        return {"ok": False, "error": "user_id required"}

    if not old_password:
        return {"ok": False, "error": "old_password required"}

    if not new_password:
        return {"ok": False, "error": "new_password required"}

    try:
        await change_password(runtime, user_id, old_password, new_password)
        return {"ok": True, "user_id": user_id}
    except Exception as e:
        logger.warning("admin_auth_change_password failed for user_id=%s: %s", user_id, e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_list_sessions(runtime: Any, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List active sessions (optionally filtered by user_id)."""
    try:
        return await list_sessions(runtime, user_id)
    except Exception as e:
        logger.warning("admin_auth_list_sessions failed: %s", e, exc_info=True)
        return []


async def admin_auth_revoke_session(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Revoke a specific session."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    session_id = body.get("session_id")
    if not session_id:
        return {"ok": False, "error": "session_id required"}

    try:
        await revoke_session(runtime, session_id)
        return {"ok": True, "session_id": session_id[:16] + "..."}
    except Exception as e:
        logger.warning("admin_auth_revoke_session failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_revoke_all_sessions(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Revoke all sessions for a user."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id")
    if not user_id:
        return {"ok": False, "error": "user_id required"}

    try:
        revoked_count = await revoke_all_sessions(runtime, user_id)
        return {"ok": True, "user_id": user_id, "revoked_count": revoked_count}
    except Exception as e:
        logger.warning("admin_auth_revoke_all_sessions failed for user_id=%s: %s", user_id, e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_revoke_api_key(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Revoke an API key."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    api_key = body.get("api_key")
    if not api_key:
        return {"ok": False, "error": "api_key required"}

    try:
        await revoke_api_key(runtime, api_key)
        return {"ok": True, "api_key": api_key[:16] + "..."}
    except Exception as e:
        logger.warning("admin_auth_revoke_api_key failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_rotate_api_key(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """Rotate an API key (create new, revoke old)."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    old_api_key = body.get("old_api_key")
    expires_at = body.get("expires_at")

    if not old_api_key:
        return {"ok": False, "error": "old_api_key required"}

    try:
        new_api_key = await rotate_api_key(runtime, old_api_key, expires_at)
        return {"ok": True, "new_api_key": new_api_key, "old_api_key": old_api_key[:16] + "..."}
    except Exception as e:
        logger.warning("admin_auth_rotate_api_key failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def admin_auth_me(runtime: Any, request: Any = None) -> Dict[str, Any]:
    """Get current user information from request context."""
    if request is None:
        return {"ok": False, "error": "request not available"}

    if not await check_initialized(runtime):
        return {"ok": False, "needs_initialization": True, "error": "System not initialized"}

    from modules.api.auth.middleware import get_request_context
    context = await get_request_context(request)

    if context is None or context.user_id is None:
        return {"ok": False, "error": "not authenticated"}

    try:
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, context.user_id)
        if not isinstance(user_data, dict):
            return {"ok": False, "error": "user data not found"}

        return {
            "ok": True,
            "user_id": context.user_id,
            "username": user_data.get("username"),
            "scopes": list(context.scopes) if context.scopes else user_data.get("scopes", []),
            "is_admin": context.is_admin or user_data.get("is_admin", False),
            "created_at": user_data.get("created_at"),
            "source": context.source,
        }
    except STORAGE_BOUNDARY_ERRORS as e:
        logger.warning(
            "admin_auth_me: storage boundary loading user %s: %s",
            context.user_id,
            e,
            exc_info=True,
        )
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.warning(
            "admin_auth_me failed for user_id=%s: %s", context.user_id, e, exc_info=True
        )
        return {"ok": False, "error": str(e)}
