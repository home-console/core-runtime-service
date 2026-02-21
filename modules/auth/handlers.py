"""
Auth service handlers — admin.auth.* services.

Moved from AdminModule for architectural separation.
Identity (auth) is a boundary, not mixed with admin UI (control plane).
Behavior unchanged, only organization different.

Bootstrap Architecture:
- auth.initialized flag stored in runtime.state (cached)
- GET /auth/v1/bootstrap returns {"initialized": bool}
- POST /auth/v1/initialize is one-shot (403 if already initialized)
- /auth/v1/me returns user info only, no bootstrap logic
"""
from typing import Any, Dict, List, Optional
import time

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


# --- Bootstrap State Helpers ---
BOOTSTRAP_STATE_KEY = "initialized"
AUTH_STATE_NAMESPACE = "auth"


async def _check_initialized(runtime: Any) -> bool:
    """
    Check if system is initialized (cached in state).
    
    Returns True if:
    1. State has auth.initialized = True, OR
    2. At least one user with is_admin=True exists
    """
    try:
        # Check state cache first
        cached = await runtime.state.get(AUTH_STATE_NAMESPACE, BOOTSTRAP_STATE_KEY)
        if cached is not None:
            return bool(cached.get("value", False))
    except Exception:
        pass
    
    # Fall back: scan for admin user
    try:
        user_ids = await runtime.storage.list_keys(AUTH_USERS_NAMESPACE)
        for uid in user_ids:
            try:
                user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, uid)
                if isinstance(user_data, dict) and user_data.get("is_admin", False):
                    # Cache the result
                    try:
                        await runtime.state.set(AUTH_STATE_NAMESPACE, BOOTSTRAP_STATE_KEY, {"value": True})
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


async def _mark_initialized(runtime: Any) -> None:
    """
    Mark system as initialized in state.
    Called after successfully creating first admin.
    """
    try:
        await runtime.state.set(AUTH_STATE_NAMESPACE, BOOTSTRAP_STATE_KEY, {"value": True})
    except Exception:
        pass


async def auth_bootstrap(runtime: Any) -> Dict[str, Any]:
    """
    Bootstrap status endpoint — check if system is initialized.
    
    Public endpoint, no auth required.
    Returns only the initialization status, no side effects.
    
    Response:
        {"initialized": true|false}
    """
    try:
        initialized = await _check_initialized(runtime)
        return {"initialized": initialized}
    except Exception:
        # On error, assume not initialized (safe default)
        return {"initialized": False}


async def auth_create_api_key(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_list_api_keys(runtime: Any) -> List[Dict[str, Any]]:
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
            except Exception:
                pass

        result.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return result
    except Exception:
        return []


async def auth_create_user(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_list_users(runtime: Any) -> List[Dict[str, Any]]:
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
            except Exception:
                pass
        return result
    except Exception:
        return []


async def auth_initialize(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """
    Initialize system by creating first admin user (one-shot).
    
    Public endpoint, no auth required.
    
    Rules:
    - If system already initialized → HTTP 403 (Forbidden)
    - If not initialized → create admin, set initialized flag, return success
    - Cannot be called twice
    
    Args:
        body: {"user_id": "admin", "username": "Admin", "password": "..."}
    
    Returns:
        {"ok": true, "user_id": "admin"} or {"ok": false, "error": "..."}
    """
    # Check if already initialized
    initialized = await _check_initialized(runtime)
    if initialized:
        return {"ok": False, "error": "forbidden", "status": 403}
    
    if not isinstance(body, dict):
        return {"ok": False, "error": "invalid_body"}

    user_id = body.get("user_id", "admin")
    username = body.get("username", "Administrator")
    password = body.get("password")

    if not password:
        return {"ok": False, "error": "password required"}

    try:
        await create_user(
            runtime,
            user_id,
            ["admin.*"],
            is_admin=True,
            username=username,
            password=password
        )
        
        # Mark system as initialized
        await _mark_initialized(runtime)
        
        return {"ok": True, "user_id": user_id, "message": "System initialized successfully"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Initialization failed: {str(e)}"}


async def auth_login(runtime: Any, body: Any = None, request: Any = None, response: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_refresh(runtime: Any, body: Any = None, request: Any = None, response: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def auth_set_password(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_change_password(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_list_sessions(runtime: Any, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List active sessions (optionally filtered by user_id)."""
    try:
        return await list_sessions(runtime, user_id)
    except Exception:
        return []


async def auth_revoke_session(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_revoke_all_sessions(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_revoke_api_key(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_rotate_api_key(runtime: Any, body: Any = None) -> Dict[str, Any]:
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
        return {"ok": False, "error": str(e)}


async def auth_me(runtime: Any, request: Any = None) -> Dict[str, Any]:
    """
    Get current user information from request context.
    
    Protected endpoint, requires auth token.
    Returns user info only, no bootstrap logic.
    
    Returns:
        {"ok": true, "user_id": "...", ...} or {"ok": false, "error": "not authenticated"}
    """
    if request is None:
        return {"ok": False, "error": "request not available"}

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
    except Exception as e:
        return {"ok": False, "error": str(e)}
