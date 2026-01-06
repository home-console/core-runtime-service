"""
Системный плагин `system_logger` — инфраструктурный in-process плагин.

Назначение:
- предоставляет сервис `logger.log` для централизованного логирования
- использует стандартный модуль `logging`, выводит в stdout
- формат логов — простая JSON-подобная строка (через `json.dumps`)

Контракт с Core: работает только через `runtime.service_registry` и опционально
может слушать/публиковать события через `runtime.event_bus` (необязательно).

Ограничения:
- не меняет глобальное состояние logging (не трогает root logger)
- не хранит состояние, не знает доменов и не зависит от адаптеров
"""

from __future__ import annotations

import sys
import json
import logging
from typing import Any

from plugins.base_plugin import BasePlugin, PluginMetadata


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
        await super().on_load()
        # Сохраняем runtime для доступа к service_registry и event_bus
        # Не импортируем или используем другие плагины
        # Создаём выделенный логгер, выводящий JSON в stdout
        self._runtime = self.runtime

        self._logger = logging.getLogger("home_console")
        # Устанавливаем уровень DEBUG, чтобы видеть все сообщения
        self._logger.setLevel(logging.DEBUG)
        # Добавляем собственный StreamHandler на stdout
        self._handler = logging.StreamHandler(stream=sys.stdout)
        fmt = "%(message)s"
        self._handler.setFormatter(logging.Formatter(fmt))
        # Регистрируем только наш handler у логгера home_console
        self._logger.addHandler(self._handler)

        # Зарегистрируем сервис logger.log
        async def _log_service(level: str, message: str, **context: Any) -> None:
            # Простая валидация уровня
            lvl = (level or "").lower()
            if lvl not in ("debug", "info", "warning", "error"):
                lvl = "info"

            record = {
                "level": lvl,
                "message": message,
                # Если плагин передаёт имя плагина — оно попадёт в context
                "context": context or {},
            }

            try:
                # Сериализуем и отправляем как единую строку — формат JSON-подобный
                line = json.dumps(record, ensure_ascii=False)
            except Exception:
                # В крайне редком случае — fallback на простую строку
                line = json.dumps({"level": lvl, "message": str(message)}, ensure_ascii=False)

            if lvl == "debug":
                self._logger.debug(line)
            elif lvl == "warning":
                self._logger.warning(line)
            elif lvl == "error":
                self._logger.error(line)
            else:
                # default: info
                self._logger.info(line)

        # Регистрируем сервис в runtime
        self.runtime.service_registry.register("logger.log", _log_service)

    async def on_start(self) -> None:
        await super().on_start()
        # Сообщаем, что логгер активирован
        try:
            await self.runtime.service_registry.call(
                "logger.log", level="info", message="system_logger запущен", plugin=self.metadata.name
            )
        except Exception:
            # Не мешаем запуску системы при ошибках логирования
            pass

    async def on_stop(self) -> None:
        await super().on_stop()
        try:
            await self.runtime.service_registry.call(
                "logger.log", level="info", message="system_logger остановлен", plugin=self.metadata.name
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        await super().on_unload()
        # Удаляем сервис и обнуляем ссылки. Не трогаем глобальный root logger.
        try:
            self.runtime.service_registry.unregister("logger.log")
        except Exception:
            pass

        # Удаляем наш handler из логгера, чтобы не менять глобальное состояние
        try:
            if hasattr(self, "_logger") and hasattr(self, "_handler"):
                self._logger.removeHandler(self._handler)
        except Exception:
            pass

        # Очистить ссылки
        try:
            self._handler = None
            self._logger = None
            self._runtime = None
            self.runtime = None
        except Exception:
            pass
