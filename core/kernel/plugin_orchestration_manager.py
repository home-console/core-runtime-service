"""
Plugin Orchestration Manager — управление контейнерами плагинов.

Отвечает за:
- Остановку контейнеров плагинов
- Удаление контейнеров плагинов
- Запуск контейнеров плагинов

Выделено из PluginLifecycleManager для соблюдения SRP.
"""

from typing import Any, Dict, Optional
import logging

from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS

logger = logging.getLogger(__name__)

_ORCH_BOUNDARY_ERRORS = (
    OSError,
    TimeoutError,
    ConnectionError,
    RuntimeError,
    TypeError,
    AttributeError,
    KeyError,
    ValueError,
)


class PluginOrchestrationManager:
    """
    Менеджер оркестрации плагинов.

    Управляет контейнерами плагинов через OrchestrationService.
    """

    def __init__(
        self,
        runtime: Optional[Any] = None,
        *,
        orchestration_service: Optional[Any] = None,
    ):
        """
        Инициализация менеджера.

        Args:
            runtime: экземпляр CoreRuntime (для доступа к orchestration_service)
            orchestration_service: явный OrchestrationService (предпочтительно)
        """
        self._runtime = runtime
        self._orchestration_service = orchestration_service

    def _get_orchestration_service(self) -> Optional[Any]:
        """Получить OrchestrationService из runtime."""
        if self._orchestration_service is not None:
            return self._orchestration_service
        if not self._runtime:
            return None
        return getattr(self._runtime, "orchestration_service", None)

    async def stop_plugin_runtime(self, plugin_name: str, metadata: Any) -> bool:
        """
        Остановить runtime-окружение плагина (например контейнер) если требуется.
        """
        try:
            mode = getattr(metadata, "execution_mode", None)
            container_config = getattr(metadata, "container_config", None)
        except (AttributeError, TypeError, ValueError):
            return False
        if mode != "container" or not container_config:
            return False
        return await self.stop_plugin_container(plugin_name, container_config)

    async def remove_plugin_runtime(self, plugin_name: str, metadata: Any) -> bool:
        """
        Удалить runtime-окружение плагина (например контейнер) если требуется.
        """
        try:
            mode = getattr(metadata, "execution_mode", None)
            container_config = getattr(metadata, "container_config", None)
        except (AttributeError, TypeError, ValueError):
            return False
        if mode != "container" or not container_config:
            return False
        return await self.remove_plugin_container(plugin_name, container_config)

    async def stop_plugin_container(
        self, plugin_name: str, container_config: Dict[str, Any], timeout: float = 30.0
    ) -> bool:
        """
        Остановить контейнер плагина.

        Args:
            plugin_name: имя плагина
            container_config: конфигурация контейнера
            timeout: таймаут остановки

        Returns:
            True если успешно
        """
        orchestration_service = self._get_orchestration_service()
        if not orchestration_service:
            return False

        try:
            result = await orchestration_service.stop_plugin_container(
                plugin_name, container_config, timeout=timeout
            )
            return bool(result.get("ok", False))
        except _ORCH_BOUNDARY_ERRORS as e:
            logger.warning(
                "plugin_orchestration_manager.stop_plugin_container: failed, returning False: %s",
                e,
                exc_info=True,
            )
            return False
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning(
                "plugin_orchestration_manager.stop_plugin_container: unexpected, returning False: %s",
                e,
                exc_info=True,
            )
            return False

    async def remove_plugin_container(
        self, plugin_name: str, container_config: Dict[str, Any], force: bool = True
    ) -> bool:
        """
        Удалить контейнер плагина.

        Args:
            plugin_name: имя плагина
            container_config: конфигурация контейнера
            force: принудительно остановить перед удалением

        Returns:
            True если успешно
        """
        orchestration_service = self._get_orchestration_service()
        if not orchestration_service:
            return False

        try:
            result = await orchestration_service.remove_plugin_container(
                plugin_name, container_config, force=force
            )
            return bool(result.get("ok", False))
        except _ORCH_BOUNDARY_ERRORS as e:
            logger.warning(
                "plugin_orchestration_manager.remove_plugin_container: failed, returning False: %s",
                e,
                exc_info=True,
            )
            return False
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning(
                "plugin_orchestration_manager.remove_plugin_container: unexpected, returning False: %s",
                e,
                exc_info=True,
            )
            return False

    async def ensure_plugin_container(
        self, plugin_name: str, container_config: Dict[str, Any]
    ) -> bool:
        """
        Убедиться что контейнер плагина существует и запущен.

        Args:
            plugin_name: имя плагина
            container_config: конфигурация контейнера

        Returns:
            True если успешно
        """
        orchestration_service = self._get_orchestration_service()
        if not orchestration_service:
            return False

        try:
            result = await orchestration_service.ensure_plugin_container(
                plugin_name, container_config
            )
            return bool(result.get("ok", False))
        except _ORCH_BOUNDARY_ERRORS as e:
            logger.warning(
                "plugin_orchestration_manager.ensure_plugin_container: failed, returning False: %s",
                e,
                exc_info=True,
            )
            return False
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning(
                "plugin_orchestration_manager.ensure_plugin_container: unexpected, returning False: %s",
                e,
                exc_info=True,
            )
            return False
