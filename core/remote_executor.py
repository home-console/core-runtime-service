"""
RemoteOperationExecutor - выполняет операции через HTTP к remote capability providers.

Поддерживает Capability Protocol v1:
- Protocol versioning и negotiation
- Manifest discovery
- Health monitoring
- Retryable error handling
- Per-capability timeouts

Используется OperationManager когда handler находится у remote provider.
Обрабатывает HTTP коммуникацию, таймауты, ошибки и retry логику.
"""

from typing import Any, Dict, Optional
import asyncio
from core import capability_protocol
from core.remote_executor_interface import IRemoteExecutor


class RemoteOperationExecutor(IRemoteExecutor):
    """
    Executor для remote capability operations.
    
    Поддерживает Capability Protocol v1:
    - request header: X-HomeConsole-Protocol: 1
    - request body: protocol_version, capability, operation_id, params, context
    - validates response protocol_version
    - handles retryable errors
    
    API:
    - execute_remote(base_url, capability, operation_id, params, context, timeout) -> Dict[str, Any]
    - get_manifest(base_url, timeout) -> Dict[str, Any]
    - check_health(base_url, timeout) -> Dict[str, Any]
    """

    @staticmethod
    async def execute_remote(
        base_url: str,
        capability: str,
        operation_id: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Выполнить операцию на remote capability provider через HTTP.
        
        Реализует Capability Protocol v1.
        
        Args:
            base_url: базовый URL remote provider (e.g., "http://localhost:9000")
            capability: ID capability (e.g., "client.command.execute")
            operation_id: уникальный ID операции для tracing
            params: параметры операции
            context: контекст выполнения (initiator, etc.)
            timeout: timeout для HTTP запроса (seconds), по умолчанию 10
            
        Returns:
            Response dict: { "status": "success|error", "protocol_version": 1, ... }
            
        Raises:
            RuntimeError: если HTTP запрос не удался
            ValueError: если response невалидный
            capability_protocol.ProtocolCompatibilityError: если protocol_version несовместима
        """
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx is required for remote capability execution. Install: pip install httpx")
        
        if timeout is None:
            timeout = capability_protocol.DEFAULT_CAPABILITY_TIMEOUT
        
        # Строим endpoint URL
        endpoint_url = f"{base_url.rstrip('/')}/capability/execute"
        
        # Подготавливаем payload согласно Protocol v1
        payload: capability_protocol.CapabilityExecuteRequest = {
            "protocol_version": capability_protocol.PROTOCOL_VERSION,
            "capability": capability,
            "operation_id": operation_id,
            "params": params,
            "context": context or {},
        }
        
        try:
            # Делаем HTTP запрос к remote provider с protocol header
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        capability_protocol.PROTOCOL_HEADER: str(capability_protocol.PROTOCOL_VERSION),
                    }
                )
                
                # Проверяем HTTP status
                if response.status_code >= 400:
                    error_text = response.text[:500]
                    raise RuntimeError(
                        f"Remote provider HTTP {response.status_code}: {error_text}"
                    )
                
                # Парсим response
                response_data = response.json()
                
                # Проверяем структуру response
                if not isinstance(response_data, dict):
                    raise ValueError(f"Remote provider returned invalid response: not a dict")
                
                # Проверяем status поле
                status = response_data.get("status")
                if status not in ("success", "error"):
                    raise ValueError(f"Remote provider returned invalid status: {status}")
                
                # Валидируем protocol version (может быть несовместима)
                capability_protocol.check_protocol_compatibility(response_data)
                
                # Возвращаем response (может содержать ошибку)
                return response_data
        
        except httpx.TimeoutException as e:
            raise RuntimeError(f"Remote provider request timeout ({timeout}s): {endpoint_url}") from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise RuntimeError(f"Cannot connect to remote provider: {endpoint_url}") from e
        except capability_protocol.ProtocolCompatibilityError:
            # Re-raise compatibility errors - они serious
            raise
        except Exception as e:
            raise RuntimeError(f"Remote operation execution failed: {e}") from e

    @staticmethod
    async def get_manifest(
        base_url: str,
        timeout: Optional[float] = None
    ) -> Optional[capability_protocol.CapabilityManifest]:
        """
        Получить manifest от remote provider.
        
        Manifest содержит:
        - protocol_version
        - provider_version
        - список capabilities
        - timeouts per capability
        
        Returns:
            Manifest dict или None если provider не поддерживает (legacy mode)
        """
        try:
            import httpx
        except ImportError:
            return None
        
        if timeout is None:
            timeout = capability_protocol.DEFAULT_MANIFEST_TIMEOUT
        
        endpoint_url = f"{base_url.rstrip('/')}/capability/manifest"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    endpoint_url,
                    headers={
                        capability_protocol.PROTOCOL_HEADER: str(capability_protocol.PROTOCOL_VERSION),
                    }
                )
                
                if response.status_code == 404:
                    # Manifest not implemented - legacy provider
                    return None
                
                if response.status_code >= 400:
                    # Error - skip manifest discovery
                    return None
                
                manifest = response.json()
                
                # Validate manifest structure
                if not isinstance(manifest, dict):
                    return None
                
                # Check required fields
                if "protocol_version" not in manifest or "provider_version" not in manifest:
                    return None
                
                # Validate protocol compatibility
                capability_protocol.check_protocol_compatibility(manifest)
                
                return manifest
        
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
            # Network error - return None, provider will work in legacy mode
            return None
        except Exception:
            # Any other error - proceed with legacy mode
            return None

    @staticmethod
    async def check_health(
        base_url: str,
        timeout: Optional[float] = None
    ) -> Optional[capability_protocol.CapabilityHealth]:
        """
        Проверить health remote provider.
        
        Returns:
            Health dict или None если provider не поддерживает (legacy mode)
        """
        try:
            import httpx
        except ImportError:
            return None
        
        if timeout is None:
            timeout = capability_protocol.DEFAULT_HEALTH_CHECK_TIMEOUT
        
        endpoint_url = f"{base_url.rstrip('/')}/capability/health"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    endpoint_url,
                    headers={
                        capability_protocol.PROTOCOL_HEADER: str(capability_protocol.PROTOCOL_VERSION),
                    }
                )
                
                if response.status_code == 404:
                    # Health endpoint not implemented - legacy provider
                    return None
                
                if response.status_code >= 400:
                    # Error - provider seems unhealthy
                    return None
                
                health = response.json()
                
                if not isinstance(health, dict):
                    return None
                
                return health
        
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
            # Network error - provider unhealthy
            return None
        except Exception:
            # Any other error - mark as unhealthy
            return None

    @staticmethod
    def is_remote_response_success(response: Dict[str, Any]) -> bool:
        """Проверить успешность ответа от remote provider."""
        return response.get("status") == "success"

    @staticmethod
    def is_error_retryable(response: Dict[str, Any]) -> bool:
        """
        Проверить, является ли ошибка retryable.
        
        Использует поле error.retryable из response.
        """
        if response.get("status") != "error":
            return False
        
        error = response.get("error", {})
        if isinstance(error, dict):
            # Явное указание retryable
            retryable = error.get("retryable")
            if retryable is not None:
                return retryable
            
            # Проверяем по стандартному коду ошибки
            code = error.get("code", "")
            return capability_protocol.is_retryable_error(code)
        
        return False

    @staticmethod
    def extract_result(response: Dict[str, Any]) -> Any:
        """Извлечь результат из ответа remote provider."""
        if response.get("status") == "success":
            return response.get("result")
        else:
            # Ошибка - вернуть что-то для логирования
            error = response.get("error", {})
            raise RuntimeError(f"Remote error: {error.get('message', 'Unknown error')}")

