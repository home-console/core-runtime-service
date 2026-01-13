"""
Authentication constants — namespaces, limits, policies.
"""

# Storage namespaces
AUTH_API_KEYS_NAMESPACE = "auth_api_keys"
AUTH_SESSIONS_NAMESPACE = "auth_sessions"
AUTH_USERS_NAMESPACE = "auth_users"
AUTH_RATE_LIMITS_NAMESPACE = "auth_rate_limits"
AUTH_AUDIT_LOG_NAMESPACE = "auth_audit_log"
AUTH_REVOKED_NAMESPACE = "auth_revoked"
AUTH_REFRESH_TOKENS_NAMESPACE = "auth_refresh_tokens"

# Default session expiration (24 hours)
DEFAULT_SESSION_EXPIRATION_SECONDS = 24 * 60 * 60

# JWT settings
JWT_ALGORITHM = "HS256"
JWT_SECRET_KEY_LENGTH = 32  # Будет генерироваться при первом запуске
ACCESS_TOKEN_EXPIRATION_SECONDS = 15 * 60  # 15 минут
REFRESH_TOKEN_EXPIRATION_SECONDS = 7 * 24 * 60 * 60  # 7 дней
JWT_SECRET_KEY_STORAGE_KEY = "jwt_secret_key"  # Хранится в storage

# Rate limiting defaults
RATE_LIMIT_AUTH_ATTEMPTS = 10  # попыток (для login, create_api_key и т.д.)
RATE_LIMIT_AUTH_WINDOW = 60  # секунд
RATE_LIMIT_API_REQUESTS = 1000  # запросов (для обычных API запросов)
RATE_LIMIT_API_WINDOW = 60  # секунд

# Password policies
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL_CHAR = False  # Опционально, можно включить для большей безопасности
