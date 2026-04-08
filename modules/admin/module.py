"""
AdminModule — Control Plane Host + Inspector Host.

Регистрирует только:
- GET /admin/v1/inspector/* (Inspector: read-only snapshot)
- POST/GET /admin/v1/operations (create / list / get / cancel / retry)
- /admin/v1/auth/* (auth)

Не содержит доменной логики, не регистрирует operations handlers, не знает плагины/домены.
"""

from pathlib import Path
from typing import Any, Optional
import logging
import time

from core.runtime.runtime_module import RuntimeModule

# OrchestrationService (Docker/k8s абстракция) — импортируется из app-layer
from app.orchestration import OrchestrationService

logger = logging.getLogger(__name__)

from .http_endpoints import register_admin_core_http_endpoints
from .plugin_control_bindings import register_plugin_control_bindings
from .device_admin_bindings import register_device_admin_bindings
from .ssh_bindings import register_ssh_bindings
from .service_registrations import build_admin_registrations
from .local_services import create_marketplace_catalog_handler, webhook_test_service

# Auth services moved to AuthModule


class AdminModule(RuntimeModule):
    """
    Модуль административных endpoints.
    Тонкий сборщик: только регистрация сервисов и HTTP endpoints.
    """

    @property
    def name(self) -> str:
        return "admin"

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self._admin_started_at: Optional[float] = None
        self._registered_services: list[str] = []
        # OrchestrationService приходит через runtime DI.
        self._orchestration_service: Optional[OrchestrationService] = getattr(
            runtime, "orchestration_service", None
        )

    async def register(self) -> None:
        self._admin_started_at = time.time()
        self._registered_services = []
        register_admin_core_http_endpoints(self.context.http)

        # No ACL: internal debug/test hook.
        await self.context.services.register("system.webhook_test", webhook_test_service)

        repo_root = Path(__file__).resolve().parent.parent.parent
        marketplace_catalog_handler = create_marketplace_catalog_handler(repo_root=repo_root)

        registrations = build_admin_registrations(
            runtime=self.runtime,
            context=self.context,
            get_admin_started_at=lambda: self._admin_started_at,
            marketplace_catalog_handler=marketplace_catalog_handler,
        )

        # Public services now managed by AuthModule
        for name, handler in registrations:
            try:
                # Allow internal calls to inspector/admin.v1.* services without admin ctx
                if name.startswith("admin.v1."):
                    admin_only = False
                else:
                    # Non-inspector admin services require admin auth (auth services in AuthModule)
                    admin_only = True
                await self.register_raw_service(
                    name,
                    handler,
                    admin_only=admin_only,
                )
                self._registered_services.append(name)
            except ValueError:
                continue

        self._registered_services.extend(
            await register_plugin_control_bindings(
                self.runtime,
                self.context,
                self._orchestration_service,
            )
        )
        self._registered_services.extend(
            await register_device_admin_bindings(self.context)
        )
        self._registered_services.extend(
            await register_ssh_bindings(self.runtime, self.context)
        )

    async def start(self) -> None:
        self._admin_started_at = time.time()

    async def stop(self) -> None:
        for service_name in self._registered_services:
            try:
                await self.context.services.unregister(service_name)
            except Exception:
                logger.warning("Unhandled exception", exc_info=True)
        self._registered_services.clear()
