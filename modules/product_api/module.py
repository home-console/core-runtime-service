"""
ProductApiModule — BFF (Backend for Frontend) для пользовательских клиентов.

- Product API НЕ использует Inspector.
- Product API МОЖЕТ вызывать service_registry.call() и агрегировать данные из доменных сервисов.
- Product API НЕ регистрирует operations handlers.
- Product API = для пользователей (User UI / Mobile / Mini-app).
- Inspector = для админов/дебага.

Ручки вида /api/v1/devices делегируют в доменные сервисы devices.list, devices.get.
Креды пользователя: /api/v1/user/credentials — credential.* с _user_id из контекста запроса.
"""

from typing import Any

from core.http_registry import EndpointAuthConfig, HttpEndpoint
from core.runtime_module import RuntimeModule
from core.http import HttpEndpoint, EndpointAuthConfig


def _user_cred_params(kw: dict) -> dict:
    """Извлечь _user_id и _user_roles для credential.* (инжектятся адаптером user_credentials)."""
    return {
        "_user_id": kw.get("_user_id"),
        "_user_roles": kw.get("_user_roles", []),
    }


class ProductApiModule(RuntimeModule):
    """
    Модуль Product API (BFF).
    Регистрирует HTTP endpoints /api/v1/* и сервисы product_api.v1.*,
    которые вызывают доменные сервисы (devices.list, devices.get и т.д.).
    """

    @property
    def name(self) -> str:
        return "product_api"

    async def register(self) -> None:
        async def _devices_list(**kwargs: Any) -> Any:
            """BFF: GET /api/v1/devices → devices.list()."""
            return await self.context.services.call("devices.list")

        async def _devices_get(id: str, **kwargs: Any) -> Any:
            """BFF: GET /api/v1/devices/{id} → devices.get(id)."""
            return await self.context.services.call("devices.get", id)

        async def _devices_set_state(id: str, body: Any = None, **kwargs: Any) -> Any:
            """BFF: POST /api/v1/devices/{id}/state → devices.set_state(id, state)."""
            state = body if isinstance(body, dict) else {}
            if (
                isinstance(body, dict)
                and "state" in body
                and isinstance(body["state"], dict)
            ):
                state = body["state"]
            return await self.context.services.call("devices.set_state", id, state)

        async def _devices_get_external(id: str, **kwargs: Any) -> Any:
            """BFF: GET /api/v1/devices/{id}/external → devices.get(id) затем devices.get_external_for_device(id)."""
            await self.context.services.call(
                "devices.get", id
            )  # проверка доступа (ACL)
            return await self.context.services.call(
                "devices.get_external_for_device", id
            )

        await self.context.services.register(
            "product_api.v1.devices.list", _devices_list
        )
        await self.context.services.register("product_api.v1.devices.get", _devices_get)
        await self.context.services.register(
            "product_api.v1.devices.set_state", _devices_set_state
        )
        await self.context.services.register(
            "product_api.v1.devices.get_external", _devices_get_external
        )

        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/devices",
                service="product_api.v1.devices.list",
                description="Product API: list devices (BFF → devices.list)",
            )
        )
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/devices/{id}",
                service="product_api.v1.devices.get",
                description="Product API: get device by id (BFF → devices.get)",
            )
        )
        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/devices/{id}/state",
                service="product_api.v1.devices.set_state",
                description="Product API: set device state (BFF → devices.set_state)",
            )
        )
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/devices/{id}/external",
                service="product_api.v1.devices.get_external",
                description="Product API: get external device payload for an internal device (BFF → devices.get_external_for_device)",
            )
        )

        # User credentials (свои креды у каждого пользователя)
        runtime = self.runtime
        services = self.context.services

        async def user_credentials_list(**kw: Any) -> Any:
            """
            GET /api/v1/user/credentials → credential.list (user-scoped).

            Если модуль credentials не загружен, не роняем Product API, а
            возвращаем пустой список с поясняющим сообщением.
            """
            from modules.admin.credentials_handlers import _service_not_loaded

            try:
                return await runtime.service_registry.call(
                    "credential.list",
                    **_user_cred_params(kw),
                )
            except Exception as e:
                # Если это не «модуль не загружен» — пробрасываем дальше
                if not _service_not_loaded(e):
                    raise

                # Модуль credentials отсутствует — мягкий fallback
                return {
                    "credentials": [],
                    "count": 0,
                    "_message": "Credentials module is not loaded on core-runtime-service; user credentials are disabled in this environment.",
                }

        async def user_credentials_create(**kw: Any) -> Any:
            from modules.admin.credentials_handlers import _service_not_loaded

            body = kw.get("body") or {}
            cred = dict(body.get("credential", body))
            secret_str = body.get("secret") or cred.get("secret")
            if not secret_str:
                raise ValueError("secret required")
            cred.pop("secret", None)
            if not cred.get("secret_ref") and (
                cred.get("host") and cred.get("username")
            ):
                cred["secret_ref"] = f"ssh:{cred['host']}:{cred['username']}"
            elif not cred.get("secret_ref"):
                cred["secret_ref"] = f"cred:{cred.get('name', '').replace(' ', '_')}"
            secret_bytes = (
                secret_str.encode("utf-8")
                if isinstance(secret_str, str)
                else secret_str
            )

            try:
                return await runtime.service_registry.call(
                    "credential.create",
                    credential=cred,
                    secret=secret_bytes,
                    **_user_cred_params(kw),
                )
            except Exception as e:
                # Если модуль credentials не загружен — даём понятное сообщение, а не "service not found".
                if not _service_not_loaded(e):
                    raise
                raise RuntimeError(
                    "Credentials module is not loaded on core-runtime-service; "
                    "user credentials are disabled in this environment.",
                ) from e

        async def user_credentials_get(**kw: Any) -> Any:
            return await runtime.service_registry.call(
                "credential.get",
                credential_id=kw.get("credential_id"),
                **_user_cred_params(kw),
            )

        async def user_credentials_get_secret(**kw: Any) -> Any:
            out = await runtime.service_registry.call(
                "credential.get_with_secret",
                credential_id=kw.get("credential_id"),
                **_user_cred_params(kw),
            )
            if not out or not isinstance(out, dict):
                raise ValueError("credential not found")
            hex_secret = out.get("secret") or ""
            secret_bytes = (
                bytes.fromhex(hex_secret) if isinstance(hex_secret, str) else hex_secret
            )
            secret_str = secret_bytes.decode("utf-8", errors="replace")
            return {"secret": secret_str}

        async def user_credentials_update(**kw: Any) -> Any:
            body = kw.get("body") or {}
            cred = dict(body.get("credential", body))
            cred["id"] = kw.get("credential_id")
            secret_str = body.get("secret") or cred.get("secret")
            cred.pop("secret", None)
            secret_bytes = (
                secret_str.encode("utf-8")
                if secret_str and isinstance(secret_str, str)
                else None
            )
            return await runtime.service_registry.call(
                "credential.update",
                credential=cred,
                secret=secret_bytes,
                **_user_cred_params(kw),
            )

        async def user_credentials_delete(**kw: Any) -> Any:
            await runtime.service_registry.call(
                "credential.delete",
                credential_id=kw.get("credential_id"),
                **_user_cred_params(kw),
            )
            return {"deleted": True}

        async def user_credentials_connect(**kw: Any) -> Any:
            from modules.admin.credentials_handlers import _ssh_connect_with_credential
            from modules.credentials import CredentialType

            out = await runtime.service_registry.call(
                "credential.get_with_secret",
                credential_id=kw.get("credential_id"),
                **_user_cred_params(kw),
            )
            if not out or not isinstance(out, dict):
                raise ValueError("credential not found")
            meta = out.get("metadata") or {}
            hex_secret = out.get("secret") or ""
            secret_bytes = (
                bytes.fromhex(hex_secret) if isinstance(hex_secret, str) else hex_secret
            )

            # Минимальный объект с .type, .host, .username, .port для _ssh_connect_with_credential
            class _CredForSsh:
                pass

            c = _CredForSsh()
            c.type = CredentialType(meta.get("type", "ssh_password"))
            c.host = meta.get("host")
            c.username = meta.get("username")
            c.port = meta.get("port")
            return _ssh_connect_with_credential(c, secret_bytes)

        auth_user_creds = EndpointAuthConfig(resource_adapter="user_credentials")

        await services.register("user.v1.credentials.list", user_credentials_list)
        await services.register("user.v1.credentials.create", user_credentials_create)
        await services.register("user.v1.credentials.get", user_credentials_get)
        await services.register(
            "user.v1.credentials.get_secret", user_credentials_get_secret
        )
        await services.register("user.v1.credentials.update", user_credentials_update)
        await services.register("user.v1.credentials.delete", user_credentials_delete)
        await services.register("user.v1.credentials.connect", user_credentials_connect)

        for method, path, svc, desc in [
            (
                "GET",
                "/api/v1/user/credentials",
                "user.v1.credentials.list",
                "User: list my credentials",
            ),
            (
                "POST",
                "/api/v1/user/credentials",
                "user.v1.credentials.create",
                "User: create credential",
            ),
            (
                "GET",
                "/api/v1/user/credentials/{credential_id}",
                "user.v1.credentials.get",
                "User: get credential",
            ),
            (
                "GET",
                "/api/v1/user/credentials/{credential_id}/secret",
                "user.v1.credentials.get_secret",
                "User: get credential secret",
            ),
            (
                "PUT",
                "/api/v1/user/credentials/{credential_id}",
                "user.v1.credentials.update",
                "User: update credential",
            ),
            (
                "DELETE",
                "/api/v1/user/credentials/{credential_id}",
                "user.v1.credentials.delete",
                "User: delete credential",
            ),
            (
                "POST",
                "/api/v1/user/credentials/{credential_id}/connect",
                "user.v1.credentials.connect",
                "User: SSH connect by credential",
            ),
        ]:
            self.context.http.register(
                HttpEndpoint(
                    method=method,
                    path=path,
                    service=svc,
                    description=desc,
                    auth_config=auth_user_creds,
                )
            )

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for name in (
            "product_api.v1.devices.list",
            "product_api.v1.devices.get",
            "product_api.v1.devices.set_state",
            "product_api.v1.devices.get_external",
            "user.v1.credentials.list",
            "user.v1.credentials.create",
            "user.v1.credentials.get",
            "user.v1.credentials.get_secret",
            "user.v1.credentials.update",
            "user.v1.credentials.delete",
            "user.v1.credentials.connect",
        ):
            try:
                await self.context.services.unregister(name)
            except Exception:
                pass
