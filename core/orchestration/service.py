"""
Orchestration Service — интерфейс для управления инфраструктурой плагинов.

Абстракция над Docker/k8s backend'ами.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class OrchestrationBackend(ABC):
    """
    Базовый класс для backend'ов orchestration.
    
    Реализации могут использовать Docker, Kubernetes, или другие системы оркестрации.
    """
    
    @abstractmethod
    async def container_exists(self, container_name: str) -> bool:
        """Проверить существование контейнера."""
        pass
    
    @abstractmethod
    async def stop_container(self, container_name: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Остановить контейнер."""
        pass
    
    @abstractmethod
    async def remove_container(self, container_name: str, force: bool = False) -> Dict[str, Any]:
        """Удалить контейнер."""
        pass
    
    @abstractmethod
    async def ensure_container(
        self,
        container_name: str,
        container_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Убедиться, что контейнер существует и запущен."""
        pass

    @abstractmethod
    async def start_container(self, container_name: str) -> Dict[str, Any]:
        """Запустить существующий контейнер."""
        pass

    @abstractmethod
    async def restart_container(
        self, container_name: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Перезапустить контейнер."""
        pass


class OrchestrationService:
    """
    Сервис оркестрации плагинов.
    
    Централизованный интерфейс для управления инфраструктурой плагинов.
    Абстрагирует детали реализации (Docker/k8s) от модулей.
    
    Использование:
        service = OrchestrationService(backend=DockerOrchestrationBackend())
        result = await service.ensure_plugin_container("plugin_name", container_config)
    """
    
    def __init__(self, backend: OrchestrationBackend):
        """
        Инициализация OrchestrationService.
        
        Args:
            backend: backend для оркестрации (Docker, k8s и т.д.)
        """
        self._backend = backend
    
    async def container_exists(self, container_name: str) -> bool:
        """
        Проверить существование контейнера.
        
        Args:
            container_name: имя контейнера
            
        Returns:
            True если контейнер существует
        """
        return await self._backend.container_exists(container_name)
    
    async def stop_container(self, container_name: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Остановить контейнер.
        
        Args:
            container_name: имя контейнера
            timeout: таймаут остановки (секунды)
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        return await self._backend.stop_container(container_name, timeout)
    
    async def remove_container(self, container_name: str, force: bool = False) -> Dict[str, Any]:
        """
        Удалить контейнер.
        
        Args:
            container_name: имя контейнера
            force: если True, принудительно останавливает перед удалением
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        return await self._backend.remove_container(container_name, force)
    
    async def ensure_container(
        self,
        container_name: str,
        container_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Убедиться, что контейнер существует и запущен.
        
        Если контейнер не существует:
        1. Проверяет наличие образа
        2. Если образа нет и указан build в container_config — собирает образ
        3. Создаёт и запускает контейнер
        
        Args:
            container_name: имя контейнера
            container_config: конфигурация контейнера из plugin.metadata.container_config
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        return await self._backend.ensure_container(container_name, container_config)
    
    async def ensure_plugin_container(
        self,
        plugin_name: str,
        container_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Убедиться, что контейнер плагина существует и запущен.
        
        Удобный метод, который определяет имя контейнера из plugin_name и container_config.
        
        Args:
            plugin_name: имя плагина
            container_config: конфигурация контейнера из plugin.metadata.container_config
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        container_name = container_config.get("name")
        if not container_name:
            container_name = f"plugin-{plugin_name}"
        
        return await self.ensure_container(container_name, container_config)
    
    async def stop_plugin_container(
        self,
        plugin_name: str,
        container_config: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Остановить контейнер плагина.
        
        Args:
            plugin_name: имя плагина
            container_config: конфигурация контейнера
            timeout: таймаут остановки (секунды)
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        container_name = container_config.get("name")
        if not container_name:
            container_name = f"plugin-{plugin_name}"
        
        return await self.stop_container(container_name, timeout)
    
    async def remove_plugin_container(
        self,
        plugin_name: str,
        container_config: Dict[str, Any],
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Удалить контейнер плагина.
        
        Args:
            plugin_name: имя плагина
            container_config: конфигурация контейнера
            force: если True, принудительно останавливает перед удалением
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        container_name = container_config.get("name")
        if not container_name:
            container_name = f"plugin-{plugin_name}"
        
        return await self.remove_container(container_name, force)
    
    async def restart_container(self, container_name: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Перезапустить контейнер.
        
        Args:
            container_name: имя контейнера
            timeout: таймаут остановки перед перезапуском (секунды)
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        return await self._backend.restart_container(container_name, timeout)
    
    async def _start_container(self, container_name: str) -> Dict[str, Any]:
        """
        Запустить существующий контейнер.
        
        Args:
            container_name: имя контейнера
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        # Backward-compat shim: delegate to backend.
        return await self._backend.start_container(container_name)


class NullOrchestrationBackend(OrchestrationBackend):
    """
    No-op backend для headless/dev сценариев.

    Позволяет отключить orchestration на уровне конфигурации, не раздувая условную
    логику по всему runtime. Все операции возвращают контролируемый отказ.
    """

    async def container_exists(self, container_name: str) -> bool:
        return False

    async def stop_container(
        self, container_name: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        return {"ok": False, "error": "Orchestration backend is disabled"}

    async def remove_container(
        self, container_name: str, force: bool = False
    ) -> Dict[str, Any]:
        return {"ok": False, "error": "Orchestration backend is disabled"}

    async def ensure_container(
        self,
        container_name: str,
        container_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {"ok": False, "error": "Orchestration backend is disabled"}

    async def start_container(self, container_name: str) -> Dict[str, Any]:
        return {"ok": False, "error": "Orchestration backend is disabled"}

    async def restart_container(
        self, container_name: str, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        return {"ok": False, "error": "Orchestration backend is disabled"}


# Глобальный экземпляр OrchestrationService (singleton)
_global_orchestration_service: Optional[OrchestrationService] = None


def get_orchestration_service() -> Optional[OrchestrationService]:
    """
    Получить глобальный экземпляр OrchestrationService.
    
    Returns:
        OrchestrationService или None если не инициализирован
    """
    return _global_orchestration_service


def set_orchestration_service(service: OrchestrationService) -> None:
    """
    Установить глобальный экземпляр OrchestrationService.
    
    Args:
        service: экземпляр OrchestrationService
    """
    global _global_orchestration_service
    _global_orchestration_service = service
