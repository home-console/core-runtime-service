"""
Security utilities для Core Runtime API.

Модуль содержит инструменты для защиты от распространённых уязвимостей:
- URL validation (SSRF protection)
- Idempotency support (race condition prevention)
"""

from .url_validator import (
    validate_external_url,
    validate_url_for_plugin,
    is_private_ip,
    is_allowed_scheme,
)
from .idempotency import (
    get_idempotency_key,
    idempotency_middleware,
    periodic_cleanup,
    IdempotencyStore,
)

__all__ = [
    # URL validation
    "validate_external_url",
    "validate_url_for_plugin",
    "is_private_ip",
    "is_allowed_scheme",
    
    # Idempotency
    "get_idempotency_key",
    "idempotency_middleware",
    "periodic_cleanup",
    "IdempotencyStore",
]
