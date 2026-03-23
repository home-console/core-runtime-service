"""
OperationExecutor - выполнение операций.

Отвечает за выполнение операций через различные backends (in_process, process, container, remote).
"""

import asyncio
import time
from typing import Any, Dict, Optional

from core import capability_protocol
from core.health_monitor import ProviderHealthMonitor
from core.operations.interface import IOperationExecutor
from core.operations.models import (
    AttemptStatus,
    RETRYABLE_ERRORS,
    Attempt,
    Operation,
    OperationError,
    OperationStatus,
)
from core.operations.registry import OperationHandlerRegistry, get_operation_handler


class OperationExecutor(IOperationExecutor):
    """
    Исполнитель операций.

    Реализует интерфейс IOperationExecutor и отвечает за выполнение операций
    через различные execution backends (in_process, process, container, remote).

    Supports:
        - Local operation execution via registered handlers
        - Remote operation execution via HTTP (Capability Protocol v1)
        - Health monitoring and automatic failover
        - Per-capability timeout configuration
        - Automatic retry on transient failures
    """

    def __init__(self, registry: OperationHandlerRegistry, runtime: Any, storage: Any):
        """
        Инициализация исполнителя.

        Args:
            registry: Реестр обработчиков операций
            runtime: Экземпляр CoreRuntime
            storage: OperationStorage для персистентности
        """
        self.registry = registry
        self.runtime = runtime
        self.storage = storage
        # Health monitor for remote providers (Protocol v1)
        self._health_monitor = ProviderHealthMonitor()

    def _find_remote_provider(self, operation_type: str) -> Optional[Dict[str, Any]]:
        """
        Find remote provider for operation type (capability).

        Args:
            operation_type: Operation type (should be capability name)

        Returns:
            Provider info dict: {"name": "...", "type": "remote", "remote_config": {...}}
            or None if no remote provider found
        """
        try:
            if (
                hasattr(self.runtime, "capability_registry")
                and self.runtime.capability_registry
            ):
                cap_reg = self.runtime.capability_registry

                # Сначала пробуем select_provider_for для получения метаданных
                provider_metadata = cap_reg.select_provider_for(operation_type)
                if provider_metadata and provider_metadata.provider_type == "remote":
                    # Конвертируем ProviderMetadata обратно в dict для совместимости
                    return {
                        "plugin": provider_metadata.plugin_name,
                        "type": provider_metadata.provider_type,
                        "remote_config": provider_metadata.remote_config or {},
                        "timeouts": provider_metadata.timeouts or {},
                        "protocol_version": provider_metadata.protocol_version,
                        "provider_version": provider_metadata.provider_version,
                    }

                # Если select_provider_for вернул локальный или None, ищем remote вручную
                # (для случаев, когда нужен именно remote, а не просто первый провайдер)
                all_providers = cap_reg.get_all_providers_for_capability(operation_type)
                for provider_info in all_providers:
                    if provider_info.get("type") == "remote":
                        return provider_info
        except Exception:
            pass

        return None

    async def _execute_remote_operation(
        self, operation: Operation, provider_info: Dict[str, Any], retry_count: int = 0
    ) -> Operation:
        """
        Execute operation on remote provider via HTTP.

        Поддерживает Capability Protocol v1:
        - Protocol version negotiation
        - Health monitoring and recording
        - Retryable error handling
        - Per-capability timeouts from manifest
        - Auto-retry on transient failures

        Args:
            operation: Operation to execute
            provider_info: Remote provider metadata with protocol info
            retry_count: Current retry attempt (for diagnostics)

        Returns:
            Operation with updated status and result/error
        """
        from core.remote_executor import RemoteOperationExecutor

        provider_name = provider_info.get("plugin") or "unknown"

        # Mark as running
        operation.status = OperationStatus.RUNNING
        operation.started_at = time.time()
        await self.storage.persist(operation)

        try:
            # Get remote config and timeout
            remote_config = provider_info.get("remote_config", {})
            base_url = remote_config.get("base_url")

            # Use per-capability timeout from manifest if available, else default
            timeouts = provider_info.get("timeouts", {})
            timeout = timeouts.get(
                operation.type, capability_protocol.DEFAULT_CAPABILITY_TIMEOUT
            )

            if not base_url:
                raise ValueError("Remote provider missing base_url in config")

            # Prepare execution context
            context = {
                "operation_id": operation.operation_id,
                "initiator": operation.initiator.to_dict()
                if operation.initiator
                else None,
            }

            # Execute with Protocol v1
            response = await RemoteOperationExecutor.execute_remote(
                base_url=base_url,
                capability=operation.type,
                operation_id=operation.operation_id,
                params=operation.params,
                context=context,
                timeout=timeout,
            )

            # Record success in health monitor
            self._health_monitor.record_success(provider_name)
            provider_info["healthy"] = True

            # Handle response
            if response.get("status") == "success":
                # Success
                operation.status = OperationStatus.COMPLETED
                operation.result = response.get("result", {})
            else:
                # Remote provider returned error
                error_info = response.get("error", {})
                operation.status = OperationStatus.FAILED
                is_retryable = RemoteOperationExecutor.is_error_retryable(response)

                operation.error = OperationError(
                    code=error_info.get("code", "remote_error"),
                    message=error_info.get("message", "Remote provider error"),
                )

                # Record failure for health tracking
                self._health_monitor.record_failure(
                    provider_name,
                    f"{error_info.get('code')}: {error_info.get('message')}",
                )

                # If retryable and we haven't exceeded retry limit → try alternative provider
                if (
                    is_retryable
                    and retry_count < capability_protocol.MAX_RETRIES_PER_OPERATION
                ):
                    # Try next provider from registry
                    if (
                        hasattr(self.runtime, "capability_registry")
                        and self.runtime.capability_registry
                    ):
                        cap_reg = self.runtime.capability_registry
                        all_providers = cap_reg.get_all_providers_for_capability(
                            operation.type
                        )

                        # Skip current provider and try next healthy one
                        for alt_provider in all_providers:
                            alt_provider_name = alt_provider.get("plugin") or "unknown"
                            if (
                                alt_provider_name != provider_name
                                and alt_provider.get("type") == "remote"
                            ):
                                if not self._health_monitor.should_skip_provider(
                                    alt_provider_name
                                ):
                                    # Reset operation status and retry with alternative
                                    operation.status = OperationStatus.CREATED
                                    operation.error = None
                                    return await self._execute_remote_operation(
                                        operation, alt_provider, retry_count + 1
                                    )

            operation.finished_at = time.time()

        except capability_protocol.ProtocolCompatibilityError as e:
            # Protocol mismatch - this is a permanent failure
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="protocol_incompatible",
                message=f"Protocol mismatch with remote provider: {str(e)}",
            )
            operation.finished_at = time.time()
            self._health_monitor.mark_unhealthy(provider_name, "protocol_incompatible")
            provider_info["healthy"] = False

        except Exception as e:
            # Network or execution error
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="remote_execution_failed",
                message=f"Remote operation failed: {str(e)}",
            )
            operation.finished_at = time.time()

            # Record failure for health monitoring
            self._health_monitor.record_failure(provider_name, str(e))
            provider_info["healthy"] = not self._health_monitor.should_skip_provider(
                provider_name
            )

        await self.storage.persist(operation)
        return operation

    async def execute(self, operation: Operation) -> Operation:
        """
        Execute operation following pipeline:
        validate → authorize → run → persist.

        Operation status is updated in-place, result persisted.

        Supports execution modes:
        1. in_process: direct handler call
        2. process: subprocess execution
        3. container: docker/podman execution
        4. remote: HTTP execution

        Args:
            operation: Operation to execute

        Returns:
            Operation with updated status and result
        """
        try:
            declared_handler = get_operation_handler(operation.type)
            if declared_handler is not None:
                operation.status = OperationStatus.RUNNING
                operation.started_at = time.time()
                # Clear stale retry metadata/result to avoid leaking previous attempt state.
                operation.error = None
                operation.result = None
                await self.storage.persist(operation)

                try:
                    result = await declared_handler(operation.params)
                    if not isinstance(result, Dict):
                        result = {"value": result}
                    operation.status = OperationStatus.COMPLETED
                    operation.result = result
                    operation.error = None
                except Exception as e:
                    operation.status = OperationStatus.FAILED
                    operation.error = OperationError(
                        code="execution_error",
                        message=str(e),
                    )

                operation.finished_at = time.time()
                await self.storage.persist(operation)
                return operation

            # 1. Validate - try to find handler (direct or capability-based)
            handler = self.registry.find_handler(operation.type, self.runtime)
            provider_metadata = None  # Get metadata for execution mode decision

            # Метод select_provider_for() атомарно выбирает провайдера и возвращает ProviderMetadata
            try:
                if (
                    hasattr(self.runtime, "capability_registry")
                    and self.runtime.capability_registry
                ):
                    cap_reg = self.runtime.capability_registry
                    provider_metadata = cap_reg.select_provider_for(operation.type)
            except Exception:
                pass  # Failed to get metadata, continue with defaults

            # 2. Извлекаем execution_mode и provider_type из metadata
            execution_mode = "in_process"  # default
            provider_type = "local"  # default
            if provider_metadata:
                execution_mode = provider_metadata.execution_mode
                provider_type = provider_metadata.provider_type

            # If no local handler, try remote provider (backward compatible)
            if handler is None:
                # Check for remote provider (either type="remote" or execution_mode="remote")
                if provider_type == "remote" or execution_mode == "remote":
                    remote_provider_info = self._find_remote_provider(operation.type)
                    if remote_provider_info:
                        return await self._execute_remote_operation(
                            operation, remote_provider_info
                        )

                # Neither local nor remote found
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(
                    code="unknown_operation_type",
                    message=f"No handler or remote provider for operation type: {operation.type}",
                )
                await self.storage.persist(operation)
                return operation

            # Mark as running
            operation.status = OperationStatus.RUNNING
            operation.started_at = time.time()
            operation.error = None
            operation.result = None
            await self.storage.persist(operation)

            # Используем ExecutionController (из модуля execution или lazy fallback)
            controller = self.runtime.execution_controller

            if controller is None:
                # Lazy fallback: создаём in-process controller без персистентного policy
                # Используется в тестах и в окружениях без registered execution-модуля
                try:
                    from core.execution.controller import ExecutionControllerImpl

                    controller = ExecutionControllerImpl(self.runtime)
                    # Кэшируем для следующих вызовов
                    self.runtime.execution_controller = controller
                except Exception as _ctrl_err:
                    operation.status = OperationStatus.FAILED
                    operation.error = OperationError(
                        code="execution_controller_unavailable",
                        message=f"Execution controller is not available: {_ctrl_err}",
                    )
                    await self.storage.persist(operation)
                    return operation

            # Используем ExecutionController
            context = {
                "runtime": self.runtime,
                "operation_id": operation.operation_id,
            }

            # Добавляем provider metadata в context если есть
            if provider_metadata:
                context["_execution_policy"] = {
                    "execution_mode": getattr(
                        provider_metadata, "execution_mode", "in_process"
                    ),
                    "process_config": getattr(
                        provider_metadata, "process_config", None
                    ),
                    "container_config": getattr(
                        provider_metadata, "container_config", None
                    ),
                }

            op_res = await controller.execute_operation(
                operation_id=operation.operation_id,
                operation_type=operation.type,
                params=operation.params,
                context=context,
            )

            # Конвертируем OperationResult → Operation status
            if op_res.ok:
                operation.status = OperationStatus.COMPLETED
                operation.result = op_res.result or {}
                operation.error = None
            else:
                operation.status = OperationStatus.FAILED
                error_info = op_res.error or {}
                operation.error = OperationError(
                    code=str(error_info.get("code", "execution_error")),
                    message=str(error_info.get("message", "Execution failed")),
                    details=error_info,
                )

            operation.finished_at = time.time()

        except Exception as e:
            # Any exception → failed operation
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(code="execution_error", message=str(e))
            operation.finished_at = time.time()

        # Persist final state
        await self.storage.persist(operation)
        return operation

    async def execute_attempt(
        self,
        attempt_id: str,
        claim_token: str,
        *,
        lease_guard_epsilon_s: float = 0.0,
    ) -> Operation:
        """
        Attempt-only execution.

        Executor loads Operation from storage using attempt metadata and executes handler
        only if the attempt is currently claimed and the lease is not expired.
        """

        now = time.time()

        attempt = await self.storage.get_attempt(attempt_id)
        if attempt is None:
            raise ValueError(f"Attempt not found: {attempt_id}")

        if attempt.status != AttemptStatus.CLAIMED:
            operation = await self.storage.get(attempt.operation_id)
            if operation is None:
                raise ValueError(
                    f"Operation not found for attempt: {attempt.operation_id}"
                )
            return operation

        if attempt.claim_token != claim_token:
            attempt.status = AttemptStatus.FAILED
            attempt.finished_at = now
            attempt.error = {
                "code": "invalid_claim",
                "message": "claim_token mismatch for attempt execution",
            }
            await self.storage.persist_attempt(attempt)

            operation = await self.storage.get(attempt.operation_id)
            if operation is None:
                raise ValueError(
                    f"Operation not found for attempt: {attempt.operation_id}"
                )
            return operation

        lease_expires_at = attempt.lease_expires_at or 0.0
        if now + float(lease_guard_epsilon_s) >= lease_expires_at:
            # Lease expired: release attempt for re-claim instead of executing.
            attempt.status = AttemptStatus.CREATED
            attempt.claim_token = None
            attempt.claimed_at = None
            attempt.lease_expires_at = None
            attempt.claimed_by = None
            attempt.started_at = None
            attempt.finished_at = None
            attempt.error = None
            await self.storage.persist_attempt(attempt)

            operation = await self.storage.get(attempt.operation_id)
            if operation is None:
                raise ValueError(
                    f"Operation not found for attempt: {attempt.operation_id}"
                )
            return operation

        # Guard passed: transition attempt to RUNNING.
        execution_token = attempt.execution_token or claim_token

        attempt.status = AttemptStatus.RUNNING
        attempt.started_at = now
        attempt.error = None
        await self.storage.persist_attempt(attempt)

        operation = await self.storage.get(attempt.operation_id)
        if operation is None:
            raise ValueError(f"Operation not found for attempt: {attempt.operation_id}")

        # Pre-start cancellation / timeout checks.
        started_at_ts = attempt.started_at or now
        if operation.cancel_requested:
            latest_attempt = await self.storage.get_attempt(attempt_id) or attempt
            latest_attempt.status = AttemptStatus.CANCELLED
            latest_attempt.error = {"code": "cancelled", "message": "operation cancelled"}
            latest_attempt.finished_at = time.time()
            await self.storage.persist_attempt(latest_attempt)

            operation.status = OperationStatus.CANCELLED
            operation.error = None
            operation.result = None
            operation.finished_at = latest_attempt.finished_at
            operation.cancel_requested = True
            await self.storage.persist(operation)
            return operation

        if operation.timeout_seconds is not None:
            try:
                timeout_seconds_i = int(operation.timeout_seconds)
            except Exception:
                timeout_seconds_i = None
            if timeout_seconds_i is not None and time.time() - float(started_at_ts) > float(
                timeout_seconds_i
            ):
                latest_attempt = await self.storage.get_attempt(attempt_id) or attempt
                latest_attempt.status = AttemptStatus.TIMEOUT
                latest_attempt.error = {"code": "timeout", "message": "execution timeout"}
                latest_attempt.finished_at = time.time()
                await self.storage.persist_attempt(latest_attempt)

                operation.status = OperationStatus.FAILED
                operation.error = OperationError(
                    code="timeout", message="execution timeout"
                )
                operation.result = None
                operation.finished_at = latest_attempt.finished_at
                await self.storage.persist(operation)
                return operation

        # Execute handler (single attempt execution, no retry decisions here).
        # Heartbeat extends claim lease during long-running execution.
        lease_ttl_raw = getattr(self.runtime, "operation_attempt_lease_ttl", 30)
        try:
            lease_ttl_s = int(lease_ttl_raw)
        except Exception:
            lease_ttl_s = 30
        heartbeat_interval_s = max(0.1, float(lease_ttl_s) / 2.0)

        handler_task = asyncio.create_task(self.execute(operation))
        abort_reason: Optional[str] = None
        operation_id = operation.operation_id
        started_at_ts = attempt.started_at or now

        async def _heartbeat() -> None:
            nonlocal abort_reason
            while True:
                if handler_task.done():
                    return
                await asyncio.sleep(heartbeat_interval_s)
                if handler_task.done():
                    return

                # Cancellation / timeout checks live inside the heartbeat loop
                # so we can stop long-running handlers without changing handler API.
                try:
                    op_current = await self.runtime.storage.get(
                        "operations", operation_id
                    )
                except Exception:
                    op_current = None

                if isinstance(op_current, dict) and op_current.get(
                    "cancel_requested", False
                ):
                    abort_reason = "cancelled"
                    handler_task.cancel()
                    return

                timeout_seconds = None
                if isinstance(op_current, dict):
                    timeout_seconds = op_current.get("timeout_seconds")

                if timeout_seconds is not None:
                    try:
                        timeout_seconds_i = int(timeout_seconds)
                    except Exception:
                        timeout_seconds_i = None
                    if timeout_seconds_i is not None:
                        if time.time() - float(started_at_ts) > float(
                            timeout_seconds_i
                        ):
                            abort_reason = "timeout"
                            handler_task.cancel()
                            return

                ok = await self.storage.extend_claim(
                    attempt_id=attempt_id,
                    claim_token=claim_token,
                    lease_ttl=lease_ttl_s,
                )
                if not ok:
                    abort_reason = "lost_claim"
                    handler_task.cancel()
                    return

        heartbeat_task = asyncio.create_task(_heartbeat())

        try:
            res: Operation = await handler_task
        except asyncio.CancelledError:
            if abort_reason in ("lost_claim", "cancelled", "timeout"):
                res = None  # type: ignore[assignment]
            else:
                raise
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        final_now = time.time()
        latest_attempt = await self.storage.get_attempt(attempt_id) or attempt

        if abort_reason == "lost_claim":
            # Lost claim => stop execution, mark attempt as LOST_CLAIM (non-terminal),
            # and revert operation to CREATED to make worker pick it up again.
            latest_attempt.status = AttemptStatus.LOST_CLAIM
            latest_attempt.error = {
                "code": "lost_claim",
                "message": "claim lease couldn't be extended",
            }
            latest_attempt.finished_at = final_now
            # Force immediate expiration so another worker can re-claim soon.
            latest_attempt.lease_expires_at = final_now - 0.001
            await self.storage.persist_attempt(latest_attempt)

            op = await self.storage.get(latest_attempt.operation_id)
            if op is not None:
                op.status = OperationStatus.CREATED
                op.started_at = None
                op.finished_at = None
                op.error = None
                op.result = None
                await self.storage.persist(op)

            return op if op is not None else operation

        if abort_reason == "cancelled":
            latest_attempt.status = AttemptStatus.CANCELLED
            latest_attempt.error = {
                "code": "cancelled",
                "message": "operation cancelled",
            }
            latest_attempt.finished_at = final_now
            await self.storage.persist_attempt(latest_attempt)

            op = await self.storage.get(latest_attempt.operation_id)
            if op is not None:
                op.status = OperationStatus.CANCELLED
                op.error = None
                op.result = None
                op.finished_at = final_now
                op.cancel_requested = True
                await self.storage.persist(op)

            return op if op is not None else operation

        if abort_reason == "timeout":
            latest_attempt.status = AttemptStatus.TIMEOUT
            latest_attempt.error = {
                "code": "timeout",
                "message": "execution timeout",
            }
            latest_attempt.finished_at = final_now
            await self.storage.persist_attempt(latest_attempt)

            op = await self.storage.get(latest_attempt.operation_id)
            if op is not None:
                op.status = OperationStatus.FAILED
                op.error = OperationError(
                    code="timeout", message="execution timeout"
                )
                op.result = None
                op.finished_at = final_now
                await self.storage.persist(op)

            return op if op is not None else operation

        if res.status == OperationStatus.COMPLETED:
            latest_attempt.status = AttemptStatus.COMPLETED
            latest_attempt.error = None
        elif res.status == OperationStatus.FAILED:
            latest_attempt.status = AttemptStatus.FAILED
            latest_attempt.error = res.error.to_dict() if res.error else None
        else:
            latest_attempt.status = AttemptStatus.FAILED
            latest_attempt.error = {
                "code": "not_executed_or_cancelled",
                "message": f"attempt execution ended with operation.status={res.status.value}",
            }

        latest_attempt.finished_at = final_now
        await self.storage.persist_attempt(latest_attempt)

        # Persist side-effect outcome for idempotent replays.
        outcome = {
            "status": res.status.value,
            "result": res.result,
            "error": res.error.to_dict() if res.error else None,
            "finished_at": res.finished_at,
        }
        await self.runtime.storage.set(
            "operation_results", execution_token, outcome
        )

        return res
