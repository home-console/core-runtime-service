"""
OperationExecutor - выполнение операций.

Отвечает за выполнение операций через различные backends (in_process, process, container, remote).
"""

import time
from typing import Any, Dict, Optional, Callable, Awaitable

from core.operations.models import Operation, OperationStatus, OperationError
from core.operations.registry import OperationHandlerRegistry
from core.health_monitor import ProviderHealthMonitor
from core.observability.metrics import get_metrics_registry
from core import capability_protocol


class OperationExecutor:
    """
    Исполнитель операций.
    
    Отвечает за выполнение операций через различные execution backends.
    """
    
    def __init__(
        self,
        registry: OperationHandlerRegistry,
        runtime: Any,
        storage: Any
    ):
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
        # Error codes that allow retry
        self._retryable_errors = {
            "timeout", "transient", "network", "device_offline", "integration_unavailable"
        }
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
            if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                cap_reg = self.runtime.capability_registry
                
                # REFACTORING: Используем высокоуровневый API для поиска провайдеров
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
        self,
        operation: Operation,
        provider_info: Dict[str, Any],
        retry_count: int = 0
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
            timeout = timeouts.get(operation.type, capability_protocol.DEFAULT_CAPABILITY_TIMEOUT)
            
            if not base_url:
                raise ValueError(f"Remote provider missing base_url in config")
            
            # Prepare execution context
            context = {
                "operation_id": operation.operation_id,
                "initiator": operation.initiator.to_dict() if operation.initiator else None,
            }
            
            # Execute with Protocol v1
            response = await RemoteOperationExecutor.execute_remote(
                base_url=base_url,
                capability=operation.type,
                operation_id=operation.operation_id,
                params=operation.params,
                context=context,
                timeout=timeout
            )
            
            # Record success in health monitor
            self._health_monitor.record_success(provider_name)
            provider_info["healthy"] = True
            
            # Handle response
            if response.get("status") == "success":
                # Success
                operation.status = OperationStatus.SUCCESS
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
                    f"{error_info.get('code')}: {error_info.get('message')}"
                )
                
                # If retryable and we haven't exceeded retry limit → try alternative provider
                if is_retryable and retry_count < capability_protocol.MAX_RETRIES_PER_OPERATION:
                    # Try next provider from registry
                    if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
                        cap_reg = self.runtime.capability_registry
                        all_providers = cap_reg.get_all_providers_for_capability(operation.type)
                        
                        # Skip current provider and try next healthy one
                        for alt_provider in all_providers:
                            alt_provider_name = alt_provider.get("plugin") or "unknown"
                            if alt_provider_name != provider_name and alt_provider.get("type") == "remote":
                                if not self._health_monitor.should_skip_provider(alt_provider_name):
                                    # Reset operation status and retry with alternative
                                    operation.status = OperationStatus.PENDING
                                    operation.error = None
                                    return await self._execute_remote_operation(
                                        operation,
                                        alt_provider,
                                        retry_count + 1
                                    )
            
            operation.finished_at = time.time()
        
        except capability_protocol.ProtocolCompatibilityError as e:
            # Protocol mismatch - this is a permanent failure
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="protocol_incompatible",
                message=f"Protocol mismatch with remote provider: {str(e)}"
            )
            operation.finished_at = time.time()
            self._health_monitor.mark_unhealthy(provider_name, "protocol_incompatible")
            provider_info["healthy"] = False
        
        except Exception as e:
            # Network or execution error
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="remote_execution_failed",
                message=f"Remote operation failed: {str(e)}"
            )
            operation.finished_at = time.time()
            
            # Record failure for health monitoring
            self._health_monitor.record_failure(provider_name, str(e))
            provider_info["healthy"] = not self._health_monitor.should_skip_provider(provider_name)
        
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
        start_time = time.time()
        metrics = get_metrics_registry()
        
        try:
            # 1. Validate - try to find handler (direct or capability-based)
            handler = self.registry.find_handler(operation.type, self.runtime)
            provider_metadata = None  # Get metadata for execution mode decision
            
            # REFACTORING: Используем инкапсулированный метод вместо прямого доступа к _lock
            # Метод select_provider_for() атомарно выбирает провайдера и возвращает ProviderMetadata
            try:
                if hasattr(self.runtime, 'capability_registry') and self.runtime.capability_registry:
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
                        return await self._execute_remote_operation(operation, remote_provider_info)
                
                # Neither local nor remote found
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(
                    code="unknown_operation_type",
                    message=f"No handler or remote provider for operation type: {operation.type}"
                )
                await self.storage.persist(operation)
                
                # Step 13: Record metrics
                metrics.increment_counter("operations_total", label_value=operation.type)
                metrics.increment_counter("operations_failed_total", label_value=operation.type)
                latency = (time.time() - start_time) * 1000  # ms
                metrics.observe_histogram("operation_latency_seconds", latency / 1000.0)
                
                return operation
            
            # Mark as running
            operation.status = OperationStatus.RUNNING
            operation.started_at = time.time()
            await self.storage.persist(operation)
            
            # REFACTORING: ExecutionRouter удалён, execution_controller теперь обязателен
            # Если execution_controller отсутствует, это ошибка конфигурации
            controller = self.runtime.execution_controller
            
            if controller is None:
                # Execution controller должен быть доступен (устанавливается модулем execution)
                operation.status = OperationStatus.FAILED
                operation.error = OperationError(
                    code="execution_controller_unavailable",
                    message="Execution controller is not available. Ensure 'execution' module is registered."
                )
                await self.storage.persist(operation)
                
                # Record metrics
                metrics.increment_counter("operations_total", label_value=operation.type)
                metrics.increment_counter("operations_failed_total", label_value=operation.type)
                latency = (time.time() - start_time) * 1000  # ms
                metrics.observe_histogram("operation_latency_seconds", latency / 1000.0)
                
                return operation
            
            # Используем ExecutionController
            context = {
                "runtime": self.runtime,
                "operation_id": operation.operation_id,
            }
            
            # Добавляем provider metadata в context если есть
            if provider_metadata:
                context["_execution_policy"] = {
                    "execution_mode": getattr(provider_metadata, "execution_mode", "in_process"),
                    "process_config": getattr(provider_metadata, "process_config", None),
                    "container_config": getattr(provider_metadata, "container_config", None),
                }
            
            op_res = await controller.execute_operation(
                operation_id=operation.operation_id,
                operation_type=operation.type,
                params=operation.params,
                context=context,
            )
            
            # Конвертируем OperationResult → Operation status
            if op_res.ok:
                operation.status = OperationStatus.SUCCESS
                operation.result = op_res.result or {}
            else:
                operation.status = OperationStatus.FAILED
                error_info = op_res.error or {}
                operation.error = OperationError(
                    code=str(error_info.get("code", "execution_error")),
                    message=str(error_info.get("message", "Execution failed")),
                    details=error_info
                )
            
            operation.finished_at = time.time()
            
            # Step 13: Record metrics
            metrics.increment_counter("operations_total", label_value=operation.type)
            latency = (time.time() - start_time) * 1000  # ms
            metrics.observe_histogram("operation_latency_seconds", latency / 1000.0)
        
        except Exception as e:
            # Any exception → failed operation
            operation.status = OperationStatus.FAILED
            operation.error = OperationError(
                code="execution_error",
                message=str(e)
            )
            operation.finished_at = time.time()
            
            # Step 13: Record failure metrics
            metrics.increment_counter("operations_total", label_value=operation.type)
            metrics.increment_counter("operations_failed_total", label_value=operation.type)
            latency = (time.time() - start_time) * 1000  # ms
            metrics.observe_histogram("operation_latency_seconds", latency / 1000.0)
        
        # Persist final state
        await self.storage.persist(operation)
        return operation
