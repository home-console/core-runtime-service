"""
HTTP-интеграция Client Manager Service в основной FastAPI‑приложение.

Выделена из ClientManagerPlugin, чтобы плагин не содержал напрямую
всю FastAPI/WS‑логику и мог делегировать интеграцию отдельному адаптеру.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect


LogFunc = Callable[[str, str], Awaitable[None]]
ConfigFunc = Callable[[str, Optional[str]], Awaitable[Optional[str]]]


async def integrate_into_main_app(
    main_app: Any,
    *,
    get_config: ConfigFunc,
    log: LogFunc,
    plugin_name: str = "client_manager",
) -> Any:
    """
    Интегрировать client-manager-service в основной FastAPI‑app.

    Возвращает созданный WebSocketHandler, чтобы вызывающий код
    мог управлять его жизненным циклом (cleanup и т.п.).
    """
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
    try:
        from app.routes import admin_messages
    except Exception:
        admin_messages = None

    import json
    import asyncio

    # Инициализируем WebSocketHandler
    handler = WebSocketHandler()
    set_websocket_handler(handler)

    # Инициализируем AuthService
    try:
        auth_service = AuthService()
        handler.auth_service = auth_service
    except Exception as e:  # pragma: no cover - best-effort логирование
        await log("warning", f"AuthService не инициализирован: {e}")

    # Запускаем фоновые задачи
    try:
        await handler.start_background_tasks()
    except Exception as e:  # pragma: no cover - best-effort логирование
        await log("warning", f"Не удалось запустить фоновые задачи: {e}")

    # Получаем префикс для WebSocket endpoints через конфиг
    ws_prefix = await get_config("ws_prefix", None) or ""
    ws_path = f"{ws_prefix}/ws" if ws_prefix else "/ws"
    admin_ws_path = f"{ws_prefix}/admin/ws" if ws_prefix else "/admin/ws"

    # Монтируем WebSocket endpoints
    @main_app.websocket(ws_path)
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint для клиентов."""
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

        token = websocket.query_params.get("token")
        if not token:
            sp = websocket.headers.get("sec-websocket-protocol")
            if sp:
                token_candidate = sp.split(",")[0].strip()
                if token_candidate.lower().startswith("bearer "):
                    token = token_candidate[7:]
                else:
                    token = token_candidate

        try:
            await websocket.accept()
        except Exception:  # pragma: no cover
            return

        if not token:
            await websocket.send_text('{"type":"auth_required","message":"Token required"}')
            await websocket.close(code=1008, reason="Auth required")
            return

        auth_svc = getattr(handler, "auth_service", None)
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
        await handler.websocket_manager.connect(
            websocket,
            admin_id,
            metadata={"admin": True, "permissions": payload.get("permissions", [])},
        )

        try:
            clients_list = handler.get_all_clients()
            await websocket.send_text(json.dumps({"type": "client_list", "data": clients_list}))
        except Exception as e:  # pragma: no cover
            await log("warning", f"Ошибка при отправке списка клиентов админу: {e}")

        try:
            async def periodic_refresh() -> None:
                prev_snapshot = None
                while True:
                    await asyncio.sleep(5)
                    try:
                        clients_list = handler.get_all_clients()
                        snapshot = json.dumps(clients_list)
                        if snapshot != prev_snapshot:
                            prev_snapshot = snapshot
                            await websocket.send_text(
                                json.dumps({"type": "client_list_refresh", "data": clients_list})
                            )
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

                if msg.get("type") == "get_clients":
                    await websocket.send_text(
                        json.dumps({"type": "client_list", "data": handler.get_all_clients()})
                    )
                elif msg.get("type") == "ping":
                    await websocket.send_text('{"type":"pong"}')
                else:
                    await websocket.send_text(
                        json.dumps({"type": "unknown_command", "received": msg.get("type")})
                    )

        except WebSocketDisconnect:
            pass
        except Exception as e:  # pragma: no cover
            await log("error", f"Ошибка в admin websocket loop: {e}")
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
    main_app.include_router(
        installations.router, prefix="/api/client-manager", tags=["Client Manager - Installations"]
    )
    main_app.include_router(
        universal_commands.router, prefix="/api/client-manager", tags=["Client Manager - Universal Commands"]
    )
    main_app.include_router(
        cloud.router, prefix="/api/client-manager/cloud", tags=["Client Manager - Cloud Services"]
    )
    main_app.include_router(
        terminal.router, prefix="/api/client-manager", tags=["Client Manager - Terminal"]
    )
    main_app.include_router(audit_queue.router, prefix="/api/client-manager", tags=["Client Manager - Audit"])

    # Health endpoint без префикса для совместимости
    main_app.include_router(health.router, tags=["Client Manager - Health"])

    if admin_messages is not None:  # pragma: no cover - optional
        main_app.include_router(
            admin_messages.router, prefix="/api/client-manager", tags=["Client Manager - Admin"]
        )

    await log("info", "Client Manager интегрирован в основной API (integrated режим)")

    return handler

