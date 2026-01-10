"""
DEPRECATED: Этот плагин заменён модулем modules.logger.LoggerModule.

Оставлен для обратной совместимости.
Будет удалён в версии 1.0.0.

Вся логика логирования теперь в modules/logger/module.py.
LoggerModule регистрируется автоматически при создании CoreRuntime
через ModuleManager (первым в списке BUILTIN_MODULES).

Этот плагин больше не нужен и может быть удалён.
"""

from __future__ import annotations

import sys
import json
import logging
from typing import Any

from core.base_plugin import BasePlugin, PluginMetadata


class SystemLoggerPlugin(BasePlugin):
    """Системный плагин логирования.

    Lifecycle:
    - on_load: сохраняет runtime, создаёт logger и регистрирует сервис
    - on_start/on_stop: пишет информационные сообщения
    - on_unload: удаляет добавленные обработчики и очищает ссылки
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="system_logger",
            version="0.1.0",
            description="Системный логгер для централизованного логирования",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """
        DEPRECATED: LoggerModule теперь регистрируется автоматически через ModuleManager.
        
        Этот метод больше не выполняет никаких действий.
        Модуль logger регистрируется при создании CoreRuntime.
        """
        await super().on_load()
        # LoggerModule уже зарегистрирован через ModuleManager
        # Ничего делать не нужно

    async def on_start(self) -> None:
        """Запуск плагина - модуль уже зарегистрирован в on_load."""
        await super().on_start()
        # LoggerModule уже запущен через ModuleManager

    async def on_stop(self) -> None:
        """Остановка плагина - модуль управляет своей остановкой самостоятельно."""
        await super().on_stop()
        # LoggerModule управляет своей остановкой через ModuleManager

    async def on_unload(self) -> None:
        """Выгрузка плагина - очистка ссылок."""
        await super().on_unload()
        # LoggerModule управляет своей выгрузкой через ModuleManager
        self.runtime = None
