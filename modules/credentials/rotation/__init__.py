"""Credential rotation engine module.

Provides automated credential lifecycle management:
- Scheduled automatic rotation
- Manual rotation
- State tracking
- Audit logging
- Plugin-based rotation strategies
"""

from .policy import (
    RotationPolicy,
    RotationStrategy,
    RotationStatus,
    RotationState,
)
from .executor import RotationExecutor
from .executor_v2 import RotationExecutor as RotationExecutorV2
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
# Strategy plugin system
from .strategy import (
    RotationStrategy as RotationStrategyBase,
    RotationStrategyType,
    RotationStrategyContext,
    RotationResult,
    StrategyExecutionError,
    IdempotencyKeyError,
)
from .registry import StrategyRegistry
from .strategies import (
    GenerateNewSecretStrategy,
    AgentPushStrategy,
    WebhookRotationStrategy,
)

__all__ = [
    # Policy
    "RotationPolicy",
    "RotationStrategy",
    "RotationStatus",
    "RotationState",
    # Components
    "RotationExecutor",
    "RotationExecutorV2",
    "RotationScheduler",
    "CredentialRotationEngine",
    # Strategy System
    "RotationStrategyBase",
    "RotationStrategyType",
    "RotationStrategyContext",
    "RotationResult",
    "StrategyRegistry",
    # Built-in Strategies
    "GenerateNewSecretStrategy",
    "AgentPushStrategy",
    "WebhookRotationStrategy",
    # Exceptions
    "RotationException",
    "RotationFailedError",
    "RotationNotAllowedError",
    "RotationTimeoutError",
    "RotationCancelledError",
    "SecretGenerationError",
    "StrategyExecutionError",
    "IdempotencyKeyError",
    # Utilities
    "generate_strong_secret",
    "generate_api_token",
    "generate_database_password",
    "calculate_entropy_bits",
]
