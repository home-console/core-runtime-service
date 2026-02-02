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
    
    # Get CSRF token from header
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token:
        return JSONResponse(status_code=403, content={"detail": "CSRF token required"})
    
    # Get session from request context populated by auth middleware.
    # NOTE: auth middleware stores context in `request.state.auth_context`.
    # Older code used `request.state.context` which caused CSRF checks to
    # always fail (no context) and return 403 even for authenticated sessions.
    ctx = getattr(request.state, "auth_context", None)
    if not ctx:
        return JSONResponse(status_code=403, content={"detail": "Authentication required for CSRF validation"})
    
    # Get session_id for CSRF validation
    session_id = getattr(ctx, "session_id", None) or getattr(ctx, "user_id", None)
    if not session_id:
        return JSONResponse(status_code=403, content={"detail": "Session required for CSRF validation"})
    
    # Validate CSRF token
    try:
        from core.security import CSRFProtection
        csrf = CSRFProtection.from_env()
        csrf.validate_token(csrf_token, session_id)
    except RuntimeError as e:
        # CSRF_SECRET not configured - log warning and allow (fail-open for development)
        # In production, this should fail-closed
        import os
        if os.getenv("ENV", "development") == "production":
            return JSONResponse(status_code=500, content={"detail": "CSRF protection not configured"})
        # Development mode - allow without CSRF
        pass
    except ValueError:
        return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})
    
    return await call_next(request)


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """
    Rate limit admin API endpoints.
    
    SECURITY P0:
    - Prevent abuse of admin endpoints
    - Different limits for different endpoint types
    - Per-user rate limiting
    
    Args:
        request: FastAPI request
        call_next: Next middleware/handler
        
    Returns:
        Response
        
    Raises:
        HTTPException 429: If rate limit exceeded
    """
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
        "/admin/v1/yandex/sync": {"max_calls": 5, "window_sec": 60},
        "/admin/v1/devices": {"max_calls": 100, "window_sec": 60},
        "/admin/v1/inspector/storage": {"max_calls": 100, "window_sec": 60},
        "default": {"max_calls": 200, "window_sec": 60},
    }
    
    # Find matching rate limit
    endpoint_limit = rate_limits.get("default")
    for path_prefix, limit in rate_limits.items():
        if path_prefix != "default" and request.url.path.startswith(path_prefix):
            endpoint_limit = limit
            break
    
    # Check rate limit
    try:
        from core.security import RateLimiter
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
