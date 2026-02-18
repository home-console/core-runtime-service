"""Credential rotation engine module.

Provides automated credential lifecycle management:
- Scheduled automatic rotation
- Manual rotation
- State tracking
- Audit logging
"""

from .policy import (
    RotationPolicy,
    RotationStrategy,
    RotationStatus,
    RotationState,
)
from .executor import RotationExecutor
from .scheduler import RotationScheduler
from .engine import CredentialRotationEngine
from .exceptions import (
    RotationException,
    RotationFailedError,
    RotationNotAllowedError,
    RotationTimeoutError,
    RotationCancelledError,
    SecretGenerationError,
)
from .secret_gen import (
    generate_strong_secret,
    generate_api_token,
    generate_database_password,
    calculate_entropy_bits,
)

__all__ = [
    # Policy
    "RotationPolicy",
    "RotationStrategy",
    "RotationStatus",
    "RotationState",
    # Components
    "RotationExecutor",
    "RotationScheduler",
    "CredentialRotationEngine",
    # Exceptions
    "RotationException",
    "RotationFailedError",
    "RotationNotAllowedError",
    "RotationTimeoutError",
    "RotationCancelledError",
    "SecretGenerationError",
    # Utilities
    "generate_strong_secret",
    "generate_api_token",
    "generate_database_password",
    "calculate_entropy_bits",
]
