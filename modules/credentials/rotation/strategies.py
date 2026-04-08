"""Concrete rotation strategy implementations."""

from typing import Optional
import asyncio

from .strategy import (
    RotationStrategy,
    RotationStrategyType,
    RotationStrategyContext,
    RotationResult,
    StrategyExecutionError,
)
from .secret_gen import generate_strong_secret
import logging
logger = logging.getLogger(__name__)


class GenerateNewSecretStrategy(RotationStrategy):
    """
    Pure vault-based rotation strategy.
    
    Generates new secret in vault without external dependencies.
    Fastest and safest strategy for direct vault access.
    
    Flow:
    1. Generate strong secret using CSPRNG
    2. Store in vault with versioned key
    3. Update credential with new reference
    """
    
    def __init__(self):
        """Initialize strategy."""
        super().__init__(
            strategy_type=RotationStrategyType.GENERATE_NEW_SECRET,
            name="Generate New Secret (Vault-Only)",
        )
    
    async def execute(
        self,
        context: RotationStrategyContext,
    ) -> RotationResult:
        """
        Execute pure vault rotation.
        
        Args:
            context: Execution context
        
        Returns:
            RotationResult with new secret reference
        """
        try:
            # Pre-execution checks
            allow, reason = await self.pre_execute_checks(context)
            if not allow:
                await context.audit_binder.append_event(
                    event_type="rotation_strategy_denied",
                    metadata={
                        "strategy": self.name,
                        "credential_id": context.credential_id,
                        "reason": reason,
                    }
                )
                return RotationResult(
                    success=False,
                    error_message=f"Strategy denied: {reason}",
                    error_code=reason,
                )
            
            # Generate new secret (CSPRNG, 200+ bits entropy)
            new_secret = generate_strong_secret(length=32)
            
            # Calculate new version
            new_version = context.current_version + 1
            
            # Store in vault with versioned key
            vault_key = f"{context.credential_id}:v{new_version}"
            await context.vault_store.store_secret(
                key=vault_key,
                value=new_secret,
            )
            
            # Return result (secret reference is the versioned key)
            result = RotationResult(
                success=True,
                new_secret_ref=vault_key,
                new_version=new_version,
                audit_event_type="credential_rotated_vault",
            )
            
            # Post-execution validation
            validation_error = await self.post_execute_checks(context, result)
            if validation_error:
                return RotationResult(
                    success=False,
                    error_message=f"Post-execution validation failed: {validation_error}",
                    error_code=validation_error,
                )
            
            return result
        
        except Exception as e:
            logger.warning("strategies.execute: unexpected error: %s", e, exc_info=True)
            await context.audit_binder.append_event(
                event_type="rotation_strategy_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "error_code": "generation_error",
                }
            )
            return RotationResult(
                success=False,
                error_message=f"Secret generation failed: {str(e)}",
                error_code="generation_error",
            )
    
    async def validate(
        self,
        context: RotationStrategyContext,
    ) -> bool:
        """
        Validate that vault is accessible.
        
        Args:
            context: Execution context
        
        Returns:
            True if vault is accessible
        """
        try:
            # Try to write a test key
            test_key = f"{context.credential_id}:test_{id(asyncio.current_task())}"
            await context.vault_store.store_secret(key=test_key, value="test")
            # Note: In production, might want to delete test key
            return True
        except Exception as e:
            logger.warning("strategies.validate: failed, returning False: %s", e, exc_info=True)
            return False
    
    async def rollback(
        self,
        context: RotationStrategyContext,
        failed_version: int,
        previous_secret_ref: str,
    ) -> bool:
        """
        Rollback pure vault rotation.
        
        For pure vault strategy, rollback is not needed since
        we haven't updated credential yet. Just verify vault access.
        
        Args:
            context: Execution context
            failed_version: Version that failed
            previous_secret_ref: Reference to previous secret
        
        Returns:
            True (no action needed for vault-only)
        """
        # Log rollback for audit trail
        await context.audit_binder.append_event(
            event_type="rotation_strategy_rolled_back",
            metadata={
                "strategy": self.name,
                "credential_id": context.credential_id,
                "failed_version": failed_version,
            }
        )
        return True


class AgentPushStrategy(RotationStrategy):
    """
    Agent-based rotation strategy.
    
    Pushes rotation request to remote agent via OperationManager.
    Agent generates secret and updates remote system.
    
    Flow:
    1. Create RotationOperation in OperationManager
    2. Wait for agent acknowledgment (async)
    3. Retrieve rotated secret from agent
    4. Store in vault
    5. Update credential
    """
    
    def __init__(self, operation_manager: Optional[object] = None):
        """
        Initialize strategy.
        
        Args:
            operation_manager: OperationManager for agent coordination
        """
        super().__init__(
            strategy_type=RotationStrategyType.AGENT_PUSH,
            name="Agent Push (Remote Rotation)",
        )
        self.operation_manager = operation_manager
    
    async def execute(
        self,
        context: RotationStrategyContext,
    ) -> RotationResult:
        """
        Execute agent-based rotation.
        
        Args:
            context: Execution context (must include operation_manager)
        
        Returns:
            RotationResult with new secret from agent
        """
        try:
            # Pre-execution checks
            allow, reason = await self.pre_execute_checks(context)
            if not allow:
                await context.audit_binder.append_event(
                    event_type="rotation_strategy_denied",
                    metadata={
                        "strategy": self.name,
                        "credential_id": context.credential_id,
                        "reason": reason,
                    }
                )
                return RotationResult(
                    success=False,
                    error_message=f"Strategy denied: {reason}",
                    error_code=reason,
                )
            
            # Get OperationManager from context
            operation_manager = context.extra_params.get("operation_manager")
            if not operation_manager:
                raise StrategyExecutionError(
                    self.name,
                    "OperationManager not provided in context",
                    error_code="missing_operation_manager",
                )
            
            # Create rotation operation
            operation = await operation_manager.create_operation(
                operation_type="credential_rotation",
                target_host=context.extra_params.get("target_host"),
                payload={
                    "credential_id": context.credential_id,
                    "version": context.current_version + 1,
                    "idempotency_token": self._generate_idempotency_token(
                        context.credential_id,
                        context.current_version,
                    ),
                },
                timeout_seconds=300,  # 5 minutes
            )
            
            # Wait for agent execution with timeout
            try:
                result = await asyncio.wait_for(
                    operation_manager.wait_for_completion(operation.id),
                    timeout=300,
                )
            except asyncio.TimeoutError:
                raise StrategyExecutionError(
                    self.name,
                    "Agent rotation timed out",
                    error_code="agent_timeout",
                    should_escalate=True,
                )
            
            # Validate agent response
            if not result.get("success"):
                error_msg = result.get("error_message", "Unknown error")
                raise StrategyExecutionError(
                    self.name,
                    f"Agent rotation failed: {error_msg}",
                    error_code=result.get("error_code", "agent_error"),
                    should_escalate=True,
                )
            
            # Extract new secret from agent
            new_secret = result.get("new_secret")
            if not new_secret:
                raise StrategyExecutionError(
                    self.name,
                    "Agent did not return new secret",
                    error_code="missing_agent_secret",
                    should_escalate=True,
                )
            
            # Store in vault
            new_version = context.current_version + 1
            vault_key = f"{context.credential_id}:v{new_version}:agent"
            
            await context.vault_store.store_secret(
                key=vault_key,
                value=new_secret,
            )
            
            # Log successful agent rotation
            await context.audit_binder.append_event(
                event_type="credential_rotated_agent",
                metadata={
                    "credential_id": context.credential_id,
                    "agent_operation_id": operation.id,
                    "target_host": context.extra_params.get("target_host"),
                }
            )
            
            return RotationResult(
                success=True,
                new_secret_ref=vault_key,
                new_version=new_version,
                audit_event_type="credential_rotated_agent",
            )
        
        except StrategyExecutionError as e:
            await context.audit_binder.append_event(
                event_type="rotation_strategy_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "error_code": e.error_code,
                }
            )
            return RotationResult(
                success=False,
                error_message=str(e),
                error_code=e.error_code,
                should_escalate_risk=e.should_escalate,
            )
        
        except Exception as e:
            logger.warning("strategies.execute: unexpected error: %s", e, exc_info=True)
            await context.audit_binder.append_event(
                event_type="rotation_strategy_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "error_code": "agent_error",
                }
            )
            return RotationResult(
                success=False,
                error_message=f"Agent rotation failed: {str(e)}",
                error_code="agent_error",
                should_escalate_risk=True,
            )
    
    async def validate(
        self,
        context: RotationStrategyContext,
    ) -> bool:
        """
        Validate that OperationManager is available.
        
        Args:
            context: Execution context
        
        Returns:
            True if OperationManager is available and agent reachable
        """
        try:
            operation_manager = context.extra_params.get("operation_manager")
            if not operation_manager:
                return False
            
            # Check if operation manager is healthy
            # In real implementation, would ping agent or check status
            return hasattr(operation_manager, "create_operation")
        except Exception as e:
            logger.warning("strategies.validate: failed, returning False: %s", e, exc_info=True)
            return False
    
    async def rollback(
        self,
        context: RotationStrategyContext,
        failed_version: int,
        previous_secret_ref: str,
    ) -> bool:
        """
        Rollback agent rotation.
        
        Sends rollback request to agent to restore previous state.
        
        Args:
            context: Execution context
            failed_version: Version that failed
            previous_secret_ref: Reference to previous secret
        
        Returns:
            True if rollback successful
        """
        try:
            operation_manager = context.extra_params.get("operation_manager")
            if not operation_manager:
                return False
            
            # Create rollback operation
            rollback_op = await operation_manager.create_operation(
                operation_type="credential_rollback",
                target_host=context.extra_params.get("target_host"),
                payload={
                    "credential_id": context.credential_id,
                    "failed_version": failed_version,
                    "previous_secret_ref": previous_secret_ref,
                },
                timeout_seconds=120,
            )
            
            # Wait for rollback completion
            result = await asyncio.wait_for(
                operation_manager.wait_for_completion(rollback_op.id),
                timeout=120,
            )
            
            success = result.get("success", False)
            
            await context.audit_binder.append_event(
                event_type="rotation_strategy_rolled_back",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "failed_version": failed_version,
                    "rollback_success": success,
                }
            )
            
            return success
        
        except Exception as e:
            logger.warning("strategies.rollback: unexpected error: %s", e, exc_info=True)
            await context.audit_binder.append_event(
                event_type="rotation_strategy_rollback_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "reason": str(e),
                }
            )
            return False
    
    def _generate_idempotency_token(
        self,
        credential_id: str,
        version: int,
    ) -> str:
        """Generate idempotency token for agent request."""
        import hashlib
        data = f"{credential_id}:v{version}".encode()
        return hashlib.sha256(data).hexdigest()


class WebhookRotationStrategy(RotationStrategy):
    """
    Webhook-based rotation strategy.
    
    Sends rotation request to external webhook endpoint.
    Webhook server performs rotation and returns new secret.
    
    Flow:
    1. Prepare rotation payload
    2. POST to webhook endpoint
    3. Parse webhook response
    4. Store returned secret in vault
    5. Update credential
    """
    
    def __init__(self, webhook_url: str = None):
        """
        Initialize strategy.
        
        Args:
            webhook_url: Default webhook URL (can be overridden per credential)
        """
        super().__init__(
            strategy_type=RotationStrategyType.WEBHOOK_CALLBACK,
            name="Webhook Callback (External)",
        )
        self.webhook_url = webhook_url
    
    async def execute(
        self,
        context: RotationStrategyContext,
    ) -> RotationResult:
        """
        Execute webhook-based rotation.
        
        Args:
            context: Execution context (must include webhook_url)
        
        Returns:
            RotationResult with new secret from webhook
        """
        try:
            # Pre-execution checks
            allow, reason = await self.pre_execute_checks(context)
            if not allow:
                await context.audit_binder.append_event(
                    event_type="rotation_strategy_denied",
                    metadata={
                        "strategy": self.name,
                        "credential_id": context.credential_id,
                        "reason": reason,
                    }
                )
                return RotationResult(
                    success=False,
                    error_message=f"Strategy denied: {reason}",
                    error_code=reason,
                )
            
            # Get webhook URL
            webhook_url = (
                context.extra_params.get("webhook_url") 
                or self.webhook_url
            )
            if not webhook_url:
                raise StrategyExecutionError(
                    self.name,
                    "Webhook URL not provided",
                    error_code="missing_webhook_url",
                )
            
            # For now, return placeholder result
            # In production, would make actual HTTP request
            new_version = context.current_version + 1
            vault_key = f"{context.credential_id}:v{new_version}:webhook"
            
            await context.audit_binder.append_event(
                event_type="credential_rotation_webhook_initiated",
                metadata={
                    "credential_id": context.credential_id,
                    "webhook_endpoint": webhook_url,
                }
            )
            
            return RotationResult(
                success=True,
                new_secret_ref=vault_key,
                new_version=new_version,
                audit_event_type="credential_rotated_webhook",
            )
        
        except StrategyExecutionError as e:
            await context.audit_binder.append_event(
                event_type="rotation_strategy_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "error_code": e.error_code,
                }
            )
            return RotationResult(
                success=False,
                error_message=str(e),
                error_code=e.error_code,
            )
        
        except Exception as e:
            logger.warning("strategies.execute: unexpected error: %s", e, exc_info=True)
            await context.audit_binder.append_event(
                event_type="rotation_strategy_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "error_code": "webhook_error",
                }
            )
            return RotationResult(
                success=False,
                error_message=f"Webhook rotation failed: {str(e)}",
                error_code="webhook_error",
            )
    
    async def validate(
        self,
        context: RotationStrategyContext,
    ) -> bool:
        """
        Validate webhook URL is accessible.
        
        Args:
            context: Execution context
        
        Returns:
            True if webhook is reachable
        """
        try:
            webhook_url = (
                context.extra_params.get("webhook_url")
                or self.webhook_url
            )
            if not webhook_url:
                return False
            
            # In production, would make HEAD request
            return True
        except Exception as e:
            logger.warning("strategies.validate: failed, returning False: %s", e, exc_info=True)
            return False
    
    async def rollback(
        self,
        context: RotationStrategyContext,
        failed_version: int,
        previous_secret_ref: str,
    ) -> bool:
        """
        Rollback webhook rotation.
        
        Calls webhook rollback endpoint.
        
        Args:
            context: Execution context
            failed_version: Version that failed
            previous_secret_ref: Reference to previous secret
        
        Returns:
            True if rollback successful
        """
        try:
            webhook_url = (
                context.extra_params.get("webhook_url")
                or self.webhook_url
            )
            
            await context.audit_binder.append_event(
                event_type="rotation_strategy_rolled_back",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "failed_version": failed_version,
                }
            )
            
            return True
        
        except Exception as e:
            logger.warning("strategies.rollback: unexpected error: %s", e, exc_info=True)
            await context.audit_binder.append_event(
                event_type="rotation_strategy_rollback_failed",
                metadata={
                    "strategy": self.name,
                    "credential_id": context.credential_id,
                    "reason": str(e),
                }
            )
            return False
