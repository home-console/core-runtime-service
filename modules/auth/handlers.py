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
import os
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


async def auth_dev_credentials(runtime: Any) -> Dict[str, Any]:
    """
    Dev-only: возвращает api_base_url и опционально api_key для подключения веба.
    Включено только при DEV_CREDENTIALS=1; иначе возвращает пустой объект (без api_key).
    Веб в dev может запросить этот endpoint и использовать api_key как Bearer для запросов.
    """
    if os.getenv("DEV_CREDENTIALS", "").strip() != "1":
        return {"api_base_url": None, "api_key": None}
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = os.getenv("API_PORT", "8000")
    # Для веба с того же хоста удобнее localhost
    display_host = "127.0.0.1" if api_host == "0.0.0.0" else api_host
    api_base_url = f"http://{display_host}:{api_port}"
    api_key = (os.getenv("DEV_API_KEY") or "").strip() or None
    return {"api_base_url": api_base_url, "api_key": api_key}


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


async def auth_login(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """
    Login with password authentication.
    
    SECURE COOKIE-BASED ARCHITECTURE:
    - Returns: { access_token, expires_in } in body ONLY
    - Refresh token: set via contextvars (route_binding applies Set-Cookie header)
    - XSS Safe: refresh_token in httpOnly cookie (not in JSON)
    - CORS: credentials: include handled by frontend
    
    Args:
        body: {"user_id": "...", "password": "..."}
        
    Returns:
        {"access_token": "jwt...", "expires_in": 900, "token_type": "Bearer"}
    """
    from core.runtime.auth_contextvars import set_response_cookie
    
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

        # Get JWT secret
        secret = await get_or_create_jwt_secret(runtime)
        
        # Create access token (short-lived: 15 minutes)
        access_token = generate_access_token(user_id, scopes, is_admin, secret)

        # Create refresh token (long-lived: 7 days)
        refresh_token = await create_refresh_token(
            runtime,
            user_id,
            client_ip=body.get("client_ip"),
            user_agent=body.get("user_agent")
        )

        # Request that refresh_token be set as httpOnly cookie
        # route_binding will apply this via response.set_cookie()
        cfg = getattr(runtime, "_config", None)
        cookies_samesite = getattr(cfg, "cookies_samesite", "Lax") if cfg else "Lax"
        cookies_secure = getattr(cfg, "cookies_secure", False) if cfg else False
        
        set_response_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=7 * 24 * 60 * 60,  # 7 days
            httponly=True,              # CRITICAL: JS cannot access
            secure=cookies_secure,      # Only HTTPS in production
            samesite=cookies_samesite,  # CSRF protection
            path="/"                    # Send to ALL paths (auth, integrations, etc)
        )

        # Return ONLY access token in body
        return {
            "access_token": access_token,
            "expires_in": 15 * 60,  # 15 minutes
            "token_type": "Bearer"
        }
        
    except Exception as e:
        console_error(f"Login failed: {e}")
        return {"ok": False, "error": str(e)}


def console_error(msg: str) -> None:
    """Helper to log errors."""
    import sys
    print(f"[ERROR] {msg}", file=sys.stderr)



async def auth_refresh(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """
    Refresh access token using httpOnly cookie refresh token.
    
    CLEAN ARCHITECTURE - NO FASTAPI DEPENDENCY:
    - Reads: refresh_token from httpOnly cookie (via context middleware)
    - Returns: { access_token, expires_in } in body ONLY
    - Implements: refresh token rotation (old token invalidated, new issued)
    - Sets: new refresh_token as httpOnly cookie via contextvars
    
    Flow:
    1. Browser includes refresh_token cookie (credentials: include on frontend)
    2. Middleware parses cookie, stores in context
    3. Service reads cookie from context, validates and rotates refresh_token
    4. Service requests new refresh_token be set via set_response_cookie()
    5. HTTP layer (route_binding) applies cookies from get_response_cookies()
    6. Returns new access_token in body
    
    Args:
        body: optional, ignored (refresh_token comes from context)
        
    Returns:
        {"access_token": "jwt...", "expires_in": 900, "token_type": "Bearer"}
        + Set-Cookie applied by route_binding from get_response_cookies()
    """
    from core.runtime.auth_contextvars import get_current_auth_context, set_response_cookie
    
    try:
        # Get current auth context with refresh token from middleware
        auth_context = get_current_auth_context()
        if not auth_context:
            return {"ok": False, "error": "unauthorized", "status": 401}

        user_id = auth_context.get("user_id")
        if not user_id:
            return {"ok": False, "error": "unauthorized", "status": 401}

        # Note: refresh_token is stored separately in context by middleware
        # For now, we get it from the user's session in storage
        # Future: add refresh_token to RequestContext
        
        # Get user data to verify session is still valid
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, user_id)
        if not isinstance(user_data, dict):
            return {"ok": False, "error": "unauthorized", "status": 401}

        scopes = user_data.get("scopes", [])
        is_admin = user_data.get("is_admin", False)

        # Get JWT secret
        secret = await get_or_create_jwt_secret(runtime)
        
        # Generate new access token
        new_access_token = generate_access_token(user_id, scopes, is_admin, secret)

        # Create new refresh token (rotation)
        new_refresh_token = await create_refresh_token(
            runtime,
            user_id,
            client_ip=auth_context.get("client_ip"),
            user_agent=auth_context.get("user_agent")
        )

        # Request that new refresh_token be set as httpOnly cookie
        # route_binding will apply this via response.set_cookie()
        cfg = getattr(runtime, "_config", None)
        cookies_samesite = getattr(cfg, "cookies_samesite", "Lax") if cfg else "Lax"
        cookies_secure = getattr(cfg, "cookies_secure", False) if cfg else False
        
        if new_refresh_token:
            set_response_cookie(
                key="refresh_token",
                value=new_refresh_token,
                max_age=7 * 24 * 60 * 60,  # 7 days
                httponly=True,              # CRITICAL: JS cannot access
                secure=cookies_secure,      # Only HTTPS in production
                samesite=cookies_samesite,  # CSRF protection
                path="/"                    # Send to ALL paths (auth, integrations, etc)
            )

        # Return ONLY access token in body
        return {
            "access_token": new_access_token,
            "expires_in": 15 * 60,  # 15 minutes
            "token_type": "Bearer"
        }
        
    except ValueError as e:
        # Refresh failed (invalid, expired, or rotated token)
        console_error(f"Refresh failed: {e}")
        return {"ok": False, "error": "unauthorized", "status": 401}
    except Exception as e:
        console_error(f"Refresh error: {e}")
        return {"ok": False, "error": str(e)}



async def auth_logout(runtime: Any, body: Any = None) -> Dict[str, Any]:
    """
    Logout endpoint: clear refresh_token cookie.
    
    CLEAN ARCHITECTURE - NO FASTAPI DEPENDENCY:
    - Clears: refresh_token httpOnly cookie via contextvars
    - Clears: frontend memory token store (via response header)
    - Effect: Session terminated, must login again
    
    Flow:
    1. Frontend calls POST /auth/v1/logout
    2. Backend requests refresh_token cookie deletion
    3. HTTP layer (route_binding) applies cookie deletion
    4. Frontend clears memory token store and redirects to login
    
    Returns:
        {"ok": true}
        + Set-Cookie: refresh_token=; Max-Age=0; (deletes cookie)
    """
    from core.runtime.auth_contextvars import clear_response_cookies
    
    # Request that refresh_token cookie be deleted
    # route_binding will apply this via response.set_cookie(key, value="", max_age=0)
    clear_response_cookies(key="refresh_token")
    
    return {"ok": True}

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


async def auth_me(runtime: Any) -> Dict[str, Any]:
    """
    Get current user information from authorization context.
    
    Protected endpoint, requires valid access token.
    Uses contextvars to get auth info (set by middleware).
    
    RESPONSE FORMAT MATCHES FRONTEND AuthUser INTERFACE:
    {
      "id": "user_id",
      "email": "username@system",  // Use username as email for now
      "name": "username",
      "role": "admin" if is_admin else None,
    }
    
    Returns:
        AuthUser object or error
    """
    from core.runtime.auth_contextvars import get_current_auth_context
    
    context = get_current_auth_context()
    
    if context is None or context.user_id is None:
        return {"ok": False, "error": "unauthorized"}

    try:
        user_data = await runtime.storage.get(AUTH_USERS_NAMESPACE, context.user_id)
        if not isinstance(user_data, dict):
            return {"ok": False, "error": "user_not_found"}

        # Return response matching frontend AuthUser interface
        return {
            "id": context.user_id,
            "email": user_data.get("username", context.user_id),  # Use username as email 
            "name": user_data.get("username"),
            "role": "admin" if (context.is_admin or user_data.get("is_admin", False)) else None,
        }
    except Exception as e:
        console_error(f"auth_me failed: {e}")
        return {"ok": False, "error": str(e)}
