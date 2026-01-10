"""
LoggerModule — встроенный модуль логирования.

Обязательный инфраструктурный модуль, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.

Предоставляет сервис `logger.log` для централизованного логирования.
Использует стандартный модуль `logging`, выводит в stdout.
Формат логов — простая JSON-подобная строка (через `json.dumps`).
"""

import sys
import json
import logging
from typing import Any

from core.runtime_module import RuntimeModule


class LoggerModule(RuntimeModule):
    """
    Модуль логирования.
    
    Предоставляет сервис logger.log для централизованного логирования.
    Не меняет глобальное состояние logging (не трогает root logger).
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "logger"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Создаёт logger и регистрирует сервис logger.log.
        """
        # Создаём выделенный логгер, выводящий JSON в stdout
        self._logger = logging.getLogger("home_console")
        # Устанавливаем уровень DEBUG, чтобы видеть все сообщения
        self._logger.setLevel(logging.DEBUG)
        # Добавляем собственный StreamHandler на stdout
        self._handler = logging.StreamHandler(stream=sys.stdout)
        fmt = "%(message)s"
        self._handler.setFormatter(logging.Formatter(fmt))
        # Регистрируем только наш handler у логгера home_console
        self._logger.addHandler(self._handler)

        # Регистрируем сервис logger.log
        await self.runtime.service_registry.register("logger.log", self._log_service)

    async def start(self) -> None:
        """
        Запуск модуля.
        
        Логирует сообщение о запуске.
        """
        try:
            await self._log_service(
                level="info",
                message="Logger module started",
                module="logger"
            )
        except Exception:
            # Не мешаем запуску системы при ошибках логирования
            pass

    async def stop(self) -> None:
        """
        Остановка модуля.
        
        Логирует сообщение об остановке и очищает ресурсы.
        """
        try:
            await self._log_service(
                level="info",
                message="Logger module stopped",
                module="logger"
            )
        except Exception:
            pass

        # Удаляем handler из логгера, чтобы не менять глобальное состояние
        try:
            if hasattr(self, "_logger") and hasattr(self, "_handler"):
                self._logger.removeHandler(self._handler)
        except Exception:
            pass

        # Очищаем ссылки
        try:
            self._handler = None
            self._logger = None
        except Exception:
            pass

        # Отменяем регистрацию сервиса
        try:
            await self.runtime.service_registry.unregister("logger.log")
        except Exception:
            pass

    async def _log_service(self, level: str, message: str, **context: Any) -> None:
        """
        Сервис логирования.
        
        Args:
            level: уровень логирования (debug, info, warning, error)
            message: сообщение для логирования
            **context: дополнительный контекст
        """
        # Простая валидация уровня
        lvl = (level or "").lower()
        if lvl not in ("debug", "info", "warning", "error"):
            lvl = "info"

        record = {
            "level": lvl,
            "message": message,
            # Если модуль/плагин передаёт имя — оно попадёт в context
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
