"""
Remote Executor Interface - контракт для удалённого исполнителя операций.

Позволяет разорвать зависимости от конкретной реализации HTTP-клиента
и сделать mock для тестов.
"""

from typing import Protocol, runtime_checkable, Dict, Any, Optional


@runtime_checkable
class IRemoteExecutor(Protocol):
    """
    Interface for remote operation execution via HTTP.
    
    Enables dependency inversion for remote capability protocol operations.
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
        Execute operation on remote capability provider.
        
        Args:
            base_url: Remote provider base URL
            capability: Capability ID (e.g., "client.command.execute")
            operation_id: Operation ID for tracing
            params: Operation parameters
            context: Execution context (initiator, etc.)
            timeout: HTTP timeout in seconds
            
        Returns:
            Response dict with status and result
        """
        ...

    @staticmethod
    async def get_manifest(
        base_url: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Get manifest from remote provider.
        
        Args:
            base_url: Remote provider base URL
            timeout: HTTP timeout in seconds
            
        Returns:
            Manifest dict with supported capabilities
        """
        ...

    @staticmethod
    async def check_health(
        base_url: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Check health of remote provider.
        
        Args:
            base_url: Remote provider base URL
            timeout: HTTP timeout in seconds
            
        Returns:
            Health status dict
        """
        ...
