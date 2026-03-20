"""
Runtime API - интерфейс для главного runtime контейнера.

Позволяет модулям и плагинам работать через минимальный API
вместо прямого импорта core.runtime.
"""

from typing import Protocol, runtime_checkable, Any, Optional, List, Dict


@runtime_checkable
class IRuntimeModule(Protocol):
    """
    Lightweight interface for runtime module access.
    
    Modules should depend on this instead of direct core.runtime import.
    """
    
    def get_service(self, name: str) -> Optional[Any]:
        """Get registered service by name."""
        ...

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        ...

    async def execute_operation(
        self,
        operation_type: str,
        params: Dict[str, Any],
        initiator: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute an operation through operations manager."""
        ...


@runtime_checkable
class IPluginRegistry(Protocol):
    """
    Interface for plugin registration and discovery.
    
    Decouples plugin lifecycle from runtime core.
    """
    
    def register_plugin(
        self,
        name: str,
        plugin: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Register a plugin."""
        ...

    def get_plugin(self, name: str) -> Optional[Any]:
        """Get registered plugin by name."""
        ...

    def list_plugins(self) -> List[str]:
        """List all registered plugin names."""
        ...


@runtime_checkable
class IPluginLifecycle(Protocol):
    """
    Interface for plugin lifecycle management (init, start, stop).
    
    Separates what plugins need to do from how runtime manages them.
    """
    
    async def initialize_plugin(
        self,
        plugin_name: str,
        config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Initialize plugin with optional config."""
        ...

    async def start_plugin(self, plugin_name: str) -> None:
        """Start/activate plugin."""
        ...

    async def stop_plugin(self, plugin_name: str) -> None:
        """Stop/deactivate plugin."""
        ...
