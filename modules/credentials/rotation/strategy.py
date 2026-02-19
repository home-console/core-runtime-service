"""Rotation strategy abstraction layer (plugin system)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Dict
from enum import Enum


class RotationStrategyType(Enum):
    """Rotation strategy types."""
    GENERATE_NEW_SECRET = "generate_new_secret"
    AGENT_PUSH = "agent_push"
    WEBHOOK_CALLBACK = "webhook_callback"
    MANUAL = "manual"


@dataclass
class RotationStrategyContext:
    """Context for strategy execution."""
    
    credential_id: str
    current_version: int
    vault_store: Any  # SecretStore
    repository: Any  # CredentialRepository
    audit_binder: Any  # AuditBinder
    trust_engine: Any  # TrustEngine
    risk_engine: Any  # RiskEngine (optional)
    security_orchestrator: Any  # SecurityOrchestrator
    
    # Strategy-specific context
    extra_params: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra_params is None:
            self.extra_params = {}


@dataclass
class RotationResult:
    """Result of a rotation operation."""
    
    success: bool
    new_secret_ref: Optional[str] = None
    new_version: Optional[int] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    audit_event_type: Optional[str] = None
    
    # Metadata for escalation
    should_freeze_account: bool = False
    should_escalate_risk: bool = False
    escalation_reason: Optional[str] = None


class RotationStrategy(ABC):
    """
    Abstract base class for rotation strategies.
    
    Strategies implement the actual rotation logic for different
    scenarios (vault-only, agent push, webhook, etc.).
    
    Requirements:
    - Must be async-safe
    - Must not log secrets
    - Must validate all inputs
    - Must handle idempotency
    - Must integrate with security layers
    """
    
    def __init__(
        self,
        strategy_type: RotationStrategyType,
        name: str,
    ):
        """
        Initialize rotation strategy.
        
        Args:
            strategy_type: Type of strategy (enum)
            name: Human-readable name for logging
        """
        self.strategy_type = strategy_type
        self.name = name
    
    @abstractmethod
    async def execute(
        self,
        context: RotationStrategyContext,
    ) -> RotationResult:
        """
        Execute rotation using this strategy.
        
        Must be idempotent - calling with same inputs should yield
        same result (or succeed if already rotated).
        
        Args:
            context: Execution context with all dependencies
        
        Returns:
            RotationResult with success/failure details
        """
        pass
    
    @abstractmethod
    async def validate(
        self,
        context: RotationStrategyContext,
    ) -> bool:
        """
        Validate that strategy can be executed in current context.
        
        Args:
            context: Execution context
        
        Returns:
            True if strategy can execute, False otherwise
        """
        pass
    
    @abstractmethod
    async def rollback(
        self,
        context: RotationStrategyContext,
        failed_version: int,
        previous_secret_ref: str,
    ) -> bool:
        """
        Rollback a failed rotation to previous state.
        
        Args:
            context: Execution context
            failed_version: Version that failed
            previous_secret_ref: Reference to previous secret
        
        Returns:
            True if rollback succeeded, False otherwise
        """
        pass
    
    async def pre_execute_checks(
        self,
        context: RotationStrategyContext,
    ) -> tuple[bool, Optional[str]]:
        """
        Pre-execution checks before rotation.
        
        Default implementation checks:
        - Account not frozen
        - RBAC permissions
        
        Can be overridden by subclasses for strategy-specific checks.
        
        Args:
            context: Execution context
        
        Returns:
            (allow: bool, reason: Optional[str])
        """
        # Check if account frozen (if trust_engine available)
        if context.trust_engine:
            trust_state = await context.trust_engine.get_state(context.credential_id)
            if trust_state:
                from core.security.trust.trust_state import TrustLevel
                if trust_state.level == TrustLevel.FROZEN:
                    return False, "account_frozen"
        
        return True, None
    
    async def post_execute_checks(
        self,
        context: RotationStrategyContext,
        result: RotationResult,
    ) -> Optional[str]:
        """
        Post-execution validation of rotation result.
        
        Default implementation validates:
        - new_secret_ref is not None on success
        - new_version incremented
        - All required fields populated
        
        Can be overridden by subclasses for strategy-specific validation.
        
        Args:
            context: Execution context
            result: Execution result to validate
        
        Returns:
            Error message if validation failed, None if valid
        """
        if result.success:
            if not result.new_secret_ref:
                return "missing_secret_ref"
            if result.new_version is None:
                return "missing_version"
            if result.new_version <= context.current_version:
                return "invalid_version_increment"
        
        return None
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"


class StrategyExecutionError(Exception):
    """Error during strategy execution."""
    
    def __init__(
        self,
        strategy_name: str,
        message: str,
        error_code: Optional[str] = None,
        should_freeze: bool = False,
        should_escalate: bool = False,
    ):
        self.strategy_name = strategy_name
        self.message = message
        self.error_code = error_code or "strategy_error"
        self.should_freeze = should_freeze
        self.should_escalate = should_escalate
        super().__init__(f"[{strategy_name}] {message}")


class IdempotencyKeyError(StrategyExecutionError):
    """Idempotency key mismatch or error."""
    
    def __init__(self, strategy_name: str, message: str):
        super().__init__(
            strategy_name,
            message,
            error_code="idempotency_error",
        )
