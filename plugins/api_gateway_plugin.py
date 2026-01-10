"""
Плагин `api_gateway` — адаптер, автоматически проксирующий HTTP на runtime-сервисы.

Особенности:
- НЕ содержит бизнес-логики
- НЕ хранит список роутов — строит их на основе `runtime.http.list()`
- Использует один универсальный handler, который собирает параметры
  и вызывает `runtime.service_registry.call`

Примечание: этот плагин зависит от `fastapi` и `uvicorn` и должен запускаться
в соответствующем окружении. Плагин сам по себе не выполняет I/O при регистрации.
"""

from typing import Any, Dict
import threading
import asyncio

from fastapi import FastAPI, Request, HTTPException
import uvicorn

from plugins.base_plugin import BasePlugin, PluginMetadata


class ApiGatewayPlugin(BasePlugin):
    """FastAPI-адаптер, проксирующий HTTP-запросы в runtime-сервисы."""

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self.app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="api_gateway",
            version="0.1.0",
            description="Автоматический HTTP-прокси на основе runtime.http",
            author="Home Console",
        )

    async def on_load(self) -> None:
        await super().on_load()
        # Создаём FastAPI приложение. Маршруты регистрируем при старте,
        # чтобы все плагины успели внести свои контракты в runtime.http
        self.app = FastAPI()

    async def on_start(self) -> None:
        await super().on_start()
        if self.app is None:
            return
        # Делаем короткую паузу, чтобы плагины успели зарегистрировать свои
        # HTTP-контракты в `runtime.http` до того, как мы снимем с него список.
        # Без этой паузы api_gateway иногда стартовал раньше других плагинов
        # и не видел зарегистрированных эндпоинтов, в результате OpenAPI
        # возвращал 404 на незарегистрированные пути.
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

                # Построим корректную сигнатуру для FastAPI/OpenAPI.
                # Извлечём имена path-параметров из шаблона пути {param}
                import re
                from fastapi import Path
                import inspect

                pattern = r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}"
                names = re.findall(pattern, endpoint.path)

                # Сигнатура нужна ТОЛЬКО для документирования в OpenAPI.
                # handler на самом деле не принимает path-параметры напрямую,
                # они идут через request.path_params.
                # Поэтому __signature__ должна содержать только "request".
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
            # Запуск сервера в отдельном потоке — используем локальную переменную
            # чтобы статический анализатор не видел возможного None у `self._server`.
            try:
                server.run()
            except SystemExit:
                # uvicorn вызывает SystemExit(1) при ошибке привязки порта;
                # подавляем исключение в потоке и логируем, чтобы pytest
                # не регистрировал unhandled thread exception warning.
                print("[api_gateway] uvicorn exited during startup (port may be in use)")
                return
            except Exception as e:
                # Общий защитный fallback — логируем и завершаем поток.
                print(f"[api_gateway] server run error: {e}")
                return

        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()

    async def on_stop(self) -> None:
        await super().on_stop()
        # Останавливаем сервер, не блокируя event loop
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            # join в отдельном потоке, чтобы не блокировать async loop
            await asyncio.to_thread(self._thread.join, timeout=1)

    async def on_unload(self) -> None:
        await super().on_unload()
        # Очистить ссылки
        self.app = None
        self._server = None
        self._thread = None
