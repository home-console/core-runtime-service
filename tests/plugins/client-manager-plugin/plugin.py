from __future__ import annotations

from sdk import HttpEndpoint
from sdk.plugin_ext import BasePlugin, PluginMetadata


class ClientManagerPlugin(BasePlugin):
    """
    Minimal client-manager plugin implementation used by tests.

    Важно: этот файл лежит под `tests/plugins/**` и проходит через SDK guards,
    поэтому используем только SDK imports и SDK helpers (без core/modules/app).
    """

    def __init__(self, runtime_or_context):
        super().__init__(runtime_or_context)
        # Must not run internal server
        self.server = None
        self.server_task = None
        self._metadata = PluginMetadata(
            name="client-manager",
            version="0.0.0-test",
            description="Test-only client-manager plugin",
        )

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata

    async def on_load(self) -> None:
        async def list_clients():
            return []

        async def get_client(client_id: str):
            return {"id": client_id}

        async def execute_command(client_id: str, command: str, **kwargs):
            return {"ok": True, "client_id": client_id, "command": command}

        async def websocket(*args, **kwargs):
            return {"ok": True}

        async def admin_websocket(*args, **kwargs):
            return {"ok": True}

        await self.register_service("client_manager.list_clients", list_clients)
        await self.register_service("client_manager.get_client", get_client)
        await self.register_service("client_manager.execute_command", execute_command)
        await self.register_service("client_manager.websocket", websocket)
        await self.register_service("client_manager.admin_websocket", admin_websocket)

        self.register_http_endpoint(
            HttpEndpoint(
                path="/client-manager/clients",
                service="client_manager.list_clients",
                method="GET",
            )
        )
        self.register_http_endpoint(
            HttpEndpoint(
                path="/client-manager/clients/{id}",
                service="client_manager.get_client",
                method="GET",
            )
        )
        self.register_http_endpoint(
            HttpEndpoint(
                path="/client-manager/ws",
                service="client_manager.websocket",
                websocket=True,
            )
        )
        self.register_http_endpoint(
            HttpEndpoint(
                path="/client-manager/admin/ws",
                service="client_manager.admin_websocket",
                websocket=True,
            )
        )

