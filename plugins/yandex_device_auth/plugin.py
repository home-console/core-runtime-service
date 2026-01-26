"""
Yandex Device Auth Plugin

Yandex QR-code authentication (magic_x_token):
- User scans QR on phone → confirms in Yandex app
- Backend gets x_token (super-token, 1 year validity)
- x_token used for Quasar API calls

HTTP API:
- POST /yandex/auth/device/start — generate QR URL
- GET /yandex/auth/device/status — check QR confirmation status
- POST /yandex/auth/device/cookies — manual cookie submission
- GET /yandex/auth/device/session — get account session status
- POST /yandex/auth/device/unlink — unlink account

Events:
- yandex.device_auth.linked — account linked
- yandex.device_auth.unlinked — account unlinked

Storage:
- yandex/device_auth/session — account metadata with x_token
"""
from typing import Any, Dict, Optional

from core.base_plugin import BasePlugin, PluginMetadata
from .device_auth_service import YandexDeviceAuthService


class YandexDeviceAuthPlugin(BasePlugin):
    """Yandex Device Authentication Plugin."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="yandex_device_auth",
            version="1.0.0",
            description="Yandex QR-code and password authentication for Quasar",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Register services and HTTP endpoints."""
        await super().on_load()

        self.auth_service = YandexDeviceAuthService(self.runtime)

        async def start_device_auth(
            *, body: Optional[Dict[str, Any]] = None, method: Optional[str] = None, **kwargs
        ) -> Dict[str, Any]:
            """Start QR, cookies, password, or token authorization.

            Args:
                method: "qr", "cookies", "password", "token"
                body: дополнительные параметры:
                    - для "cookies": {"cookies": "..."}
                    - для "password": {"username": "...", "password": "..."}
                    - для "token": {"token": "..."}

            Returns:
                {
                    "qr_url": str (для method="qr"),
                    "oauth_url": str (alias для qr_url),
                    "status": str,
                    "method": str,
                }
            """
            if body and isinstance(body, dict):
                method = body.get("method") or method

            method = method or "qr"

            try:
                return await self.auth_service.start_auth(method, body)
            except Exception as e:
                raise Exception(f"500: {str(e)}")

        async def check_qr_status(
            *, body: Optional[Dict[str, Any]] = None, **kwargs
        ) -> Dict[str, Any]:
            """Check if user confirmed QR authorization.

            Returns:
                {
                    "status": "approved" | "pending",
                    "quasar_ready": bool,
                    "x_token": str (if approved),
                }
            """
            result = await self.auth_service.check_qr_status()
            if result:
                return result
            return {"status": "pending"}

        async def save_cookies(
            *, body: Optional[Dict[str, Any]] = None, cookies: Optional[str] = None, **kwargs
        ) -> Dict[str, Any]:
            """Save cookies from manual submission.

            Args:
                cookies: JSON array or raw cookie string

            Returns:
                {"status": "linked", "quasar_ready": true}
            """
            if body and isinstance(body, dict):
                cookies = body.get("cookies") or cookies

            if not cookies:
                raise ValueError("cookies are required")

            return await self.auth_service.save_cookies(cookies)

        async def get_account_status(
            *, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None, **kwargs
        ) -> Dict[str, Any]:
            """Get account status.

            Returns:
                {"linked": bool, "quasar_ready": bool, "linked_at": float, "method": str}
            """
            return await self.auth_service.get_account_status()

        async def cancel_auth(
            *, body: Optional[Dict[str, Any]] = None, **kwargs
        ) -> Dict[str, Any]:
            """Cancel ongoing authorization (alias for unlink for compatibility).

            Returns:
                {"status": "cancelled"}
            """
            # Отменяем активную сессию авторизации
            if hasattr(self.auth_service, '_yandex_session') and self.auth_service._yandex_session:
                if self.auth_service._yandex_session._session:
                    await self.auth_service._yandex_session._session.close()
                self.auth_service._yandex_session = None
                self.auth_service._auth_method = None
            
            return {"status": "cancelled"}

        async def unlink_account(
            *, body: Optional[Dict[str, Any]] = None, **kwargs
        ) -> Dict[str, Any]:
            """Unlink account and clear session.

            Returns:
                {"status": "unlinked"}
            """
            return await self.auth_service.unlink_account()

        async def get_account_session() -> Dict[str, Any]:
            """Get current account session status.

            Returns:
                {
                    "linked": bool,
                    "quasar_ready": bool,
                    "linked_at": float,
                    "method": str,
                }
            """
            return await self.auth_service.get_account_status()

        # Register services
        await self.runtime.service_registry.register("yandex_device_auth.start", start_device_auth)
        await self.runtime.service_registry.register("yandex_device_auth.status", check_qr_status)
        await self.runtime.service_registry.register("yandex_device_auth.cookies", save_cookies)
        await self.runtime.service_registry.register("yandex_device_auth.get_account_status", get_account_status)
        await self.runtime.service_registry.register("yandex_device_auth.cancel", cancel_auth)
        await self.runtime.service_registry.register("yandex_device_auth.unlink", unlink_account)
        await self.runtime.service_registry.register("yandex_device_auth.get_session", get_account_session)

        # Register HTTP endpoints
        from core.http_registry import HttpEndpoint

        try:
            self.runtime.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/yandex/auth/device/start",
                    service="yandex_device_auth.start",
                    description="Start QR or password authorization",
                )
            )

            self.runtime.http.register(
                HttpEndpoint(
                    method="GET",
                    path="/yandex/auth/device/status",
                    service="yandex_device_auth.status",
                    description="Check QR confirmation status",
                )
            )

            self.runtime.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/yandex/auth/device/cookies",
                    service="yandex_device_auth.cookies",
                    description="Save cookies from manual submission",
                )
            )

            self.runtime.http.register(
                HttpEndpoint(
                    method="GET",
                    path="/yandex/auth/device/session",
                    service="yandex_device_auth.get_session",
                    description="Get account session status",
                )
            )

            self.runtime.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/yandex/auth/device/cancel",
                    service="yandex_device_auth.cancel",
                    description="Cancel ongoing authorization",
                )
            )

            self.runtime.http.register(
                HttpEndpoint(
                    method="POST",
                    path="/yandex/auth/device/unlink",
                    service="yandex_device_auth.unlink",
                    description="Unlink account",
                )
            )
        except Exception:
            pass

    async def on_unload(self) -> None:
        """Cleanup on unload."""
        await super().on_unload()

        if hasattr(self, "auth_service"):
            await self.auth_service.cleanup()

        try:
            await self.runtime.service_registry.unregister("yandex_device_auth.start")
            await self.runtime.service_registry.unregister("yandex_device_auth.status")
            await self.runtime.service_registry.unregister("yandex_device_auth.cookies")
            await self.runtime.service_registry.unregister("yandex_device_auth.get_account_status")
            await self.runtime.service_registry.unregister("yandex_device_auth.cancel")
            await self.runtime.service_registry.unregister("yandex_device_auth.unlink")
            await self.runtime.service_registry.unregister("yandex_device_auth.get_session")
        except Exception:
            pass
