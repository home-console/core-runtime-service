"""
Client Manager Plugin - управление удаленными клиентами.

Интеграция как in-process плагина Core Runtime с использованием:
- HttpRegistry для регистрации HTTP и WebSocket endpoints
- service_registry для бизнес-логики
- Без собственного uvicorn сервера
"""

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.http.models import HttpEndpoint

if TYPE_CHECKING:
    from core.runtime.runtime import CoreRuntime

logger = logging.getLogger(__name__)


def _ensure_client_manager_plugin_on_path() -> None:
    """Добавляет каталог client-manager-plugin в sys.path и app.__path__."""
    plugin_dir = Path(__file__).resolve().parent
    plugins_root = plugin_dir.parent
    cm_plugin_dir = plugins_root / "client-manager-service"
    cm_app_dir = cm_plugin_dir / "app"
    if cm_plugin_dir.is_dir() and str(cm_plugin_dir) not in sys.path:
        sys.path.insert(0, str(cm_plugin_dir))
    try:
        app_pkg = importlib.import_module("app")
        app_path = getattr(app_pkg, "__path__", None)
        if app_path is not None and cm_app_dir.is_dir() and str(cm_app_dir) not in app_path:
            app_path.append(str(cm_app_dir))
    except Exception:
        pass


class ClientManagerPlugin(BasePlugin):
    """
    Плагин для управления удаленными клиентами.
    
    Возможности:
    - WebSocket соединения с агентами
    - REST API для управления клиентами
    - Отправка команд на агенты
    - Файловые трансферы
    - Terminal sessions
    - JWT аутентификация
    
    Архитектура:
    - Использует HttpRegistry для регистрации HTTP/WebSocket endpoints
    - Реализует обработчики как сервисы через service_registry
    - Не запускает собственный сервер (интегрируется с ApiModule)
    """

    def __init__(self, runtime: Optional["CoreRuntime"] = None):
        super().__init__(runtime)
        self.handler: Optional[object] = None  # WebSocketHandler instance
        self._handler_ready = asyncio.Event()  # Флаг готовности handler'а

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="client_manager",
            version="1.0.0",
            description="Управление удаленными клиентами через WebSocket и REST API",
            author="Home Console",
            dependencies=[],
            capabilities_provided=[
                "client.command.execute",
                "client.list",
                "client.delete"
            ]
        )

    async def on_load(self) -> None:
        """Загрузка плагина - регистрация сервисов и endpoints."""
        await super().on_load()

        try:
            from . import plugin_services

            # Регистрируем сервисы в service_registry
            await plugin_services.register_services(self)

            # Регистрируем endpoints в HttpRegistry
            self._register_http_endpoints()

            # Register operation handlers (capability-first model)
            try:
                self.register_operation_handler(
                    "client.command.execute",
                    self._op_execute_command,
                )
                self.register_operation_handler(
                    "client.list",
                    self._op_list_clients,
                )
                self.register_operation_handler(
                    "client.delete",
                    self._op_delete_client,
                )

                self.register_operation_handler(
                    "client_manager.execute_command",
                    self._op_execute_command,
                )
                self.register_operation_handler(
                    "client_manager.delete_client",
                    self._op_delete_client,
                )
                self.register_operation_handler(
                    "client_manager.execute_universal_command",
                    self._op_execute_universal_command,
                )
            except Exception:
                pass

            try:
                await self.call_service(
                    "logger.log",
                    level="info",
                    message="Client Manager endpoints и сервисы зарегистрированы через HttpRegistry",
                    plugin="client_manager"
                )
            except Exception:
                logger.info("Client Manager endpoints и сервисы зарегистрированы")

        except Exception as e:
            logger.error(f"Ошибка регистрации Client Manager: {e}")
            try:
                await self.call_service(
                    "logger.log",
                    level="error",
                    message=f"Ошибка регистрации Client Manager: {e}",
                    plugin="client_manager"
                )
            except Exception:
                pass
            raise

    def _register_http_endpoints(self) -> None:
        """Регистрирует HTTP и WebSocket endpoints в HttpRegistry."""

        ws_endpoints = [
            HttpEndpoint(
                path="/ws",
                service="client_manager.websocket",
                websocket=True,
                description="WebSocket для агентских соединений",
                tags=["client_manager", "websocket"]
            ),
            HttpEndpoint(
                path="/admin/ws",
                service="client_manager.admin_websocket",
                websocket=True,
                description="Админский WebSocket (JWT защита)",
                tags=["client_manager", "websocket", "admin"]
            ),
        ]

        rest_endpoints = [
            HttpEndpoint(
                path="/client-manager/clients",
                method="GET",
                service="client_manager.list_clients",
                description="Получить список клиентов",
                tags=["client_manager", "clients"]
            ),
            HttpEndpoint(
                path="/client-manager/clients/{client_id}",
                method="GET",
                service="client_manager.get_client",
                description="Получить информацию о клиенте",
                tags=["client_manager", "clients"]
            ),
            HttpEndpoint(
                path="/client-manager/clients/{client_id}",
                method="DELETE",
                service="client_manager.delete_client",
                description="Удалить клиента",
                tags=["client_manager", "clients"]
            ),
            HttpEndpoint(
                path="/client-manager/commands/{client_id}",
                method="POST",
                service="client_manager.execute_command",
                description="Выполнить команду на клиенте",
                tags=["client_manager", "commands"]
            ),
            HttpEndpoint(
                path="/client-manager/commands/{client_id}/status",
                method="GET",
                service="client_manager.get_command_status",
                description="Получить статус команды",
                tags=["client_manager", "commands"]
            ),
            HttpEndpoint(
                path="/client-manager/health",
                method="GET",
                service="client_manager.health_check",
                description="Health check",
                tags=["client_manager", "health"]
            ),
            HttpEndpoint(
                path="/client-manager/files/transfers",
                method="GET",
                service="client_manager.list_transfers",
                description="Список передач файлов",
                tags=["client_manager", "files"]
            ),
            HttpEndpoint(
                path="/admin/v1/agents/{agent_id}/terminal/start",
                method="POST",
                service="admin.v1.agents.terminal.start",
                description="Запустить терминальную сессию на агенте",
                tags=["client_manager", "terminal", "admin", "agents"]
            ),
            HttpEndpoint(
                path="/admin/v1/agents/terminal/ws/{session_id}",
                service="admin.v1.agents.terminal.ws",
                websocket=True,
                description="WebSocket attach к терминальной сессии агента",
                tags=["client_manager", "terminal", "admin", "agents", "websocket"]
            ),
            HttpEndpoint(
                path="/client-manager/universal/{client_id}/execute",
                method="POST",
                service="client_manager.execute_universal_command",
                description="Выполнить универсальную команду",
                tags=["client_manager", "commands"]
            ),
        ]

        for ep in ws_endpoints + rest_endpoints:
            self.register_http_endpoint(ep)

    async def on_start(self) -> None:
        """Запуск плагина - инициализация WebSocketHandler."""
        await super().on_start()

        _ensure_client_manager_plugin_on_path()

        try:
            from app.core.websocket_handler import WebSocketHandler
            from app.core.security.auth_service import AuthService

            self.handler = WebSocketHandler()
            
            # НОВОЕ (TASK 1.3): Передаем runtime для интеграции с DeploymentTracker
            if self.runtime:
                self.handler.set_runtime(self.runtime)
                logger.info("Runtime передан WebSocketHandler для интеграции с DeploymentTracker")

            try:
                auth_service = AuthService()
                self.handler.auth_service = auth_service
                logger.info("AuthService инициализирован для админских WS")
            except Exception as e:
                logger.warning(f"AuthService не инициализирован: {e}")

            try:
                await self.handler.start_background_tasks()
                logger.info("Background tasks started: core monitor and audit flusher")
            except Exception as e:
                logger.warning(f"Не удалось запустить фоновые задачи обработчика: {e}")

            self._handler_ready.set()

            # Интеграция с event_bus (client.connected, command.completed и т.д.)
            try:
                from . import plugin_events
                await plugin_events.setup_event_integration(self, self.handler)
            except Exception as e:
                logger.warning(f"Event integration не подключена: {e}")

            logger.info("Client Manager WebSocket handler инициализирован")

            try:
                await self.call_service(
                    "logger.log",
                    level="info",
                    message="Client Manager WebSocket handler инициализирован",
                    plugin="client_manager"
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Ошибка запуска Client Manager: {e}")
            try:
                await self.call_service(
                    "logger.log",
                    level="error",
                    message=f"Ошибка запуска Client Manager: {e}",
                    plugin="client_manager"
                )
            except Exception:
                pass
            raise

    async def on_stop(self) -> None:
        """Остановка плагина - graceful shutdown handler'а."""
        await super().on_stop()

        try:
            logger.info("Остановка Client Manager...")

            if self.handler:
                try:
                    await self.handler.cleanup()
                except Exception as e:
                    logger.warning(f"Ошибка при очистке handler'а: {e}")

            logger.info("Client Manager остановлен")

            try:
                await self.call_service(
                    "logger.log",
                    level="info",
                    message="Client Manager остановлен",
                    plugin="client_manager"
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Ошибка при остановке Client Manager: {e}")
            try:
                await self.call_service(
                    "logger.log",
                    level="error",
                    message=f"Ошибка при остановке Client Manager: {e}",
                    plugin="client_manager"
                )
            except Exception:
                pass

    async def on_unload(self) -> None:
        """Выгрузка плагина - очистка ресурсов."""
        await super().on_unload()

        self.handler = None
        self._handler_ready.clear()

        logger.info("Client Manager выгружен")

        try:
            await self.call_service(
                "logger.log",
                level="info",
                message="Client Manager выгружен",
                plugin="client_manager"
            )
        except Exception:
            pass

    # -----------------
    # Operation handlers
    # -----------------
    async def _op_execute_command(self, params: dict, context: dict) -> dict:
        client_id = params.get("client_id")
        body = params.get("body", {})
        if not client_id:
            raise ValueError("client_id is required")
        return await self.call_service("client_manager._impl.execute_command", client_id, body)

    async def _op_list_clients(self, params: dict, context: dict) -> dict:
        return await self.call_service("client_manager._impl.list_clients")

    async def _op_delete_client(self, params: dict, context: dict) -> dict:
        client_id = params.get("client_id")
        if not client_id:
            raise ValueError("client_id is required")
        return await self.call_service("client_manager._impl.delete_client", client_id)

    async def _op_execute_universal_command(self, params: dict, context: dict) -> dict:
        client_id = params.get("client_id")
        body = params.get("body", {})
        if not client_id:
            raise ValueError("client_id is required")
        return await self.call_service("client_manager._impl.execute_universal_command", client_id, body)
