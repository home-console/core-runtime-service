"""
RemoteOperationExecutor - выполняет операции через HTTP к remote capability providers.

Используется OperationManager когда handler находится у remote provider.
Обрабатывает HTTP коммуникацию, таймауты, ошибки и retry логику.
"""

from typing import Any, Dict, Optional
import asyncio


class RemoteOperationExecutor:
    """
    Executor для remote capability operations.
    
    API:
    - execute_remote(base_url, operation, timeout) -> Dict[str, Any]
    """

    @staticmethod
    async def execute_remote(
        base_url: str,
        operation_type: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Выполнить операцию на remote capability provider через HTTP.
        
        Args:
            base_url: базовый URL remote provider (e.g., "http://localhost:9000")
            operation_type: тип операции (e.g., "client.command.execute")
            params: параметры операции
            context: контекст выполнения (runtime info, operation_id и др.)
            timeout: timeout для HTTP запроса (default: 10 сек)
            
        Returns:
            Результат выполнения: { "status": "success", "result": ... }
                                или { "status": "error", "error": {...} }
            
        Raises:
            RuntimeError: если HTTP запрос не удался (timeout, connection refused и т.д.)
            ValueError: если response невалидный
        """
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx is required for remote capability execution. Install: pip install httpx")
        
        if timeout is None:
            timeout = 10.0
        
        # Строим endpoint URL
        endpoint_url = f"{base_url.rstrip('/')}/capability/execute"
        
        # Подготавливаем payload
        payload = {
            "type": operation_type,
            "params": params,
            "context": {
                "operation_id": context.get("operation_id"),
                "initiator": context.get("initiator"),
            }
        }
        
        try:
            # Делаем HTTP запрос к remote provider
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                # Проверяем HTTP status
                if response.status_code >= 400:
                    error_text = response.text[:500]  # Ограничиваем размер для логирования
                    raise RuntimeError(
                        f"Remote provider returned {response.status_code}: {error_text}"
                    )
                
                # Парсим response
                response_data = response.json()
                
                # Проверяем структуру response
                if not isinstance(response_data, dict):
                    raise ValueError(f"Remote provider returned invalid response: not a dict")
                
                status = response_data.get("status")
                if status not in ("success", "error"):
                    raise ValueError(f"Remote provider returned invalid status: {status}")
                
                # Возвращаем результат как-есть (успех или ошибка)
                return response_data
        
        except httpx.TimeoutException as e:
            raise RuntimeError(f"Remote provider request timeout ({timeout}s): {endpoint_url}") from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise RuntimeError(f"Cannot connect to remote provider: {endpoint_url}") from e
        except Exception as e:
            raise RuntimeError(f"Remote operation execution failed: {e}") from e

    @staticmethod
    def is_remote_response_success(response: Dict[str, Any]) -> bool:
        """Проверить успешность ответа от remote provider."""
        return response.get("status") == "success"

    @staticmethod
    def extract_result(response: Dict[str, Any]) -> Any:
        """Извлечь результат из ответа remote provider."""
        if response.get("status") == "success":
            return response.get("result")
        else:
            # Ошибка - вернуть что-то для логирования
            error = response.get("error", {})
            raise RuntimeError(f"Remote error: {error.get('message', 'Unknown error')}")
