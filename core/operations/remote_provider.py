"""
RemoteCapabilityProvider - базовый класс для плагинов, которые предоставляют capabilities через HTTP.

Отличие от обычного плагина:
- Не регистрирует handler напрямую в OperationManager
- Вместо этого объявляет remote_config в metadata
- OperationManager маршрутизирует операции через HTTP к remote endpoint

Пример использования:

```python
class RemoteClientManager(RemoteCapabilityProvider):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="remote_client_manager",
            version="1.0.0",
            description="Remote client manager service",
            capabilities_provided=["client.command.execute"],
            remote_config={
                "base_url": "http://localhost:9000",
                "timeout": 10,
            }
        )
```

Remote Service должен реализовать API:
- POST /capability/execute
  Request: { type, params, context }
  Response: { status, result } или { status, error }
"""

from typing import TYPE_CHECKING, Optional

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.exception_groups import LOGGING_HELPER_ERRORS

if TYPE_CHECKING:
    from core.runtime.runtime import CoreRuntime
import logging

logger = logging.getLogger(__name__)

_REMOTE_LOG_ERRORS = (RuntimeError, AttributeError, KeyError, TypeError, ValueError)


class RemoteCapabilityProvider(BasePlugin):
    """
    Базовый класс для remote capability providers.
    
    Remote provider не регистрирует handlers - вместо этого объявляет capabilities
    и remote_config в metadata. OperationManager автоматически маршрутизирует
    операции через HTTP.
    
    Гарантирует:
    - Плагин не сломается если HTTP недоступен (graceful degradation)
    - Повторные попытки при сетевых ошибках (опционально в executor)
    - Правильный error handling
    """

    def __init__(self, runtime: Optional["CoreRuntime"] = None):
        super().__init__(runtime)

    @property
    def metadata(self) -> PluginMetadata:
        """
        Метаданные remote provider.
        
        ДОЛЖНЫ содержать:
        - capabilities_provided: список capabilities
        - remote_config: конфигурация подключения { "base_url": "...", "timeout": N }
        """
        raise NotImplementedError("Subclass must implement metadata property")

    async def on_load(self) -> None:
        """Загрузка: verify remote config."""
        await super().on_load()
        
        # Проверяем что remote_config задан
        if not self.metadata.remote_config:
            raise ValueError(f"Plugin {self.metadata.name} must have remote_config in metadata")
        
        if "base_url" not in self.metadata.remote_config:
            raise ValueError(f"Plugin {self.metadata.name} must have 'base_url' in remote_config")
        
        # Логируем registrацию remote provider
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"Remote capability provider loaded: {self.metadata.name} at {self.metadata.remote_config['base_url']}",
                plugin=self.metadata.name
            )
        except LOGGING_HELPER_ERRORS as e:
            if isinstance(e, _REMOTE_LOG_ERRORS):
                logger.debug(
                    "remote_provider.on_load: logger.log failed (boundary)",
                    exc_info=True,
                )
            else:
                logger.debug("remote_provider.on_load: unexpected", exc_info=True)

    async def on_start(self) -> None:
        """Запуск: регистрируем capabilities в registry как remote."""
        await super().on_start()
        
        # CapabilityRegistry автоматически регистрирует remote capabilities
        # на основе metadata и remote_config в PluginManager.load_plugin()
        # Здесь просто логируем
        try:
            caps = ", ".join(self.metadata.capabilities_provided or [])
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"Remote provider capabilities started: {caps}",
                plugin=self.metadata.name
            )
        except LOGGING_HELPER_ERRORS as e:
            if isinstance(e, _REMOTE_LOG_ERRORS):
                logger.debug(
                    "remote_provider.on_start: logger.log failed (boundary)",
                    exc_info=True,
                )
            else:
                logger.debug("remote_provider.on_start: unexpected", exc_info=True)

    async def on_stop(self) -> None:
        """Остановка: cleanup graceful."""
        await super().on_stop()
        
        try:
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"Remote capability provider stopped",
                plugin=self.metadata.name
            )
        except LOGGING_HELPER_ERRORS as e:
            if isinstance(e, _REMOTE_LOG_ERRORS):
                logger.debug(
                    "remote_provider.on_stop: logger.log failed (boundary)",
                    exc_info=True,
                )
            else:
                logger.debug("remote_provider.on_stop: unexpected", exc_info=True)

    async def on_unload(self) -> None:
        """Выгрузка: cleanup."""
        await super().on_unload()
