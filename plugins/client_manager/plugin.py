"""
Client Manager Plugin — регистрация endpoints через HttpRegistry.

Регистрирует WebSocket и REST endpoints через HttpRegistry,
которые автоматически монтируются ApiModule'ом в основной API.
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


async def _safe_log(runtime: Any, level: str, message: str, plugin: str = "client_manager") -> None:
    """
    Безопасное логирование с fallback на print.
    
    Используется в on_load(), когда logger.log может быть ещё недоступен.
    """
    try:
        if runtime and hasattr(runtime, 'service_registry'):
            await runtime.service_registry.call(
                "logger.log",
                level=level,
                message=message,
                plugin=plugin
            )
            return
    except Exception:
        # Если logger.log недоступен - используем print как fallback
        pass
    
    # Fallback на print
    print(f"[{level.upper()}] [{plugin}] {message}", file=sys.stderr)


class ClientManagerPlugin(BasePlugin):
    """
    Плагин для Client Manager Service.
    
    Регистрирует WebSocket и REST endpoints через HttpRegistry.
    Конфигурация:
    - Читается из runtime.storage (namespace: "plugin_config", key: "client_manager")
    - Fallback на переменные окружения если конфигурация в storage отсутствует
    - Соответствует архитектуре Core Runtime - плагины работают через компоненты ядра
    """
    
    # Namespace для хранения конфигурации в storage
    CONFIG_NAMESPACE = "plugin_config"
    CONFIG_KEY = "client_manager"
    
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
    
    async def _get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Получить конфигурацию через компоненты ядра (Storage API).
        
        Порядок проверки:
        1. runtime.storage (namespace: "plugin_config", key: "client_manager")
        2. Переменные окружения (через get_env_config)
        
        Соответствует архитектуре Core Runtime - плагины работают через компоненты ядра.
        
        Args:
            key: имя параметра конфигурации
            default: значение по умолчанию
            
        Returns:
            Значение конфигурации или default
        """
        # Сначала проверяем storage (компонент ядра)
        if self.runtime and hasattr(self.runtime, 'storage'):
            try:
                config = await self.runtime.storage.get(self.CONFIG_NAMESPACE, self.CONFIG_KEY)
                if config and isinstance(config, dict) and key in config:
                    value = config.get(key)
                    if value is not None:
                        return str(value)
            except Exception:
                # Если storage недоступен или ошибка - fallback на env
                pass
        
        # Fallback на переменные окружения (для обратной совместимости)
        # Маппинг ключей для переменных окружения
        env_key_map = {
            "mode": "CLIENT_MANAGER_MODE",
            "host": "CLIENT_MANAGER_HOST",
            "port": "CLIENT_MANAGER_PORT",
            "ws_prefix": "CLIENT_MANAGER_WS_PREFIX",
        }
        env_key = env_key_map.get(key, f"CLIENT_MANAGER_{key.upper()}")
        return self.get_env_config(env_key, default=default)
    
    async def _set_config(self, key: str, value: str) -> None:
        """
        Сохранить конфигурацию через компоненты ядра (Storage API).
        
        Соответствует архитектуре Core Runtime - плагины работают через компоненты ядра.
        
        Args:
            key: имя параметра конфигурации
            value: значение для сохранения
        """
        if not self.runtime or not hasattr(self.runtime, 'storage'):
            return
        
        try:
            # Получаем текущую конфигурацию
            config = await self.runtime.storage.get(self.CONFIG_NAMESPACE, self.CONFIG_KEY)
            if not config or not isinstance(config, dict):
                config = {}
            
            # Обновляем значение
            config[key] = value
            
            # Сохраняем обратно в storage
            await self.runtime.storage.set(self.CONFIG_NAMESPACE, self.CONFIG_KEY, config)
        except Exception:
            # Если не удалось сохранить - игнорируем (не критично)
            pass
    
    async def on_load(self) -> None:
        """Загрузка: регистрируем HTTP endpoints через HttpRegistry."""
        await super().on_load()
        
        # Импортируем HttpEndpoint для регистрации
        from core.http_registry import HttpEndpoint
        
        # Регистрируем REST endpoints через HttpRegistry
        # Все endpoints идут в /api/client-manager prefix
        endpoints = [
            HttpEndpoint(
                path="/api/client-manager/clients",
                method="GET",
                service="client_manager.get_clients",
                description="Get list of all connected clients",
                tags=["client_manager", "clients"]
            ),
            HttpEndpoint(
                path="/api/client-manager/clients/{client_id}",
                method="GET",
                service="client_manager.get_client_info",
                description="Get information about a specific client",
                tags=["client_manager", "clients"]
            ),
            # Регистрируем WebSocket endpoint
            HttpEndpoint(
                path="/api/client-manager/ws",
                service="client_manager.websocket",
                websocket=True,
                description="WebSocket endpoint for client connections",
                tags=["client_manager"]
            ),
            HttpEndpoint(
                path="/api/client-manager/admin/ws",
                service="client_manager.admin_websocket",
                websocket=True,
                description="Admin WebSocket endpoint for management",
                tags=["client_manager", "admin"]
            ),
        ]
        
        for endpoint in endpoints:
            self.runtime.http.register(endpoint)
        
        await _safe_log(self.runtime, "info", f"Client Manager зарегистрировал {len(endpoints)} endpoints через HttpRegistry")
    
    async def on_start(self) -> None:
        """Запуск: запускаем WebSocket handler и регистрируем сервисы."""
        await super().on_start()
        
        # Теперь все endpoints зарегистрированы через HttpRegistry
        # ApiModule будет их автоматически монтировать
        
        # Если нужен отдельный сервер (standalone режим), запускаем его
        # Но основная функциональность работает через HttpRegistry
        await self._register_services()
        
        # Опционально: запускаем standalone сервер если установлены нужные переменные
        mode = await self._get_config("mode", default="none") or "none"
        if mode.lower() == "standalone":
            await self._start_standalone_mode()
    
    async def _start_standalone_mode(self) -> None:
        """Режим прокси: запускаем отдельный сервер."""
        if self._app is None:
            return
        
        # Получаем конфигурацию через компоненты ядра
        host = await self._get_config("host", default="0.0.0.0") or "0.0.0.0"
        port_str = await self._get_config("port", default="10000") or "10000"
        try:
            port = int(port_str)
        except (ValueError, TypeError):
            port = 10000
        
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
            message=f"Client Manager запущен на {host}:{port} (standalone режим)",
            plugin="client_manager"
        )
    
    async def _register_services(self) -> None:
        """Регистрирует сервисы Client Manager через ServiceRegistry."""
        try:
            from fastapi import WebSocket, WebSocketDisconnect
            import json
            
            # WebSocket handler для клиентов
            async def websocket_handler(websocket: WebSocket) -> None:
                """WebSocket endpoint для подключения клиентов."""
                try:
                    await websocket.accept()
                    # Базовый echo handler для демонстрации
                    # В реальной реализации здесь должна быть обработка команд
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message="Client подключился к WebSocket",
                        plugin="client_manager"
                    )
                    
                    while True:
                        try:
                            data = await websocket.receive_text()
                            msg = json.loads(data) if data.startswith('{') else {"message": data}
                            # Отправляем echo ответ
                            await websocket.send_json({
                                "type": "echo",
                                "data": msg
                            })
                        except json.JSONDecodeError:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Invalid JSON"
                            })
                except WebSocketDisconnect:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message="Client отключился от WebSocket",
                        plugin="client_manager"
                    )
                except Exception as e:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"WebSocket error: {e}",
                        plugin="client_manager"
                    )
                    try:
                        await websocket.close(code=1011)
                    except Exception:
                        pass
            
            # WebSocket handler для админа
            async def admin_websocket_handler(websocket: WebSocket) -> None:
                """Admin WebSocket endpoint для управления."""
                try:
                    await websocket.accept()
                    
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message="Admin подключился к WebSocket",
                        plugin="client_manager"
                    )
                    
                    while True:
                        try:
                            data = await websocket.receive_text()
                            msg = json.loads(data) if data.startswith('{') else {"message": data}
                            
                            # Обработка админских команд
                            if msg.get("type") == "get_clients":
                                await websocket.send_json({
                                    "type": "client_list",
                                    "data": []  # В реальной реализации здесь должен быть список клиентов
                                })
                            else:
                                await websocket.send_json({
                                    "type": "echo",
                                    "data": msg
                                })
                        except json.JSONDecodeError:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Invalid JSON"
                            })
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Admin WebSocket error: {e}",
                        plugin="client_manager"
                    )
                    try:
                        await websocket.close(code=1011)
                    except Exception:
                        pass
            
            # REST handlers
            async def get_clients() -> dict:
                """Получить список всех клиентов."""
                return {"clients": []}
            
            async def get_client_info(client_id: str) -> Optional[dict]:
                """Получить информацию о клиенте."""
                return {"client_id": client_id, "status": "unknown"}
            
            # Регистрируем сервисы
            await self.runtime.service_registry.register("client_manager.websocket", websocket_handler)
            await self.runtime.service_registry.register("client_manager.admin_websocket", admin_websocket_handler)
            await self.runtime.service_registry.register("client_manager.get_clients", get_clients)
            await self.runtime.service_registry.register("client_manager.get_client_info", get_client_info)
            
            await _safe_log(self.runtime, "info", "Client Manager сервисы зарегистрированы через HttpRegistry")
        except Exception as e:
            await _safe_log(self.runtime, "error", f"Ошибка при регистрации сервисов: {e}")
    
    async def on_stop(self) -> None:
        """Остановка: останавливаем standalone сервер если запущен."""
        await super().on_stop()
        
        # Останавливаем standalone сервер если запущен
        if self._server is not None:
            self._server.should_exit = True
        
        if self._thread is not None:
            try:
                await asyncio.to_thread(self._thread.join, timeout=2)
            except Exception:
                pass
        
        await _safe_log(self.runtime, "info", "Client Manager остановлен")
    
    async def on_unload(self) -> None:
        """Выгрузка: cleanup и отмена регистрации сервисов."""
        await super().on_unload()
        
        # Отменяем регистрацию всех сервисов
        services_to_unregister = [
            "client_manager.websocket",
            "client_manager.admin_websocket",
            "client_manager.get_clients",
            "client_manager.get_client_info",
        ]
        
        for service_name in services_to_unregister:
            try:
                await self.runtime.service_registry.unregister(service_name)
            except Exception:
                pass
        
        # Cleanup
        self._app = None
        self._server = None
        self._thread = None
        self._handler = None
