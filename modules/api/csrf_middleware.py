"""
CSRF Protection Middleware for Admin API.

SECURITY P0: Admin API endpoints MUST validate CSRF tokens to prevent CSRF attacks.

Mechanics:
- Client gets CSRF token from /admin/v1/auth/csrf endpoint
- Client includes token in X-CSRF-Token header for mutating operations
- Server validates token using HMAC-based validation
- Token is tied to user session

Safe methods (GET, HEAD, OPTIONS) are exempt from CSRF validation.
"""

from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# Methods that don't require CSRF protection (read-only)
CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _add_cors_to_response(request: Request, response: Response) -> None:
    """Добавить CORS-заголовки к ответу для localhost origin (чтобы 403 не блокировался браузером)."""
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"


async def csrf_protection_middleware(request: Request, call_next: Callable) -> Response:
    """
    Validate CSRF token for admin API mutating operations.
    
    SECURITY P0:
    - All POST/PUT/PATCH/DELETE to /admin/* require CSRF token
    - Token validated using HMAC tied to session
    - Missing/invalid token = 403 Forbidden
    
    Args:
        request: FastAPI request
        call_next: Next middleware/handler
        
    Returns:
        Response
        
    Raises:
        HTTPException 403: If CSRF validation fails
    """
    # Only validate CSRF for admin endpoints
    if not request.url.path.startswith("/admin/"):
        return await call_next(request)
    
    # Skip CSRF for safe methods
    if request.method in CSRF_SAFE_METHODS:
        return await call_next(request)
    
    # Skip CSRF for auth endpoints (bootstrap problem)
    if request.url.path.startswith("/admin/v1/auth/"):
        return await call_next(request)
    
    # Auth context is set by require_auth_middleware which must run before this middleware.
    ctx = getattr(request.state, "auth_context", None)
    if not ctx:
        # Unauthenticated request — not vulnerable to CSRF (no session to hijack).
        # Pass through; the route handler will return 401.
        return await call_next(request)

    # JWT и API key (Bearer в заголовке) не уязвимы к CSRF — токен не отправляется браузером автоматически.
    # CSRF обязателен только для cookie-based сессий.
    source = getattr(ctx, "source", None) or ""
    if source in ("jwt", "api_key"):
        return await call_next(request)

    # Для session/cookie — требуем X-CSRF-Token
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token:
        r = JSONResponse(status_code=403, content={"detail": "CSRF token required"})
        _add_cors_to_response(request, r)
        return r

    # session_id for CSRF validation
    session_id = getattr(ctx, "session_id", None) or getattr(ctx, "user_id", None)
    if not session_id:
        r = JSONResponse(status_code=403, content={"detail": "Session required for CSRF validation"})
        _add_cors_to_response(request, r)
        return r
    
    # Validate CSRF token
    try:
        from modules.security import CSRFProtection
        csrf = CSRFProtection.from_env()
        csrf.validate_token(csrf_token, session_id)
    except RuntimeError as e:
        # CSRF is enabled but not configured (missing CSRF_SECRET) — fail-closed.
        # If you intentionally want to disable CSRF (dev only), set RUNTIME_CSRF_ENABLED=false.
        r = JSONResponse(
            status_code=500,
            content={
                "detail": "CSRF protection not configured (CSRF_SECRET missing). "
                "Set CSRF_SECRET or disable CSRF via RUNTIME_CSRF_ENABLED=false."
            },
        )
        _add_cors_to_response(request, r)
        return r
    except ValueError:
        r = JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})
        _add_cors_to_response(request, r)
        return r
    
    return await call_next(request)


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """
    Rate limit admin API endpoints.
    
    DEBUG MODE: Rate limiting is DISABLED for easier development.
    Set DEBUG_MODE=false in environment to enable rate limiting.
    
    Args:
        request: FastAPI request
        call_next: Next middleware/handler
        
    Returns:
        Response
    """
    import os
    
    # DISABLED by default for debug mode
    if os.getenv("DEBUG_MODE", "true").lower() != "false":
        # Rate limiting is disabled - pass through
        return await call_next(request)
    
    # Only rate limit admin endpoints
    if not request.url.path.startswith("/admin/"):
        return await call_next(request)
    
    # Skip rate limiting for monitoring endpoints
    if request.url.path.startswith("/admin/v1/monitor"):
        return await call_next(request)
    
    # Get user identifier from request context
    ctx = getattr(request.state, "context", None)
    if not ctx:
        # No auth context - use IP address
        identifier = request.client.host if request.client else "unknown"
    else:
        identifier = getattr(ctx, "user_id", None) or (request.client.host if request.client else "unknown")
    
    # Define rate limits for different endpoint types
    rate_limits = {
        "/admin/v1/yandex/sync": {"max_calls": 60, "window_sec": 60},  # Повышено: 5 → 60 для синхронизации
        "/admin/v1/devices": {"max_calls": 500, "window_sec": 60},      # Повышено: 100 → 500
        "/admin/v1/inspector/storage": {"max_calls": 500, "window_sec": 60},  # Повышено: 100 → 500
        "default": {"max_calls": 1000, "window_sec": 60},                # Повышено: 200 → 1000
    }
    
    # Find matching rate limit
    endpoint_limit = rate_limits.get("default")
    for path_prefix, limit in rate_limits.items():
        if path_prefix != "default" and request.url.path.startswith(path_prefix):
            endpoint_limit = limit
            break
    
    # Check rate limit
    try:
        from modules.security import RateLimiter
        # Use singleton rate limiter (stored in app state)
        if not hasattr(request.app.state, "rate_limiter"):
            request.app.state.rate_limiter = RateLimiter()
        
        limiter = request.app.state.rate_limiter
        limiter.check_limit(
            endpoint=request.url.path,
            identifier=identifier,
            max_calls=endpoint_limit["max_calls"],
            window_sec=endpoint_limit["window_sec"]
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail=str(e))
    
    return await call_next(request)
