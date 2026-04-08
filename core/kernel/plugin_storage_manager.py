"""
Plugin Storage Manager — управление метаданными плагинов в storage.

Отвечает за:
- Сохранение метаданных плагина
- Обновление статуса (loaded/unloaded)
- Чтение метаданных для восстановления

Выделено из PluginLifecycleManager для соблюдения SRP.
"""

import logging
import time
from typing import Any, Optional

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from core.exception_groups import BEST_EFFORT_BACKGROUND_ERRORS
from core.kernel.plugin_metadata_storage_contract import (
    PLUGIN_METADATA_NAMESPACE,
    PluginMetadataRecord,
)

logger = logging.getLogger(__name__)


class PluginStorageManager:
    """
    Менеджер хранения метаданных плагинов.

    Отвечает за персистентность информации о плагинах.
    """

    def __init__(self, runtime: Optional[Any] = None):
        """
        Инициализация менеджера.

        Args:
            runtime: экземпляр CoreRuntime (для доступа к storage)
        """
        self._runtime = runtime

    def _get_storage(self) -> Optional[Any]:
        """Получить storage из runtime."""
        if not self._runtime:
            return None
        return getattr(self._runtime, "storage", None)

    async def save_plugin_metadata(self, plugin_name: str, metadata: Any) -> None:
        """
        Сохранить метаданные плагина в persistent storage.

        Args:
            plugin_name: имя плагина
            metadata: метаданные плагина
        """
        storage = self._get_storage()
        if not storage:
            return

        try:
            record = PluginMetadataRecord.from_metadata(
                plugin_name, metadata, now=time.time()
            )
            await storage.set(PLUGIN_METADATA_NAMESPACE, plugin_name, record.to_storage_dict())
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "plugin_storage_manager.save_plugin_metadata: storage boundary (suppressed)",
                exc_info=True,
            )
        except BEST_EFFORT_BACKGROUND_ERRORS:
            logger.warning(
                "plugin_storage_manager.save_plugin_metadata: unexpected error (suppressed)",
                exc_info=True,
            )

    async def mark_plugin_unloaded(self, plugin_name: str) -> None:
        """
        Пометить плагин как выгруженный.

        Args:
            plugin_name: имя плагина
        """
        storage = self._get_storage()
        if not storage:
            return

        try:
            raw = await storage.get(PLUGIN_METADATA_NAMESPACE, plugin_name)
            if not isinstance(raw, dict):
                return
            record = PluginMetadataRecord.from_storage_dict(plugin_name, raw)
            updated = PluginMetadataRecord(
                schema_version=record.schema_version,
                name=record.name,
                version=record.version,
                class_path=record.class_path,
                execution_mode=record.execution_mode,
                container_config=record.container_config,
                capabilities_provided=list(record.capabilities_provided),
                capabilities_required=list(record.capabilities_required),
                dependencies=list(record.dependencies),
                loaded=False,
                loaded_at=record.loaded_at,
                unloaded_at=time.time(),
            )
            await storage.set(
                PLUGIN_METADATA_NAMESPACE, plugin_name, updated.to_storage_dict()
            )
        except STORAGE_BOUNDARY_ERRORS:
            logger.debug(
                "plugin_storage_manager.mark_plugin_unloaded: storage boundary (suppressed)",
                exc_info=True,
            )
        except BEST_EFFORT_BACKGROUND_ERRORS:
            logger.warning(
                "plugin_storage_manager.mark_plugin_unloaded: unexpected error (suppressed)",
                exc_info=True,
            )

    async def get_plugin_metadata(self, plugin_name: str) -> Optional[dict]:
        """
        Получить метаданные плагина из storage.

        Args:
            plugin_name: имя плагина

        Returns:
            Метаданные или None
        """
        storage = self._get_storage()
        if not storage:
            return None

        try:
            raw = await storage.get(PLUGIN_METADATA_NAMESPACE, plugin_name)
            if not isinstance(raw, dict):
                return None
            # Normalize legacy shapes to current schema on read.
            record = PluginMetadataRecord.from_storage_dict(plugin_name, raw)
            return record.to_storage_dict()
        except STORAGE_BOUNDARY_ERRORS as e:
            logger.warning(
                "plugin_storage_manager.get_plugin_metadata: storage boundary, returning None: %s",
                e,
                exc_info=True,
            )
            return None
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning(
                "plugin_storage_manager.get_plugin_metadata: unexpected, returning None: %s",
                e,
                exc_info=True,
            )
            return None

    async def list_installed_plugins(self) -> list[str]:
        """
        Получить список установленных плагинов.

        Returns:
            Список имён плагинов
        """
        storage = self._get_storage()
        if not storage:
            return []

        try:
            keys = await storage.list_keys(PLUGIN_METADATA_NAMESPACE)
            return list(keys)
        except STORAGE_BOUNDARY_ERRORS as e:
            logger.warning(
                "plugin_storage_manager.list_installed_plugins: storage boundary: %s",
                e,
                exc_info=True,
            )
            return []
        except BEST_EFFORT_BACKGROUND_ERRORS as e:
            logger.warning(
                "plugin_storage_manager.list_installed_plugins: unexpected: %s",
                e,
                exc_info=True,
            )
            return []
