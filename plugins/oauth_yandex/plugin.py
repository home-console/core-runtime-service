"""
Плагин `oauth_yandex` — self-contained реализация OAuth flow для Яндекса.

Назначение:
- хранение конфигурации OAuth (`configure`)
- построение URL авторизации (`get_authorize_url`)
- обмен `code` на `access_token`/`refresh_token` (`exchange_code`)
- проверка статуса авторизации (`get_status`)
- хранение токенов через `runtime.storage`

Архитектура:
- Вся логика OAuth — в плагине (self-contained)
- UI НЕ передаёт OAuth параметры после вызова `configure`
- UI только отображает статус и инициирует действия
- Конфигурация и токены хранятся в `runtime.storage`

Ограничения:
- НЕ управляет устройствами
- НЕ публикует события
- НЕ знает про `devices` или `automation`

Комментарии на русском языке.
"""
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from core.base_plugin import BasePlugin, PluginMetadata


class OAuthYandexPlugin(BasePlugin):
    """Self-contained плагин аутентификации через OAuth Яндекса.

    Сервисы:
    - `oauth_yandex.configure(client_id, client_secret, redirect_uri, scope?)`
      Сохраняет конфигурацию OAuth в storage.
    - `oauth_yandex.get_status()`
      Возвращает статус: configured, authorized, access_token_valid, etc.
    - `oauth_yandex.get_authorize_url()`
      Вернёт URL авторизации (использует сохранённую конфигурацию).
    - `oauth_yandex.exchange_code(code)`
      Обменяет код на токены (использует сохранённую конфигурацию).
    - `oauth_yandex.get_tokens()`
      Вернёт сохранённые токены (debug).
    - `oauth_yandex.set_tokens(tokens)`
      Сохранит токены (для тестов).
    """

    TOKEN_NAMESPACE = "oauth_yandex"
    CONFIG_KEY = "config"
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
        """Регистрируем сервисы при загрузке плагина.
        
        Важно: UI НЕ должен передавать OAuth параметры после вызова configure.
        Все параметры хранятся в storage и используются автоматически.
        """
        await super().on_load()

        async def configure(client_id: str, client_secret: str, redirect_uri: str, scope: Optional[str] = None) -> Dict[str, Any]:
            """Сохранить конфигурацию OAuth в storage.
            
            После вызова этого сервиса UI НЕ должен передавать параметры
            в get_authorize_url или exchange_code — они используют
            сохранённую конфигурацию автоматически.
            
            Args:
                client_id: OAuth Client ID из Яндекса
                client_secret: OAuth Client Secret из Яндекса
                redirect_uri: URL для редиректа после авторизации
                scope: Опциональный scope (разрешения)
            
            Returns:
                Сохранённая конфигурация
            """
            if not client_id or not client_secret or not redirect_uri:
                raise ValueError("client_id, client_secret и redirect_uri обязательны")
            
            config = {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "scope": scope,
            }
            
            await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.CONFIG_KEY, config)
            # Do not return client_secret in responses — mask it
            safe = dict(config)
            if "client_secret" in safe:
                safe["client_secret"] = "****"
            return safe

        async def get_status() -> Dict[str, Any]:
            """Получить статус OAuth авторизации.
            
            Возвращает полную информацию о состоянии авторизации:
            - configured: есть ли сохранённая конфигурация
            - authorized: есть ли токены
            - access_token_valid: валиден ли access_token (упрощённо)
            - expires_at: когда истекает токен (если есть)
            - needs_user_action: требуется ли действие пользователя
            
            UI использует этот сервис для отображения состояния.
            """
            config = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.CONFIG_KEY)
            tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
            
            configured = config is not None
            authorized = tokens is not None and "access_token" in tokens if tokens else False
            
            # Упрощённая проверка: если есть access_token, считаем валидным
            # В реальной реализации проверяем expires_in и делаем refresh
            access_token_valid = authorized
            
            expires_at = None
            if tokens and "expires_in" in tokens:
                # В реальной реализации вычислить timestamp + expires_in
                expires_at = str(tokens.get("expires_in", "unknown"))
            
            needs_user_action = configured and not authorized
            
            return {
                "configured": configured,
                "authorized": authorized,
                "access_token_valid": access_token_valid,
                "expires_at": expires_at,
                "needs_user_action": needs_user_action,
            }

        async def get_authorize_url() -> str:
            """Построить URL для авторизации пользователя.
            
            Использует сохранённую конфигурацию из storage.
            UI НЕ передаёт параметры — они берутся из конфигурации.
            
            Raises:
                ValueError: если конфигурация не установлена
                ValueError: если уже авторизован
            """
            config = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.CONFIG_KEY)
            if not config:
                raise ValueError("OAuth не настроен. Вызовите oauth_yandex.configure сначала.")
            
            tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
            if tokens and "access_token" in tokens:
                raise ValueError("Уже авторизован. Удалите токены перед повторной авторизацией.")
            
            params = {
                "response_type": "code",
                "client_id": config["client_id"],
                "redirect_uri": config["redirect_uri"],
            }
            
            if config.get("scope"):
                params["scope"] = config["scope"]
            
            return f"{self.AUTHORIZE_ENDPOINT}?{urlencode(params)}"

        async def exchange_code(code: str) -> Dict[str, Any]:
            """Обменять authorization code на токены.
            
            Использует сохранённую конфигурацию из storage.
            UI НЕ передаёт client_id/client_secret/redirect_uri.
            
            Args:
                code: authorization code из redirect URL
            
            Returns:
                Полученные токены (также сохраняются в storage)
            
            Raises:
                ValueError: если конфигурация не установлена
                ValueError: если code не указан
                RuntimeError: если обмен не удался
            """
            if not code:
                raise ValueError("code обязателен")
            
            config = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.CONFIG_KEY)
            if not config:
                raise ValueError("OAuth не настроен. Вызовите oauth_yandex.configure сначала.")
            
            # Импорт aiohttp только при выполнении
            try:
                import aiohttp
            except Exception:
                raise RuntimeError("Для обмена кода требуется aiohttp")
            
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": config["redirect_uri"],
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.TOKEN_ENDPOINT, data=data) as resp:
                    text = await resp.text()
                    try:
                        json_data = await resp.json()
                    except Exception:
                        raise RuntimeError(f"Ошибка получения токенов: HTTP {resp.status} — {text}")

            # Сохраняем токены в storage (single source of truth)
            await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, json_data)

            # Do NOT return raw tokens to caller. Return minimal status only.
            return {"ok": True, "authorized": True, "expires_in": json_data.get("expires_in")}

        async def get_tokens() -> Optional[Dict[str, Any]]:
            """Получить сохранённые токены (internal service).

            Этот сервис предназначен только для внутреннего использования другими
            плагинами через `runtime.service_registry.call("oauth_yandex.get_tokens")`.
            Ни при каких условиях токены не регистрируются как публичный HTTP-эндпоинт.
            """
            return await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)

        async def validate_token(token: Optional[str] = None) -> Dict[str, Any]:
            """Проверить валидность access_token у Яндекса.

            Если `token` не передан, берёт сохранённый в storage.

            Возвращает словарь с полем `valid: bool` и дополнительной информацией.
            """
            # Получить токен из хранилища, если не передан
            if not token:
                tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
                if not tokens or 'access_token' not in tokens:
                    return {'valid': False, 'reason': 'no_token'}
                token = tokens['access_token']

            try:
                import aiohttp
            except Exception:
                return {'valid': False, 'reason': 'aiohttp_missing'}

            url = 'https://login.yandex.ru/info?format=json'
            headers = {'Authorization': f'OAuth {token}'}

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                            except Exception:
                                data = {'raw': text}
                            return {'valid': True, 'status': 200, 'info': data}
                        else:
                            return {'valid': False, 'status': resp.status, 'body': text}
            except Exception as e:
                return {'valid': False, 'reason': 'request_failed', 'error': str(e)}

        async def set_tokens(tokens: Dict[str, Any]) -> None:
            """Сохранить токены (internal/test service)."""
            if not isinstance(tokens, dict):
                raise ValueError("tokens должен быть словарём")
            await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, tokens)

        # Регистрируем сервисы
        await self.runtime.service_registry.register("oauth_yandex.configure", configure)
        await self.runtime.service_registry.register("oauth_yandex.get_status", get_status)
        await self.runtime.service_registry.register("oauth_yandex.get_authorize_url", get_authorize_url)
        await self.runtime.service_registry.register("oauth_yandex.exchange_code", exchange_code)
        await self.runtime.service_registry.register("oauth_yandex.get_tokens", get_tokens)
        await self.runtime.service_registry.register("oauth_yandex.validate_token", validate_token)
        await self.runtime.service_registry.register("oauth_yandex.set_tokens", set_tokens)

        # Регистрируем HTTP-контракты через runtime.http.register()
        # UI НЕ должен передавать OAuth параметры после configure —
        # они берутся из storage автоматически.
        from core.http_registry import HttpEndpoint
        try:
            # POST /oauth/yandex/configure — сохранить конфигурацию OAuth
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/oauth/yandex/configure",
                service="oauth_yandex.configure",
                description="Настроить OAuth параметры (client_id, client_secret, redirect_uri)"
            ))
            # GET /oauth/yandex/status — получить статус авторизации (не возвращает токены)
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/oauth/yandex/status",
                service="oauth_yandex.get_status",
                description="Получить статус OAuth: configured, authorized, access_token_valid"
            ))
            # GET /oauth/yandex/authorize-url — построить URL авторизации
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/oauth/yandex/authorize-url",
                service="oauth_yandex.get_authorize_url",
                description="Получить URL авторизации (использует сохранённую конфигурацию)"
            ))
            # POST /oauth/yandex/exchange-code — обменять код на токены
            # Этот HTTP-эндпоинт сохраняет токены в storage, но не возвращает их клиенту.
            self.runtime.http.register(HttpEndpoint(
                method="POST",
                path="/oauth/yandex/exchange-code",
                service="oauth_yandex.exchange_code",
                description="Обменять code на токены (использует сохранённую конфигурацию)"
            ))
            # GET /oauth/yandex/validate — проверить access_token (optional query param `token`)
            self.runtime.http.register(HttpEndpoint(
                method="GET",
                path="/oauth/yandex/validate",
                service="oauth_yandex.validate_token",
                description="Проверить валидность access_token (если не указан, используется сохранённый)"
            ))
        except Exception:
            # Ошибки регистрации HTTP не должны блокировать загрузку плагина
            pass

    async def on_unload(self) -> None:
        """Удаляем сервисы и очищаем ссылку на runtime при выгрузке."""
        await super().on_unload()
        try:
            await self.runtime.service_registry.unregister("oauth_yandex.configure")
            await self.runtime.service_registry.unregister("oauth_yandex.get_status")
            await self.runtime.service_registry.unregister("oauth_yandex.get_authorize_url")
            await self.runtime.service_registry.unregister("oauth_yandex.exchange_code")
            await self.runtime.service_registry.unregister("oauth_yandex.get_tokens")
            await self.runtime.service_registry.unregister("oauth_yandex.validate_token")
            await self.runtime.service_registry.unregister("oauth_yandex.set_tokens")
        except Exception:
            pass

        self.runtime = None
