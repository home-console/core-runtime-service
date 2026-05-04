"""Credential rotation execution logic (strategy-based)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .exceptions import RotationFailedError, RotationNotAllowedError
from .policy import RotationPolicy
from .policy import RotationStrategy as PolicyStrategy
from .registry import StrategyRegistry
from .strategy import RotationStrategyContext, RotationStrategyType
from modules.domain import TrustLevel

logger = logging.getLogger(__name__)


class RotationExecutor:
    """
    Executes credential rotation atomically using strategy pattern.

    Responsibilities:
    - Select appropriate rotation strategy
    - Execute rotation atomically through strategy
    - Update vault storage
    - Increment version
    - Track audit events
    - Rollback on failure

    Strategies are pluggable and registered with StrategyRegistry.
    """

    def __init__(
        self,
        vault_store: Any,  # SecretStore implementation
        repository: Any,  # CredentialRepository
        audit_binder: Any,  # AuditBinder for logging
        strategy_registry: StrategyRegistry,  # Plugin registry
        security_orchestrator: Optional[Any] = None,
        trust_engine: Optional[Any] = None,
        risk_engine: Optional[Any] = None,
    ):
        self.vault_store = vault_store
        self.repository = repository
        self.audit_binder = audit_binder
        self.strategy_registry = strategy_registry
        self.security_orchestrator = security_orchestrator
        self.trust_engine = trust_engine
        self.risk_engine = risk_engine

    async def execute_rotation(
        self,
        credential_id: str,
        rotation_policy: RotationPolicy,
        current_version: int,
        extra_context: Optional[dict[str, Any]] = None,
    ) -> tuple[str, int]:
        try:
            if self.trust_engine:
                trust_state = await self.trust_engine.get_state(credential_id)

                if trust_state and trust_state.level == TrustLevel.FROZEN:
                    await self.audit_binder.append_event(
                        event_type="credential_rotation_denied",
                        metadata={
                            "credential_id": credential_id,
                            "reason": "account_frozen",
                        },
                    )
                    raise RotationNotAllowedError(
                        f"Cannot rotate {credential_id}: account frozen"
                    )

            strategy_type = self._map_policy_to_strategy(rotation_policy.strategy)
            if strategy_type == RotationStrategyType.MANUAL:
                raise RotationNotAllowedError(
                    "Cannot auto-rotate with MANUAL strategy"
                )

            strategy = await self.strategy_registry.get_or_fail(strategy_type)

            context = RotationStrategyContext(
                credential_id=credential_id,
                current_version=current_version,
                vault_store=self.vault_store,
                repository=self.repository,
                audit_binder=self.audit_binder,
                trust_engine=self.trust_engine,
                risk_engine=self.risk_engine,
                security_orchestrator=self.security_orchestrator,
                extra_params=extra_context or {},
            )

            if not await strategy.validate(context):
                await self.audit_binder.append_event(
                    event_type="credential_rotation_validation_failed",
                    metadata={
                        "credential_id": credential_id,
                        "strategy": strategy.name,
                    },
                )
                raise RotationFailedError(
                    f"Strategy validation failed for {credential_id}"
                )

            await self.audit_binder.append_event(
                event_type="credential_rotation_started",
                metadata={
                    "credential_id": credential_id,
                    "strategy": strategy.name,
                    "new_version": current_version + 1,
                },
            )

            result = await strategy.execute(context)

            if not result.success:
                await self.audit_binder.append_event(
                    event_type="credential_rotation_failed",
                    metadata={
                        "credential_id": credential_id,
                        "strategy": strategy.name,
                        "error": result.error_code,
                    },
                )

                if result.should_freeze_account and self.trust_engine:
                    await self.trust_engine.freeze(credential_id)
                if result.should_escalate_risk and self.risk_engine:
                    await self.risk_engine.escalate(credential_id)

                raise RotationFailedError(result.error_message)

            if result.new_secret_ref is None or result.new_version is None:
                raise RotationFailedError(
                    "Strategy returned success but missing secret_ref or version"
                )

            credential = await self.repository.get(credential_id)
            updated_credential = credential.mutate(
                version=result.new_version,
                secret_ref=result.new_secret_ref,
            )
            await self.repository.update(updated_credential)

            await self.audit_binder.append_event(
                event_type=result.audit_event_type or "credential_rotated",
                metadata={
                    "credential_id": credential_id,
                    "new_version": result.new_version,
                    "strategy": strategy.name,
                },
            )

            return result.new_secret_ref, result.new_version

        except RotationNotAllowedError:
            raise
        except RotationFailedError:
            raise
        except Exception as e:
            await self.audit_binder.append_event(
                event_type="credential_rotation_error",
                metadata={
                    "credential_id": credential_id,
                    "error": str(e),
                },
            )
            raise RotationFailedError(f"Rotation execution failed: {str(e)}")

    async def execute_manual_rotation(
        self,
        credential_id: str,
        new_secret: str,
        current_version: int,
    ) -> tuple[str, int]:
        try:
            if self.trust_engine:
                trust_state = await self.trust_engine.get_state(credential_id)

                if trust_state and trust_state.level == TrustLevel.FROZEN:
                    raise RotationNotAllowedError(
                        f"Cannot rotate {credential_id}: account frozen"
                    )

            new_version = current_version + 1
            vault_key = f"{credential_id}:v{new_version}:manual"

            await self.vault_store.store_secret(
                key=vault_key,
                value=new_secret,
            )

            credential = await self.repository.get(credential_id)
            updated = credential.mutate(
                version=new_version,
                secret_ref=vault_key,
            )
            await self.repository.update(updated)

            await self.audit_binder.append_event(
                event_type="credential_rotated_manual",
                metadata={
                    "credential_id": credential_id,
                    "new_version": new_version,
                },
            )

            return vault_key, new_version

        except RotationNotAllowedError:
            raise
        except Exception as e:
            await self.audit_binder.append_event(
                event_type="credential_rotation_manual_failed",
                metadata={
                    "credential_id": credential_id,
                    "error": str(e),
                },
            )
            raise RotationFailedError(f"Manual rotation failed: {str(e)}")

    async def rollback_rotation(
        self,
        credential_id: str,
        failed_version: int,
        previous_secret_ref: str,
    ) -> bool:
        try:
            credential = await self.repository.get(credential_id)
            if not credential.rotation_policy:
                return False

            policy = RotationPolicy.from_dict(credential.rotation_policy)
            strategy_type = self._map_policy_to_strategy(policy.strategy)
            strategy = await self.strategy_registry.get(strategy_type)

            if not strategy:
                return False

            context = RotationStrategyContext(
                credential_id=credential_id,
                current_version=failed_version,
                vault_store=self.vault_store,
                repository=self.repository,
                audit_binder=self.audit_binder,
                trust_engine=self.trust_engine,
                risk_engine=self.risk_engine,
                security_orchestrator=self.security_orchestrator,
            )

            success = await strategy.rollback(
                context,
                failed_version,
                previous_secret_ref,
            )

            if success:
                updated = credential.mutate(
                    version=failed_version - 1,
                    secret_ref=previous_secret_ref,
                )
                await self.repository.update(updated)

            return success

        except Exception as e:
            logger.warning(
                "executor.rollback_rotation: unexpected error: %s",
                e,
                exc_info=True,
            )
            await self.audit_binder.append_event(
                event_type="credential_rotation_rollback_failed",
                metadata={
                    "credential_id": credential_id,
                    "error": str(e),
                },
            )
            return False

    def _map_policy_to_strategy(
        self,
        policy_strategy: PolicyStrategy,
    ) -> RotationStrategyType:
        strategy_map = {
            PolicyStrategy.GENERATE_NEW_SECRET: RotationStrategyType.GENERATE_NEW_SECRET,
            PolicyStrategy.AGENT_PUSH: RotationStrategyType.AGENT_PUSH,
            PolicyStrategy.CALLBACK_WEBHOOK: RotationStrategyType.WEBHOOK_CALLBACK,
            PolicyStrategy.MANUAL: RotationStrategyType.MANUAL,
        }

        return strategy_map.get(
            policy_strategy,
            RotationStrategyType.GENERATE_NEW_SECRET,
        )
