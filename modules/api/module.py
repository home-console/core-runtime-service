"""
ApiModule — HTTP API Gateway (FastAPI + uvicorn).

Вся логика HTTP только здесь. Runtime не знает про FastAPI/uvicorn;
после start() вызывает api_module.run_http(runtime).
Маршруты привязываются в run_http() — после старта модулей и плагинов.
"""

from __future__ import annotations

from typing import Any, Dict
import os
import asyncio
import signal
from contextlib import nullcontext

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from core.runtime_module import RuntimeModule
from modules.api.auth.middleware import require_auth_middleware
from modules.api.admin_access_middleware import admin_access_middleware
from modules.monitoring import MonitoringModule


class ApiModule(RuntimeModule):
    """Модуль API: владеет FastAPI app и uvicorn. Запуск HTTP через run_http(runtime)."""

    @property
    def name(self) -> str:
        return "api"

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime)
        self.app: FastAPI | None = None
        self._server: uvicorn.Server | None = None

    async def register(self) -> None:
        """Только bootstrap HTTP-контрактов в runtime.http."""
        try:
            from core.adapters.http.bootstrap import register_core_http
            register_core_http(self.runtime)
        except ImportError:
            pass

    async def start(self) -> None:
        """No-op. HTTP стартует в run_http() после start всех модулей и плагинов."""
        pass

    async def stop(self) -> None:
        """Сигнал серверу выйти."""
        if self._server is not None:
            self._server.should_exit = True

    def _build_app(self, runtime: Any) -> None:
        """Создаёт FastAPI app, middleware и роутеры. Вызывается из run_http()."""
        self.app = FastAPI(title="Home Console API", version="0.1.0", openapi_url="/openapi.json")
        self.app.state.runtime = runtime

        cors_allowed = None
        is_dev = True
        try:
            cfg = getattr(runtime, "_config", None)
            if cfg:
                cors_allowed = getattr(cfg, "cors_allowed_origins", None)
                is_dev = getattr(cfg, "env", "production") == "development"
        except Exception:
            pass
        
        # CORS configuration
        if is_dev:
            # Development: allow any localhost origin (any port)
            cors_kw: Dict[str, Any] = {
                "allow_origin_regex": r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
                "allow_credentials": True,
                "allow_methods": ["*"],
                "allow_headers": ["*"],
            }
        else:
            # Production: use configured origins or restrict to localhost:3000
            cors_kw: Dict[str, Any] = {
                "allow_origins": cors_allowed or ["http://localhost:3000", "http://127.0.0.1:3000"],
                "allow_credentials": True,
                "allow_methods": ["*"],
                "allow_headers": ["*"],
            }
        
        self.app.add_middleware(CORSMiddleware, **cors_kw)

        try:
            from modules.request_logger.middleware import request_logger_middleware
            self.app.middleware("http")(request_logger_middleware)
        except ImportError:
            pass
        # Middleware execution order (first registered = outermost = runs first on request):
        # require_auth → admin_access → csrf → rate_limit → security_headers
        # require_auth must run BEFORE csrf so that auth_context is populated when csrf checks it.
        self.app.middleware("http")(require_auth_middleware)
        self.app.middleware("http")(admin_access_middleware)
        try:
            from modules.api.csrf_middleware import csrf_protection_middleware, rate_limit_middleware
            self.app.middleware("http")(csrf_protection_middleware)
            self.app.middleware("http")(rate_limit_middleware)
        except ImportError:
            pass
        from modules.api.security_headers import security_headers_middleware
        self.app.middleware("http")(security_headers_middleware)

        self.app.include_router(MonitoringModule(runtime=runtime).router, prefix="/monitor", tags=["monitoring"])
        try:
            from modules.request_logger.router import create_request_logger_router
            self.app.include_router(create_request_logger_router(runtime))
        except ImportError:
            pass

    async def _log(self, runtime: Any, level: str, message: str, **ctx: Any) -> None:
        try:
            services = runtime.kernel_context.get_service("service_registry")
            await services.call(
                "logger.log",
                level=level,
                message=message,
                component="api",
                **ctx,
            )
        except Exception:
            pass

    async def run_http(self, runtime: Any) -> None:
        """
        Запуск HTTP: app + привязка маршрутов (после start) + uvicorn.
        Вызывается из Runtime.run() после runtime.start().
        """
        await self._log(runtime, "info", "API: run_http entered")
        self._build_app(runtime)
        await self._log(runtime, "info", "API: app built")

        from modules.api.route_binding import bind_routes
        bind_routes(runtime, self.app)
        await self._log(runtime, "info", "API: routes bound")

        # Log registered WebSocket endpoints for easy debugging
        ws_eps = [ep for ep in runtime.http.list() if ep.websocket]
        if ws_eps:
            ws_paths = ", ".join(ep.path for ep in ws_eps)
            await self._log(runtime, "info", f"[API] WebSocket endpoints: {ws_paths}")

        api_host = os.getenv("API_HOST", "0.0.0.0")
        api_port = int(os.getenv("API_PORT", "8000"))
        uvicorn_log_level = os.getenv("UVICORN_LOG_LEVEL", "warning")
        config = uvicorn.Config(
            self.app,
            host=api_host,
            port=api_port,
            log_level=uvicorn_log_level,
            access_log=False,
        )
        await self._log(runtime, "info", "API: uvicorn config created")
        server = uvicorn.Server(config)
        server.capture_signals = lambda: nullcontext()  # type: ignore[method-assign]
        self._server = server
        await self._log(runtime, "info", "API: server object created")

        loop = asyncio.get_running_loop()
        await self._log(runtime, "info", f"Current loop: {loop!r}")
        sigint_count = [0]

        def _on_sigint() -> None:
            sigint_count[0] += 1
            if sigint_count[0] == 1:
                server.should_exit = True
            else:
                os._exit(1)

        try:
            if hasattr(loop, "add_signal_handler"):
                loop.add_signal_handler(signal.SIGINT, _on_sigint)
            else:
                raise OSError("no add_signal_handler")
        except (OSError, ValueError):
            signal.signal(signal.SIGINT, lambda s, f: loop.call_soon_threadsafe(_on_sigint))

        await self._log(runtime, "info", f"[API] HTTP на http://{api_host}:{api_port}")
        # Креды в терминал: URL и опционально dev API key для подключения веба
        display_host = "127.0.0.1" if api_host == "0.0.0.0" else api_host
        api_base_url = f"http://{display_host}:{api_port}"
        print(f"[Runtime] API: {api_base_url} — для веба: VITE_API_BASE_URL={api_base_url}")
        if os.getenv("DEV_CREDENTIALS", "").strip() == "1":
            dev_key = (os.getenv("DEV_API_KEY") or "").strip()
            if dev_key:
                print(f"[Runtime] Dev API key (для веба): {dev_key}")
            else:
                print("[Runtime] DEV_CREDENTIALS=1, но DEV_API_KEY не задан — создайте API key и укажите в .env")
        await self._log(runtime, "info", f"Server should_exit: {self._server.should_exit}")
        await self._log(runtime, "info", "API: about to call serve()")
        await server.serve()
        await self._log(runtime, "info", "API: serve() returned")
