"""
Плагин `oauth_yandex` — минимальная реализация OAuth flow для Яндекса.

Назначение:
- построение URL авторизации (`get_authorize_url`)
- обмен `code` на `access_token`/`refresh_token` (`exchange_code`)
- хранение/получение токенов через `runtime.storage`

Ограничения:
- НЕ управляет устройствами
- НЕ публикует события
- НЕ знает про `devices` или `automation`
- простой и легко удаляемый код

Комментарии на русском языке.
"""
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from plugins.base_plugin import BasePlugin, PluginMetadata


class OAuthYandexPlugin(BasePlugin):
    """Минимальный плагин аутентификации через OAuth Яндекса.

    Сервисы (зарегистрированные при загрузке):
    - `oauth_yandex.get_authorize_url(client_id, redirect_uri, scope=None, state=None)`
      Вернёт URL для перенаправления пользователя на страницу авторизации.
    - `oauth_yandex.exchange_code(code, client_id, client_secret, redirect_uri)`
      Выполнит обмен кода на токены и сохранит их в `runtime.storage`.
    - `oauth_yandex.get_tokens()`
      Вернёт сохранённые токены или None.
    - `oauth_yandex.set_tokens(tokens)`
      Сохранит переданный словарь токенов (удобно для тестов).
    """

    TOKEN_NAMESPACE = "oauth_yandex"
    TOKEN_KEY = "tokens"
    TOKEN_ENDPOINT = "https://oauth.yandex.ru/token"
    AUTHORIZE_ENDPOINT = "https://oauth.yandex.ru/authorize"

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="oauth_yandex",
            version="0.1.0",
            description="OAuth helper для Яндекса: получение и хранение токенов",
            author="Home Console",
        )

    async def on_load(self) -> None:
        """Регистрируем сервисы при загрузке плагина."""
        await super().on_load()

        async def get_authorize_url(client_id: str, redirect_uri: str, scope: Optional[str] = None, state: Optional[str] = None) -> str:
            """Построить URL для перенаправления пользователя на страницу авторизации.

            Простая обёртка над query-параметрами OAuth.
            """
            if not client_id or not redirect_uri:
                raise ValueError("client_id и redirect_uri должны быть указаны")

            params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            }
            if scope:
                params["scope"] = scope
            if state:
                params["state"] = state

            return f"{self.AUTHORIZE_ENDPOINT}?{urlencode(params)}"

        async def set_tokens(tokens: Dict[str, Any]) -> None:
            """Сохранить словарь токенов в runtime.storage."""
            if not isinstance(tokens, dict):
                raise ValueError("tokens должен быть словарём")
            await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, tokens)

        async def get_tokens() -> Optional[Dict[str, Any]]:
            """Получить ранее сохранённые токены, если они есть."""
            return await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)

        async def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> Dict[str, Any]:
            """Обменять `code` на токены через OAuth token endpoint Яндекса.

            Использует `aiohttp` при наличии. Результат сохраняется в `runtime.storage`.
            Для тестов можно вызвать `set_tokens` напрямую.
            """
            if not code:
                raise ValueError("code обязателен")
            if not client_id or not client_secret or not redirect_uri:
                raise ValueError("client_id, client_secret и redirect_uri обязательны")

            # Импорт aiohttp только при выполнении, чтобы не требовать зависимости всегда
            try:
                import aiohttp
            except Exception:
                raise RuntimeError("Для обмена кода требуется aiohttp; установите его или используйте set_tokens для тестов")

            data = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.TOKEN_ENDPOINT, data=data) as resp:
                    text = await resp.text()
                    try:
                        json_data = await resp.json()
                    except Exception:
                        raise RuntimeError(f"Ошибка получения токенов: HTTP {resp.status} — {text}")

            # Ожидаем поля access_token и refresh_token (в зависимости от провайдера)
            await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, json_data)
            return json_data

        # Регистрируем сервисы
        self.runtime.service_registry.register("oauth_yandex.get_authorize_url", get_authorize_url)
        self.runtime.service_registry.register("oauth_yandex.exchange_code", exchange_code)
        self.runtime.service_registry.register("oauth_yandex.get_tokens", get_tokens)
        self.runtime.service_registry.register("oauth_yandex.set_tokens", set_tokens)

    async def on_unload(self) -> None:
        """Удаляем сервисы и очищаем ссылку на runtime при выгрузке."""
        await super().on_unload()
        try:
            self.runtime.service_registry.unregister("oauth_yandex.get_authorize_url")
            self.runtime.service_registry.unregister("oauth_yandex.exchange_code")
            self.runtime.service_registry.unregister("oauth_yandex.get_tokens")
            self.runtime.service_registry.unregister("oauth_yandex.set_tokens")
        except Exception:
            pass

        self.runtime = None
