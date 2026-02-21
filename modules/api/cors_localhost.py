"""
CORS: в development разрешаем любой origin с хостом localhost или 127.0.0.1 (любой порт).
Фронт (Vite и др.) часто поднимается на случайном порту — preflight и запросы должны проходить.
"""

from __future__ import annotations

from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


def _is_localhost_origin(origin: str | None) -> bool:
    if not origin or not origin.strip():
        return False
    try:
        parsed = urlparse(origin.strip())
        return (
            parsed.scheme in ("http", "https")
            and parsed.hostname in ("localhost", "127.0.0.1")
        )
    except Exception:
        return False


class LocalhostCORSMiddleware(BaseHTTPMiddleware):
    """
    В dev разрешает CORS для любого origin вида http(s)://localhost:* и http(s)://127.0.0.1:*.
    Обрабатывает preflight (OPTIONS) и добавляет заголовки к ответам.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        origin = request.headers.get("origin")
        if not _is_localhost_origin(origin):
            return await call_next(request)

        # Preflight: сразу отвечаем 200 с CORS-заголовками.
        # С credentials: true браузер не принимает Access-Control-Allow-Headers: * —
        # нужно вернуть запрошенные заголовки (эхо Access-Control-Request-Headers)
        # или явный список; эхо безопасно для localhost.
        if request.method == "OPTIONS":
            requested_headers = request.headers.get("access-control-request-headers")
            allow_headers = requested_headers if requested_headers else "content-type, authorization, x-csrf-token, accept"
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": allow_headers,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Max-Age": "86400",
                },
            )

        response = await call_next(request)
        # Добавляем заголовки к ответу основного запроса
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
