"""
Client Manager Plugin — интеграция client-manager-service как плагина.

Запускает FastAPI приложение client-manager-service в отдельном потоке через uvicorn.
"""
import sys
import threading
import asyncio
from pathlib import Path
from typing import Optional, Any

try:
    import uvicorn
except ImportError:
    uvicorn = None

from core.base_plugin import BasePlugin, PluginMetadata


class ClientManagerPlugin(BasePlugin):
    """
    Плагин для Client Manager Service.
    
    Запускает client-manager-service как отдельный FastAPI сервер в отдельном потоке.
    """
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="client_manager",
            version="1.0.0",
            description="Client Manager Service - управление удалёнными клиентами через WebSocket",
            author="Home Console",
            dependencies=[]
        )
    
    def __init__(self, runtime: Optional[Any] = None):
        super().__init__(runtime)
        self._server: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._app: Optional[Any] = None
        self._handler: Optional[Any] = None
    
    async def on_load(self) -> None:
        """Загрузка: импортируем и создаём FastAPI app."""
        await super().on_load()
        
        # Проверяем наличие uvicorn
        if uvicorn is None:
            await self.runtime.service_registry.call(
                "logger.log",
                level="error",
                message="uvicorn не установлен. Установите: pip install uvicorn",
                plugin="client_manager"
            )
            raise ImportError("uvicorn is required for client_manager plugin")
        
        # Добавляем путь к client-manager-service в sys.path для импортов
        client_manager_path = Path(__file__).parent.parent / "client-manager-service"
        if str(client_manager_path) not in sys.path:
            sys.path.insert(0, str(client_manager_path))
        
        # Импортируем app из client-manager-service
        try:
            # Импортируем create_app вместо готового app, чтобы контролировать lifespan
            # После добавления пути в sys.path импорты должны работать
            from app.main import create_app
            self._app = create_app()
            
            # Получаем handler для регистрации сервисов
            from app.dependencies import get_websocket_handler
            try:
                self._handler = get_websocket_handler()
            except Exception:
                # Handler может быть не инициализирован до старта
                self._handler = None
            
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Client Manager app создан",
                plugin="client_manager"
            )
        except ImportError as e:
            await self.runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Не удалось импортировать client-manager app: {e}",
                plugin="client_manager"
            )
            raise
        except Exception as e:
            await self.runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Ошибка при создании Client Manager app: {e}",
                plugin="client_manager"
            )
            raise
    
    async def on_start(self) -> None:
        """Запуск: запускаем uvicorn сервер в отдельном потоке."""
        await super().on_start()
        
        if self._app is None:
            return
        
        # Получаем конфигурацию из переменных окружения
        host = self.get_env_config("CLIENT_MANAGER_HOST", default="0.0.0.0")
        port = self.get_env_config_int("CLIENT_MANAGER_PORT", default=10000)
        
        # Создаём конфигурацию uvicorn
        config = uvicorn.Config(
            self._app,
            host=host,
            port=port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        self._server = server
        
        # Запускаем сервер в отдельном потоке
        def run_server():
            try:
                server.run()
            except SystemExit:
                # uvicorn вызывает SystemExit(1) при ошибке привязки порта
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        self.runtime.service_registry.call(
                            "logger.log",
                            level="warning",
                            message=f"Client Manager server exited (port {port} may be in use)",
                            plugin="client_manager"
                        )
                    )
                    loop.close()
                except Exception:
                    pass
                return
            except Exception as e:
                # Общий защитный fallback
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        self.runtime.service_registry.call(
                            "logger.log",
                            level="error",
                            message=f"Client Manager server error: {e}",
                            plugin="client_manager"
                        )
                    )
                    loop.close()
                except Exception:
                    pass
                return
        
        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
        
        # Логируем успешный запуск
        await self.runtime.service_registry.call(
            "logger.log",
            level="info",
            message=f"Client Manager запущен на {host}:{port}",
            plugin="client_manager"
        )
        
        # Регистрируем сервисы для доступа к ClientManager из других плагинов
        await self._register_services()
    
    async def _register_services(self) -> None:
        """Регистрирует сервисы Client Manager через ServiceRegistry."""
        try:
            from app.dependencies import get_websocket_handler
            
            async def get_clients() -> dict:
                """Получить список всех клиентов."""
                try:
                    handler = get_websocket_handler()
                    if handler and hasattr(handler, 'get_all_clients'):
                        return handler.get_all_clients()
                    return {}
                except Exception as e:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Ошибка получения списка клиентов: {e}",
                        plugin="client_manager"
                    )
                    return {}
            
            async def get_client_info(client_id: str) -> Optional[dict]:
                """Получить информацию о клиенте."""
                try:
                    handler = get_websocket_handler()
                    if handler and hasattr(handler, 'get_client_info'):
                        info = handler.get_client_info(client_id)
                        if info:
                            # Преобразуем в dict если нужно
                            if hasattr(info, '__dict__'):
                                return info.__dict__
                            return info
                    return None
                except Exception as e:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Ошибка получения информации о клиенте {client_id}: {e}",
                        plugin="client_manager"
                    )
                    return None
            
            # Регистрируем сервисы
            await self.runtime.service_registry.register("client_manager.get_clients", get_clients)
            await self.runtime.service_registry.register("client_manager.get_client_info", get_client_info)
            
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Client Manager сервисы зарегистрированы",
                plugin="client_manager"
            )
        except Exception as e:
            # Не критично, если не удалось зарегистрировать сервисы
            await self.runtime.service_registry.call(
                "logger.log",
                level="warning",
                message=f"Не удалось зарегистрировать Client Manager сервисы: {e}",
                plugin="client_manager"
            )
    
    async def on_stop(self) -> None:
        """Остановка: останавливаем сервер."""
        await super().on_stop()
        
        if self._server is not None:
            self._server.should_exit = True
        
        if self._thread is not None:
            try:
                await asyncio.to_thread(self._thread.join, timeout=2)
            except Exception:
                pass
        
        await self.runtime.service_registry.call(
            "logger.log",
            level="info",
            message="Client Manager остановлен",
            plugin="client_manager"
        )
    
    async def on_unload(self) -> None:
        """Выгрузка: cleanup."""
        await super().on_unload()
        
        # Отменяем регистрацию сервисов
        try:
            await self.runtime.service_registry.unregister("client_manager.get_clients")
            await self.runtime.service_registry.unregister("client_manager.get_client_info")
        except Exception:
            pass
        
        self._app = None
        self._server = None
        self._thread = None
        self._handler = None
