"""
RuntimeContext - ограниченный контекст для модулей и плагинов.

Предоставляет только необходимые компоненты ядра без прямого доступа
к внутренним деталям (plugin_manager, module_manager, event_bus напрямую).
"""

from typing import Optional, Any
from dataclasses import dataclass

from core.storage import Storage
from core.service_registry import ServiceRegistry
from core.http_registry import HttpRegistry
from core.capability_registry import CapabilityRegistry
from core.operations.manager import OperationManager


@dataclass
class RuntimeContext:
    """
    Ограниченный контекст для модулей и плагинов.
    
    Предоставляет только публичный API ядра:
    - storage: доступ к storage (через StoragePort)
    - vault: доступ к vault storage (если dual-mode)
    - services: ServiceRegistry для регистрации/вызова сервисов
    - http: HttpRegistry для регистрации HTTP endpoints
    - capabilities: CapabilityRegistry для регистрации capabilities
    - operations: OperationManager для выполнения операций
    
    НЕ предоставляет:
    - plugin_manager, module_manager (внутренние детали)
    - event_bus (используется через operations/events)
    - Прямой доступ к runtime (только через контекст)
    """
    
    # Storage
    storage: Storage  # Core storage (через StoragePort)
    vault: Optional[Any] = None  # Vault storage port (если dual-mode)
    
    # Registries
    services: ServiceRegistry  # Service registry
    http: HttpRegistry  # HTTP registry
    capabilities: CapabilityRegistry  # Capability registry
    
    # Operations
    operations: OperationManager  # Operations manager
    
    # Опциональные компоненты (могут быть None в некоторых контекстах)
    state: Optional[Any] = None  # StateEngine (для быстрого доступа к state)
    
    def __post_init__(self):
        """Валидация обязательных полей."""
        if self.storage is None:
            raise ValueError("storage is required")
        if self.services is None:
            raise ValueError("services is required")
        if self.http is None:
            raise ValueError("http is required")
        if self.capabilities is None:
            raise ValueError("capabilities is required")
        if self.operations is None:
            raise ValueError("operations is required")
