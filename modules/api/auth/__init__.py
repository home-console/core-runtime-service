"""
Authentication module — boundary-layer для ApiModule и AdminModule.

Это boundary-layer: auth логика НЕ проникает в CoreRuntime, RuntimeModule,
ServiceRegistry или доменные модули. Всё изолировано на уровне HTTP.

Экспортирует все публичные функции для обратной совместимости.
"""

# Core types
from .context import RequestContext

# Constants
from .constants import (
    AUTH_API_KEYS_NAMESPACE,
    AUTH_SESSIONS_NAMESPACE,
    AUTH_USERS_NAMESPACE,
    AUTH_RATE_LIMITS_NAMESPACE,
    AUTH_AUDIT_LOG_NAMESPACE,
    AUTH_REVOKED_NAMESPACE,
    AUTH_REFRESH_TOKENS_NAMESPACE,
    DEFAULT_SESSION_EXPIRATION_SECONDS,
    ACCESS_TOKEN_EXPIRATION_SECONDS,
    REFRESH_TOKEN_EXPIRATION_SECONDS,
    RATE_LIMIT_AUTH_ATTEMPTS,
    RATE_LIMIT_AUTH_WINDOW,
    RATE_LIMIT_API_REQUESTS,
    RATE_LIMIT_API_WINDOW,
    MIN_PASSWORD_LENGTH,
    MAX_PASSWORD_LENGTH,
)

# API Keys
from .api_keys import (
    validate_api_key,
    create_api_key,
    extract_api_key_from_header,
    rotate_api_key,
)

# Sessions
from .sessions import (
    validate_session,
    create_session,
    delete_session,
    list_sessions,
    revoke_all_sessions,
    extract_session_from_cookie,
)

# JWT Tokens
from .jwt_tokens import (
    get_or_create_jwt_secret,
    generate_access_token,
    validate_access_token,
    validate_jwt_token,
    create_refresh_token,
    validate_refresh_token,
    refresh_access_token,
    extract_jwt_from_header,
)

# Passwords
from .passwords import (
    hash_password,
    verify_password,
    validate_password_strength,
    set_password,
    change_password,
    verify_user_password,
)

# Revocation
from .revocation import (
    revoke_api_key,
    revoke_session,
    revoke_refresh_token,
    is_revoked,
)

# Audit
from .audit import audit_log_auth_event

# Users
from .users import (
    validate_user_exists,
    create_user,
)

# Utils
from .utils import (
    validate_scopes,
    check_service_scope,
)

# Rate Limiting
from .rate_limiting import rate_limit_check

# Middleware
from .middleware import (
    require_auth_middleware,
    get_request_context,
)

__all__ = [
    # Types
    "RequestContext",
    # Constants
    "AUTH_API_KEYS_NAMESPACE",
    "AUTH_SESSIONS_NAMESPACE",
    "AUTH_USERS_NAMESPACE",
    "AUTH_RATE_LIMITS_NAMESPACE",
    "AUTH_AUDIT_LOG_NAMESPACE",
    "AUTH_REVOKED_NAMESPACE",
    "AUTH_REFRESH_TOKENS_NAMESPACE",
    "DEFAULT_SESSION_EXPIRATION_SECONDS",
    "ACCESS_TOKEN_EXPIRATION_SECONDS",
    "REFRESH_TOKEN_EXPIRATION_SECONDS",
    # API Keys
    "validate_api_key",
    "create_api_key",
    "extract_api_key_from_header",
    "rotate_api_key",
    # Sessions
    "validate_session",
    "create_session",
    "delete_session",
    "list_sessions",
    "revoke_all_sessions",
    "extract_session_from_cookie",
    # JWT Tokens
    "get_or_create_jwt_secret",
    "generate_access_token",
    "validate_access_token",
    "validate_jwt_token",
    "create_refresh_token",
    "validate_refresh_token",
    "refresh_access_token",
    "extract_jwt_from_header",
    # Passwords
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "set_password",
    "change_password",
    "verify_user_password",
    # Revocation
    "revoke_api_key",
    "revoke_session",
    "revoke_refresh_token",
    "is_revoked",
    # Audit
    "audit_log_auth_event",
    # Users
    "validate_user_exists",
    "create_user",
    # Utils
    "validate_scopes",
    "check_service_scope",
    # Rate Limiting
    "rate_limit_check",
    # Middleware
    "require_auth_middleware",
    "get_request_context",
]
