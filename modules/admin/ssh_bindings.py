from __future__ import annotations

import logging
from typing import Any

from core.http.models import HttpEndpoint, EndpointAuthConfig

logger = logging.getLogger(__name__)


async def register_ssh_bindings(runtime: Any, context: Any) -> list[str]:
    registered_services: list[str] = []
    services = context.services

    try:
        from .services import ssh_terminal as ssh_mod
        _admin_write = EndpointAuthConfig(required_scopes=["admin.write"])
        _admin_read = EndpointAuthConfig(required_scopes=["admin.read"])

        async def _ssh_create(body: dict = None, **kw):
            return await ssh_mod.http_create_session(runtime, body)

        async def _ssh_list(**kw):
            return await ssh_mod.http_list_sessions(runtime)

        async def _ssh_close(session_id: str, **kw):
            return await ssh_mod.http_close_session(runtime, session_id)

        async def _ssh_ws(websocket: Any, session_id: str = None, **kw):
            if not session_id:
                await websocket.close(code=1008, reason="session_id required")
                return
            await ssh_mod.attach_websocket(websocket, session_id)

        for service_name, handler in [
            ("admin.v1.ssh.sessions.create", _ssh_create),
            ("admin.v1.ssh.sessions.list", _ssh_list),
            ("admin.v1.ssh.sessions.close", _ssh_close),
            ("admin.v1.ssh.ws", _ssh_ws),
        ]:
            await services.register_with_acl(service_name, handler, admin_only=True)
            registered_services.append(service_name)

        for endpoint in [
            HttpEndpoint(method="POST", path="/admin/v1/ssh/sessions", service="admin.v1.ssh.sessions.create", description="Create SSH PTY session", auth_config=_admin_write),
            HttpEndpoint(method="GET", path="/admin/v1/ssh/sessions", service="admin.v1.ssh.sessions.list", description="List SSH PTY sessions", auth_config=_admin_read),
            HttpEndpoint(method="DELETE", path="/admin/v1/ssh/sessions/{session_id}", service="admin.v1.ssh.sessions.close", description="Close SSH PTY session", auth_config=_admin_write),
            HttpEndpoint(path="/admin/v1/ssh/ws/{session_id}", service="admin.v1.ssh.ws", websocket=True, description="Attach WebSocket to SSH PTY session", auth_config=_admin_write),
        ]:
            context.http.register(endpoint)
    except Exception as e:
        logger.warning("Failed to register SSH terminal endpoints: %s", e, exc_info=True)

    return registered_services
