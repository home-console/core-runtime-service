"""
RemoteServiceRegistry — IServiceRegistry через HTTP.

Drop-in замена ServiceRegistry для случая когда ApiModule
работает в отдельном процессе от Core Runtime.

Протокол:
  POST /internal/v1/services/{service_name}
  Body: {"args": [...], "kwargs": {...}}
  Response: {"result": ..., "error": null}
             {"result": null, "error": "ServiceNotFound: ..."}

Аутентификация: Bearer токен (INTERNAL_API_KEY env var).
Timeout: наследует default_timeout из конфига.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RemoteServiceCallError(Exception):
    """Ошибка удалённого вызова сервиса."""


class RemoteServiceRegistry:
    """
    IServiceRegistry через HTTP к Core Runtime.

    Использование:
        registry = RemoteServiceRegistry(
            base_url="http://core-runtime:8000",
            api_key="secret",
            default_timeout=30.0,
        )
        await registry.start()
        result = await registry.call("devices.get", device_id="abc")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_timeout = float(default_timeout)
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._default_timeout,
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def clear(self) -> None:
        """Compatibility with runtime.shutdown() which calls service_registry.clear()."""

    # ─── IServiceRegistry interface ──────────────────────────────────

    async def call(self, service_name: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call_remote(
            service_name, args, kwargs, timeout=self._default_timeout
        )

    async def call_without_timeout(
        self, service_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._call_remote(service_name, args, kwargs, timeout=None)

    async def call_with_timeout(
        self, service_name: str, timeout: float, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._call_remote(service_name, args, kwargs, timeout=float(timeout))

    async def has_service(self, service_name: str) -> bool:
        if self._client is None:
            raise RuntimeError("RemoteServiceRegistry not started")
        try:
            resp = await self._client.get(f"/internal/v1/services/{service_name}/exists")
            return resp.status_code == 200
        except Exception:
            return False

    async def list_services(self) -> list[str]:
        if self._client is None:
            raise RuntimeError("RemoteServiceRegistry not started")
        resp = await self._client.get("/internal/v1/services")
        resp.raise_for_status()
        body = resp.json()
        services = body.get("services", [])
        return list(services) if isinstance(services, list) else []

    # Stub-методы для совместимости с IServiceRegistry Protocol
    async def register(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "RemoteServiceRegistry: register() not available. "
            "Services are registered in Core Runtime process."
        )

    async def register_with_acl(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("RemoteServiceRegistry: register_with_acl() not available.")

    async def unregister(self, service_name: str) -> None:
        raise NotImplementedError("RemoteServiceRegistry: unregister() not available.")

    async def add_middleware(self, middleware: Any) -> None:
        return

    async def remove_middleware(self, middleware: Any) -> None:
        return

    async def list_middleware(self) -> list[str]:
        return []

    async def get_auth_config(self, service_name: str) -> Any:
        return None

    async def set_auth_config(self, service_name: str, config: Any) -> None:
        return

    # ─── Internal ───────────────────────────────────────────────────

    async def _call_remote(
        self,
        service_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        timeout: float | None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("RemoteServiceRegistry not started. Call start() first.")

        payload = {"args": list(args), "kwargs": kwargs}

        try:
            request_timeout = httpx.Timeout(timeout) if timeout is not None else None
            resp = await self._client.post(
                f"/internal/v1/services/{service_name}",
                json=payload,
                timeout=request_timeout,
            )
        except httpx.TimeoutException:
            raise asyncio.TimeoutError(
                f"Service call '{service_name}' timed out after {timeout}s"
            )
        except httpx.ConnectError as e:
            raise RemoteServiceCallError(f"Cannot connect to Core Runtime: {e}") from e

        body: dict[str, Any]
        try:
            body = resp.json()
        except Exception:
            body = {"error": f"invalid json response (status={resp.status_code})"}

        if resp.status_code == 404:
            raise ValueError(f"Сервис '{service_name}' не найден")

        if resp.status_code != 200:
            error_msg = body.get("error", f"HTTP {resp.status_code}")
            raise RemoteServiceCallError(f"Service '{service_name}' failed: {error_msg}")

        if body.get("error"):
            raise RemoteServiceCallError(str(body["error"]))

        return body.get("result")

