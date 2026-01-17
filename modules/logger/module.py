"""
LoggerModule — встроенный модуль логирования.

Обязательный инфраструктурный модуль, который регистрируется автоматически
при создании CoreRuntime через ModuleManager.

Предоставляет сервис `logger.log` для централизованного логирования.
Использует стандартный модуль `logging`, выводит в stdout.
Формат логов — простой читаемый текст: [LEVEL] [plugin] message (context)
"""

import os
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
        # Сохраняем уровень логирования для фильтрации
        # Можно установить LOG_LEVEL=DEBUG для отладки, или LOG_LEVEL=WARNING для тихих логов
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        self._log_level = getattr(logging, log_level_str, logging.INFO)
        
        # НЕ используем logging для вывода - используем прямой print в stdout
        # Это гарантирует простой формат без JSON обёртки

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

        # Очищаем ссылки (больше не используем logger)
        try:
            self._log_level = logging.INFO
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
            **context: дополнительный контекст (может включать operation_id, plugin, module и др.)
        """
        # Извлекаем operation_id из context (может быть передан явно)
        operation_id = context.pop("operation_id", None)
        
        # Простая валидация уровня
        lvl = (level or "").lower()
        if lvl not in ("debug", "info", "warning", "error"):
            lvl = "info"
        
        # Фильтруем по уровню логирования
        level_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }
        message_level = level_map.get(lvl, logging.INFO)
        if message_level < self._log_level:
            # Лог ниже установленного уровня - пропускаем
            return

        # Формируем простой читаемый формат лога
        # Формат: [LEVEL] [plugin/module] message (context если есть)
        parts = [f"[{lvl.upper()}]"]
        
        # Добавляем источник (plugin или module)
        plugin = context.get("plugin")
        module = context.get("module")
        if plugin:
            parts.append(f"[{plugin}]")
        elif module:
            parts.append(f"[{module}]")
        
        # Добавляем сообщение
        parts.append(message)
        
        # Добавляем важный контекст (исключая plugin/module, так как уже добавили)
        important_context = {}
        for key, value in context.items():
            if key not in ("plugin", "module", "request_id"):
                # Добавляем только простые значения (не вложенные объекты)
                if isinstance(value, (str, int, float, bool, type(None))):
                    important_context[key] = value
        
        if important_context:
            # Форматируем контекст как key=value
            context_str = " ".join(f"{k}={v}" for k, v in important_context.items())
            parts.append(f"({context_str})")
        
        line = " ".join(parts)

        # ВАЖНО: Используем прямой вывод в stdout чтобы избежать JSON обёртки от других handlers
        # Это гарантирует что логи будут в простом формате без JSON
        print(line, file=sys.stdout, flush=True)
        
        # Если доступен RequestLoggerModule, записываем лог туда тоже
        try:
            if hasattr(self.runtime, 'service_registry'):
                has_request_logger = await self.runtime.service_registry.has_service("request_logger.log")
                if has_request_logger:
                    # Используем operation_id из параметров или из контекста выполнения
                    if not operation_id:
                        try:
                            from modules.request_logger.middleware import get_operation_id
                            operation_id = get_operation_id()
                        except ImportError:
                            pass
                    
                    if operation_id:
                        await self.runtime.service_registry.call(
                            "request_logger.log",
                            request_id=operation_id,  # Используем operation_id как request_id для обратной совместимости API
                            level=lvl,
                            message=message,
                            **{k: v for k, v in context.items() if k not in ("request_id", "operation_id")}
                        )
        except Exception:
            # Игнорируем ошибки при записи в RequestLoggerModule
            # Это не должно влиять на основное логирование
            pass