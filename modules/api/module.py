"""
ApiModule — встроенный модуль HTTP API Gateway.

Автоматически проксирует HTTP-запросы на runtime-сервисы на основе HttpRegistry.
"""

from typing import Any, Dict
import threading
import asyncio
import re
import inspect

from fastapi import FastAPI, Request, HTTPException, Path
import uvicorn

from core.runtime_module import RuntimeModule


class ApiModule(RuntimeModule):
    """
    Модуль HTTP API Gateway.
    
    Автоматически создаёт HTTP endpoints на основе зарегистрированных
    контрактов в runtime.http и проксирует запросы в runtime-сервисы.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "api"

    def __init__(self, runtime: Any):
        """Инициализация модуля."""
        super().__init__(runtime)
        self.app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    async def register(self) -> None:
        """
        Регистрация модуля в CoreRuntime.
        
        Создаёт FastAPI приложение. Маршруты регистрируются при старте,
        чтобы все модули и плагины успели внести свои контракты в runtime.http.
        """
        self.app = FastAPI(title="Home Console API", version="0.1.0")

    async def start(self) -> None:
        """
        Запуск модуля.
        
        Регистрирует HTTP маршруты на основе текущего состояния HttpRegistry
        и запускает HTTP сервер.
        """
        if self.app is None:
            return
        
        # Делаем короткую паузу, чтобы модули и плагины успели зарегистрировать свои
        # HTTP-контракты в `runtime.http` до того, как мы снимем с него список.
        try:
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # Регистрируем маршруты на основе текущего состояния HttpRegistry.
        endpoints = self.runtime.http.list()

        for ep in endpoints:
            def make_handler(endpoint):
                async def handler(request: Request):
                    params: Dict[str, Any] = {}
                    # path params доступны через request.path_params
                    params.update(request.path_params)
                    for k, v in request.query_params.multi_items():
                        params[k] = v
                    body = None
                    try:
                        body = await request.json()
                    except Exception:
                        body = None

                    # Передаём body отдельно от query/path params только если он не None
                    # Не мержим body в params, чтобы сохранить структуру данных
                    if body is not None:
                        params["body"] = body

                    if not await self.runtime.service_registry.has_service(endpoint.service):
                        raise HTTPException(status_code=404, detail="service not found")

                    try:
                        result = await self.runtime.service_registry.call(endpoint.service, **params)
                    except Exception as e:
                        # Map ValueError from services to HTTP 400 (bad request)
                        if isinstance(e, ValueError):
                            raise HTTPException(status_code=400, detail=str(e))
                        raise HTTPException(status_code=500, detail=str(e))

                    return result

                # Сигнатура нужна ТОЛЬКО для документирования в OpenAPI.
                # handler на самом деле не принимает path-параметры напрямую,
                # они идут через request.path_params.
                params_sig = [
                    inspect.Parameter(
                        "request",
                        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Request,
                    )
                ]

                handler.__signature__ = inspect.Signature(parameters=params_sig)
                return handler

            handler = make_handler(ep)
            route_name = f"{ep.method}_{ep.path}"
            # HttpRegistry теперь нормализует пути, удаляя завершающий '/'.
            # Дублирование со слэшем и без слэша больше не нужно.
            self.app.add_api_route(ep.path, handler, methods=[ep.method], name=route_name)

        config = uvicorn.Config(self.app, host="127.0.0.1", port=8000, log_level="info")
        server = uvicorn.Server(config)
        self._server = server

        def run_server():
            # Запуск сервера в отдельном потоке
            try:
                server.run()
            except SystemExit:
                # uvicorn вызывает SystemExit(1) при ошибке привязки порта;
                # подавляем исключение в потоке и логируем
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        self.runtime.service_registry.call(
                            "logger.log",
                            level="warning",
                            message="uvicorn exited during startup (port may be in use)",
                            module="api"
                        )
                    )
                    loop.close()
                except Exception:
                    pass
                return
            except Exception as e:
                # Общий защитный fallback — логируем и завершаем поток.
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        self.runtime.service_registry.call(
                            "logger.log",
                            level="error",
                            message=f"server run error: {e}",
                            module="api"
                        )
                    )
                    loop.close()
                except Exception:
                    pass
                return

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        """
        Остановка модуля.
        
        Останавливает HTTP сервер.
        """
        # Останавливаем сервер, не блокируя event loop
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            # join в отдельном потоке, чтобы не блокировать async loop
            await asyncio.to_thread(self._thread.join, timeout=1)
