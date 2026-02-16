"""
Client Manager Plugin — интеграция client-manager-service как плагина.

Поддерживает два режима работы:
1. integrated - монтирует роуты в основной API (порт 8000)
2. standalone - запускает отдельный FastAPI сервер (порт 10000)

Режим выбирается через переменную окружения CLIENT_MANAGER_MODE (по умолчанию: standalone).
"""
import sys
import threading
import asyncio
from pathlib import Path
from typing import Optional, Any, Literal

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
    
    Поддерживает два режима работы:
    - integrated: монтирует роуты в основной API через ApiModule
    - standalone: запускает отдельный FastAPI сервер в отдельном потоке
    
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
        self._mode: Literal["integrated", "standalone"] = "standalone"
        self._lifespan_context = None
    
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
        """Загрузка: определяем режим работы и импортируем зависимости."""
        await super().on_load()
        
        # Определяем режим работы через компоненты ядра (Storage API)
        # Сначала проверяем storage, потом fallback на env
        mode = await self._get_config("mode", default="standalone")
        if mode:
            mode = mode.lower()
        else:
            mode = "standalone"
            
        if mode not in ("integrated", "standalone"):
            await _safe_log(self.runtime, "warning", f"Неизвестный режим {mode}, используем standalone")
            mode = "standalone"
        self._mode = mode
        
        # Проверяем наличие uvicorn (нужен для standalone режима)
        if mode == "standalone" and uvicorn is None:
            await _safe_log(self.runtime, "error", "uvicorn не установлен. Установите: pip install uvicorn")
            raise ImportError("uvicorn is required for client_manager plugin in standalone mode")
        
        # Добавляем путь к client-manager-service в sys.path для импортов
        client_manager_path = Path(__file__).parent.parent / "client-manager-service"
        if str(client_manager_path) not in sys.path:
            sys.path.insert(0, str(client_manager_path))
        
        # В режиме integrated не создаём app здесь, это будет сделано в on_start
        # В режиме standalone создаём app как раньше
        if mode == "standalone":
            try:
                from app.main import create_app
                self._app = create_app()
                
                # Получаем handler для регистрации сервисов
                from app.dependencies import get_websocket_handler
                try:
                    self._handler = get_websocket_handler()
                except Exception:
                    # Handler может быть не инициализирован до старта
                    self._handler = None
                
                await _safe_log(self.runtime, "info", "Client Manager app создан (standalone режим)")
            except ImportError as e:
                await _safe_log(self.runtime, "error", f"Не удалось импортировать client-manager app: {e}")
                raise
            except Exception as e:
                await _safe_log(self.runtime, "error", f"Ошибка при создании Client Manager app: {e}")
                raise
        else:
            await _safe_log(self.runtime, "info", "Client Manager будет интегрирован в основной API (integrated режим)")
    
    async def on_start(self) -> None:
        """Запуск: в зависимости от режима интегрируем или запускаем отдельный сервер."""
        await super().on_start()
        
        if self._mode == "integrated":
            await self._start_integrated_mode()
        else:
            await self._start_standalone_mode()
        
        # Регистрируем сервисы для доступа к ClientManager из других плагинов
        await self._register_services()
    
    async def _start_integrated_mode(self) -> None:
        """Режим интеграции: монтируем роуты в основной API."""
        try:
            # Получаем ApiModule
            api_module = self.runtime.module_manager.get_module("api")
            if api_module is None or api_module.app is None:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message="ApiModule не найден или не инициализирован",
                    plugin="client_manager"
                )
                raise RuntimeError("ApiModule not available for integrated mode")
            
            main_app = api_module.app
            
            # Импортируем зависимости client-manager-service
            from app.core.websocket_handler import WebSocketHandler
            from app.core.security.auth_service import AuthService
            from app.dependencies import set_websocket_handler, get_websocket_handler
            from app.routes import (
                clients,
                commands,
                health,
                files,
                secrets,
                enrollments,
                universal_commands,
                installations,
                cloud,
                terminal,
                audit_queue,
            )
            from fastapi import WebSocket, WebSocketDisconnect
            import json
            import asyncio
            
            # Инициализируем WebSocketHandler
            handler = WebSocketHandler()
            set_websocket_handler(handler)
            self._handler = handler
            
            # Инициализируем AuthService
            try:
                auth_service = AuthService()
                handler.auth_service = auth_service
            except Exception as e:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"AuthService не инициализирован: {e}",
                    plugin="client_manager"
                )
            
            # Запускаем фоновые задачи
            try:
                await handler.start_background_tasks()
            except Exception as e:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Не удалось запустить фоновые задачи: {e}",
                    plugin="client_manager"
                )
            
            # Получаем префикс для WebSocket endpoints через компоненты ядра
            ws_prefix = await self._get_config("ws_prefix", default="")
            ws_path = f"{ws_prefix}/ws" if ws_prefix else "/ws"
            admin_ws_path = f"{ws_prefix}/admin/ws" if ws_prefix else "/admin/ws"
            
            # Монтируем WebSocket endpoints
            @main_app.websocket(ws_path)
            async def websocket_endpoint(websocket: WebSocket):
                """WebSocket endpoint для клиентов"""
                if handler:
                    await handler.handle_websocket(websocket)
                else:
                    await websocket.close(code=1011, reason="Server not ready")
            
            @main_app.websocket(admin_ws_path)
            async def admin_websocket_endpoint(websocket: WebSocket):
                """Админский WebSocket endpoint. Ожидает JWT в query param `token`."""
                if not handler:
                    await websocket.close(code=1011, reason="Server not ready")
                    return
                
                token = websocket.query_params.get('token')
                if not token:
                    sp = websocket.headers.get('sec-websocket-protocol')
                    if sp:
                        token_candidate = sp.split(',')[0].strip()
                        if token_candidate.lower().startswith('bearer '):
                            token = token_candidate[7:]
                        else:
                            token = token_candidate
                
                try:
                    await websocket.accept()
                except Exception:
                    return
                
                if not token:
                    await websocket.send_text('{"type":"auth_required","message":"Token required"}')
                    await websocket.close(code=1008, reason="Auth required")
                    return
                
                auth_svc = getattr(handler, 'auth_service', None)
                if not auth_svc:
                    await websocket.send_text('{"type":"auth_unavailable","message":"Auth service unavailable"}')
                    await websocket.close(code=1011, reason="Auth service unavailable")
                    return
                
                payload = auth_svc.verify_token(token)
                if not payload:
                    await websocket.send_text('{"type":"auth_failed","message":"Invalid token"}')
                    await websocket.close(code=1008, reason="Invalid token")
                    return
                
                admin_id = f"admin:{payload.get('client_id', 'unknown')}"
                await handler.websocket_manager.connect(websocket, admin_id, metadata={"admin": True, "permissions": payload.get('permissions', [])})
                
                try:
                    clients_list = handler.get_all_clients()
                    await websocket.send_text(json.dumps({"type": "client_list", "data": clients_list}))
                except Exception as e:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="warning",
                        message=f"Ошибка при отправке списка клиентов админу: {e}",
                        plugin="client_manager"
                    )
                
                try:
                    async def periodic_refresh():
                        prev_snapshot = None
                        while True:
                            await asyncio.sleep(5)
                            try:
                                clients_list = handler.get_all_clients()
                                snapshot = json.dumps(clients_list)
                                if snapshot != prev_snapshot:
                                    prev_snapshot = snapshot
                                    await websocket.send_text(json.dumps({"type": "client_list_refresh", "data": clients_list}))
                            except Exception:
                                break
                    
                    refresh_task = asyncio.create_task(periodic_refresh())
                    
                    while True:
                        text = await websocket.receive_text()
                        try:
                            msg = json.loads(text)
                        except Exception:
                            await websocket.send_text('{"type":"error","message":"Invalid JSON"}')
                            continue
                        
                        if msg.get('type') == 'get_clients':
                            await websocket.send_text(json.dumps({"type": "client_list", "data": handler.get_all_clients()}))
                        elif msg.get('type') == 'ping':
                            await websocket.send_text('{"type":"pong"}')
                        else:
                            await websocket.send_text(json.dumps({"type": "unknown_command", "received": msg.get('type')}))
                
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Ошибка в admin websocket loop: {e}",
                        plugin="client_manager"
                    )
                finally:
                    try:
                        refresh_task.cancel()
                    except Exception:
                        pass
                    await handler.websocket_manager.disconnect(admin_id)
            
            # Монтируем REST API роуты
            # Используем префикс /api/client-manager чтобы не конфликтовать с основными роутами
            main_app.include_router(clients.router, prefix="/api/client-manager", tags=["Client Manager - Clients"])
            main_app.include_router(commands.router, prefix="/api/client-manager", tags=["Client Manager - Commands"])
            main_app.include_router(files.router, prefix="/api/client-manager", tags=["Client Manager - Files"])
            main_app.include_router(secrets.router, prefix="/api/client-manager", tags=["Client Manager - Secrets"])
            main_app.include_router(enrollments.router, prefix="/api/client-manager", tags=["Client Manager - Enrollments"])
            main_app.include_router(installations.router, prefix="/api/client-manager", tags=["Client Manager - Installations"])
            main_app.include_router(universal_commands.router, prefix="/api/client-manager", tags=["Client Manager - Universal Commands"])
            main_app.include_router(cloud.router, prefix="/api/client-manager/cloud", tags=["Client Manager - Cloud Services"])
            main_app.include_router(terminal.router, prefix="/api/client-manager", tags=["Client Manager - Terminal"])
            main_app.include_router(audit_queue.router, prefix="/api/client-manager", tags=["Client Manager - Audit"])
            
            # Health endpoint без префикса для совместимости
            main_app.include_router(health.router, tags=["Client Manager - Health"])
            
            try:
                from app.routes import admin_messages
                main_app.include_router(admin_messages.router, prefix="/api/client-manager", tags=["Client Manager - Admin"])
            except Exception:
                pass
            
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message="Client Manager интегрирован в основной API (integrated режим)",
                plugin="client_manager"
            )
            
        except Exception as e:
            await self.runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Ошибка при интеграции Client Manager: {e}",
                plugin="client_manager"
            )
            raise
    
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
        """Остановка: останавливаем сервер или очищаем интеграцию."""
        await super().on_stop()
        
        if self._mode == "standalone":
            if self._server is not None:
                self._server.should_exit = True
            
            if self._thread is not None:
                try:
                    await asyncio.to_thread(self._thread.join, timeout=2)
                except Exception:
                    pass
        else:
            # В режиме integrated очищаем handler
            if self._handler is not None:
                try:
                    await self._handler.cleanup()
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
        self._lifespan_context = None
