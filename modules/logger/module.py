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
from modules.hooks.system import register_system_hook, unregister_system_hook
from modules.hooks.runtime_contract import ensure_runtime_execution_contract


class LoggerModule(RuntimeModule):
    """
    Модуль логирования.
    
    Предоставляет сервис logger.log для централизованного логирования.
    Не меняет глобальное состояние logging (не трогает root logger).
    """

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._hook_bindings: list[tuple[str, Any]] = []

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "logger"

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Создаёт logger и регистрирует сервис logger.log.
        """
        ensure_runtime_execution_contract(self.runtime)

        # Сохраняем уровень логирования для фильтрации
        # Можно установить LOG_LEVEL=DEBUG для отладки, или LOG_LEVEL=WARNING для тихих логов
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        self._log_level = getattr(logging, log_level_str, logging.INFO)

        # Формат логов:
        # - text (по умолчанию) — человекочитаемый
        # - json — структурированный (для production / ELK / Loki)
        cfg = getattr(self.runtime, "_config", None)
        cfg_fmt = getattr(cfg, "log_format", None) if cfg is not None else None
        env_fmt = os.getenv("RUNTIME_LOG_FORMAT") or os.getenv("LOG_FORMAT")
        self._log_format = (cfg_fmt or env_fmt or "text").lower()
        if self._log_format not in ("text", "json"):
            self._log_format = "text"

        # Регистрируем сервис logger.log (ACL обвязка в ядре — без ограничений)
        # Поддерживаем старые FakeRegistry объекты в тестах, поэтому используем
        # register_with_acl если доступен, иначе падаем back на register().
        services = self._get_service_registry()
        if hasattr(services, "register_with_acl"):
            await services.register_with_acl("logger.log", self._log_service)
        else:
            await services.register("logger.log", self._log_service)

        register_system_hook("after_execute", self._after_execute)
        register_system_hook("on_failure", self._on_failure)
        self._hook_bindings.extend(
            [
                ("after_execute", self._after_execute),
                ("on_failure", self._on_failure),
            ]
        )

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

        for hook_name, handler in self._hook_bindings:
            unregister_system_hook(hook_name, handler)
        self._hook_bindings.clear()

        # Очищаем ссылки (больше не используем logger)
        try:
            self._log_level = logging.INFO
        except Exception:
            pass

        # Отменяем регистрацию сервиса
        try:
            services = self._get_service_registry()
            await services.unregister("logger.log")
        except Exception:
            pass

    def _get_service_registry(self):
        kernel_context = getattr(self.runtime, "kernel_context", None)
        if kernel_context is not None:
            services = kernel_context.get_service("service_registry")
            if services is not None:
                return services
        return getattr(self.runtime, "service_registry", None)

    async def _log_service(self, level: str, message: str, **context: Any) -> None:
        """
        Сервис логирования.
        
        SECURITY: All logs are sanitized before output to prevent secret leakage.
        
        Args:
            level: уровень логирования (debug, info, warning, error)
            message: сообщение для логирования
            **context: дополнительный контекст (может включать operation_id, plugin, module и др.)
        """
        # SECURITY: Sanitize all data before logging
        from modules.security import sanitize_for_logging
        message = sanitize_for_logging(message)
        context = sanitize_for_logging(context)
        
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

        if getattr(self, "_log_format", "text") == "json":
            # Структурированный JSON лог (одна строка на событие)
            event: dict[str, Any] = {
                "level": lvl.upper(),
                "message": message,
            }
            plugin = context.get("plugin")
            module = context.get("module")
            if plugin:
                event["plugin"] = plugin
            if module:
                event["module"] = module
            if operation_id:
                event["operation_id"] = operation_id
            # Добавляем контекст как есть (только сериализуемые типы)
            safe_ctx: dict[str, Any] = {}
            for k, v in context.items():
                if k in ("plugin", "module"):
                    continue
                # базовые типы + dict/list (json сможет)
                if isinstance(v, (str, int, float, bool, type(None), dict, list)):
                    safe_ctx[k] = v
                else:
                    safe_ctx[k] = str(v)
            if safe_ctx:
                event["context"] = safe_ctx
            print(json.dumps(event, ensure_ascii=False), file=sys.stdout, flush=True)
        else:
            # Формируем простой читаемый формат лога
            # Формат: [LEVEL] [plugin/module] message (context если есть)
            parts = [f"[{lvl.upper()}]"]
            plugin = context.get("plugin")
            module = context.get("module")
            if plugin:
                parts.append(f"[{plugin}]")
            elif module:
                parts.append(f"[{module}]")
            parts.append(message)
            important_context = {}
            for key, value in context.items():
                if key not in ("plugin", "module", "request_id"):
                    if isinstance(value, (str, int, float, bool, type(None))):
                        important_context[key] = value
            if important_context:
                context_str = " ".join(f"{k}={v}" for k, v in important_context.items())
                parts.append(f"({context_str})")
            line = " ".join(parts)
            print(line, file=sys.stdout, flush=True)
        
        # Если доступен RequestLoggerModule, записываем лог туда тоже
        try:
            services = self.runtime.kernel_context.get_service("service_registry")
            if services:
                has_request_logger = await services.has_service("request_logger.log")
                if has_request_logger:
                    # Используем operation_id из параметров или из контекста выполнения
                    if not operation_id:
                        from core.operation_context import get_operation_id
                        operation_id = get_operation_id()
                    
                    if operation_id:
                        await services.call(
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

    async def _after_execute(self, ctx: dict[str, Any]):
        operation = ctx.get("operation")
        if operation is None:
            return None
        await self.runtime.service_registry.call(
            "logger.log",
            level="info",
            message="operation executed",
            component="execution",
            operation_id=getattr(operation, "operation_id", None),
            operation_type=getattr(operation, "type", None),
            status=getattr(getattr(operation, "status", None), "value", None),
            error_code=getattr(getattr(operation, "error", None), "code", None),
        )
        return None

    async def _on_failure(self, ctx: dict[str, Any]):
        operation = ctx.get("operation")
        if operation is None:
            return None
        await self.runtime.service_registry.call(
            "logger.log",
            level="warning",
            message="operation failed",
            component="execution",
            operation_id=getattr(operation, "operation_id", None),
            operation_type=getattr(operation, "type", None),
            status=getattr(getattr(operation, "status", None), "value", None),
            error_code=getattr(getattr(operation, "error", None), "code", None),
        )
        return None
