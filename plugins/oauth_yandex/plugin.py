"""
Плагин `oauth_yandex` — self-contained реализация OAuth flow для Яндекса.

Назначение:
- хранение конфигурации OAuth (`configure`)
- построение URL авторизации (`get_authorize_url`)
- обмен `code` на `access_token`/`refresh_token` (`exchange_code`)
- проверка статуса авторизации (`get_status`)
- автоматическое обновление токенов через refresh (`get_access_token`)
- хранение токенов через `runtime.storage`

Архитектура:
- Вся логика OAuth — в плагине (self-contained)
- UI НЕ передаёт OAuth параметры после вызова `configure`
- UI только отображает статус и инициирует действия
- Конфигурация и токены хранятся в `runtime.storage`
- Автоматический refresh токенов прозрачен для потребителей

Ограничения:
- НЕ управляет устройствами
- НЕ публикует события
- НЕ знает про `devices` или `automation`

Комментарии на русском языке.
"""
import asyncio
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import aiohttp

from core.base_plugin import BasePlugin, PluginMetadata


class OAuthReauthRequired(Exception):
    """Исключение, указывающее что требуется повторная авторизация."""
    pass


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

    async def _get_http_session(self):
        """Получить HTTP session (обёрнутый для логирования, если доступен)."""
        try:
            if await self.runtime.service_registry.has_service("request_logger.create_http_session"):
                return await self.runtime.service_registry.call(
                    "request_logger.create_http_session",
                    source=self.metadata.name
                )
        except Exception:
            pass
        # Fallback на обычный session
        import aiohttp
        return aiohttp.ClientSession()

    async def on_load(self) -> None:
        """Регистрируем сервисы при загрузке плагина.
        
        Важно: UI НЕ должен передавать OAuth параметры после вызова configure.
        Все параметры хранятся в storage и используются автоматически.
        """
        await super().on_load()
        
        # Блокировка для предотвращения параллельных refresh-запросов
        self._refresh_lock = asyncio.Lock()

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
            - access_token_valid: валиден ли access_token (проверяется через expires_at)
            - expires_at: когда истекает токен (timestamp, если есть)
            - needs_user_action: требуется ли действие пользователя
            
            UI использует этот сервис для отображения состояния.
            """
            config = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.CONFIG_KEY)
            tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
            
            configured = config is not None
            authorized = tokens is not None and "access_token" in tokens if tokens else False
            
            # Проверяем валидность через expires_at
            access_token_valid = False
            expires_at = None
            
            if authorized and tokens and isinstance(tokens, dict):
                expires_at = tokens.get("expires_at")
                if expires_at is not None:
                    if isinstance(expires_at, (int, float)):
                        now = time.time()
                        # Токен валиден если expires_at > now + 30 секунд (запас)
                        access_token_valid = expires_at > (now + 30)
                        expires_at = float(expires_at)  # Нормализуем до float
                    else:
                        # Если expires_at не число, считаем токен валидным (старая схема)
                        access_token_valid = True
                else:
                    # Если expires_at нет, считаем токен валидным (старая схема)
                    access_token_valid = True
            
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
            from core.utils.operation import operation
            
            async with operation("oauth.exchange_code", self.metadata.name, self.runtime):
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
                
                # Логируем запрос на обмен кода
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="info",
                    message=f"OAuth exchange_code request: POST {self.TOKEN_ENDPOINT}",
                    plugin=self.metadata.name,
                    context={"endpoint": self.TOKEN_ENDPOINT, "grant_type": "authorization_code"}
                )
                
                session = await self._get_http_session()
                async with session:
                    async with await session.post(self.TOKEN_ENDPOINT, data=data) as resp:
                        text = await resp.text()
                        # Логируем ответ
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="info" if resp.status == 200 else "error",
                            message=f"OAuth exchange_code response: POST {self.TOKEN_ENDPOINT} -> HTTP {resp.status}",
                            plugin=self.metadata.name,
                            context={"status_code": resp.status, "response_preview": text[:200]}
                        )
                        try:
                            json_data = await resp.json()
                        except Exception:
                            await self.runtime.service_registry.call(
                                "logger.log",
                                level="error",
                                message=f"OAuth exchange_code failed to parse JSON: {text[:200]}",
                                plugin=self.metadata.name,
                                context={"status_code": resp.status}
                            )
                            raise RuntimeError(f"Ошибка получения токенов: HTTP {resp.status} — {text}")

                # Вычисляем expires_at на основе expires_in
                tokens_to_save = dict(json_data)
                if "expires_in" in json_data:
                    expires_in = json_data.get("expires_in")
                    if isinstance(expires_in, (int, float)) and expires_in > 0:
                        tokens_to_save["expires_at"] = time.time() + expires_in
                    elif isinstance(expires_in, str):
                        try:
                            expires_in_int = int(expires_in)
                            if expires_in_int > 0:
                                tokens_to_save["expires_at"] = time.time() + expires_in_int
                        except (ValueError, TypeError):
                            pass

                # Сохраняем токены в storage (single source of truth)
                await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, tokens_to_save)

                # Do NOT return raw tokens to caller. Return minimal status only.
                return {"ok": True, "authorized": True, "expires_in": json_data.get("expires_in")}

        async def _refresh_access_token() -> str:
            """Внутренний метод для обновления access_token через refresh_token.
            
            IMPORTANT:
            OAuthReauthRequired MUST be raised ONLY when user re-authorization is required:
            - invalid_grant (refresh_token revoked/expired/invalid)
            - 200 response but no access_token
            
            Temporary errors (429, 5xx, network, parse) are re-raised without token deletion.
            
            Returns:
                Новый access_token
                
            Raises:
                OAuthReauthRequired: if refresh_token invalid or response format broken (FATAL)
                aiohttp.ClientError: network errors (TEMPORARY)
                asyncio.TimeoutError: timeout (TEMPORARY)
                RuntimeError: for 429, 5xx, parse errors (TEMPORARY)
            """
            config = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.CONFIG_KEY)
            if not config:
                raise OAuthReauthRequired("OAuth не настроен")
            
            tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
            if not tokens or not isinstance(tokens, dict):
                raise OAuthReauthRequired("Токены не найдены")
            
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                raise OAuthReauthRequired("Refresh token отсутствует")
            
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            }
            
            session = await self._get_http_session()
            try:
                async with session:
                    async with await session.post(self.TOKEN_ENDPOINT, data=data) as resp:
                        text = await resp.text()
                        
                        if resp.status != 200:
                            # IMPORTANT: Distinguish FATAL (invalid_grant) from TEMPORARY (429, 5xx, network).
                            # Only clear tokens and raise OAuthReauthRequired for FATAL cases.
                            # Temporary errors must NOT trigger re-auth flow.
                            should_clear_tokens = False
                            is_fatal = False
                            
                            # Check for FATAL: invalid_grant or other permanent OAuth errors
                            if resp.status in (400, 401):
                                try:
                                    error_data = await resp.json()
                                    error_type = error_data.get("error", "")
                                    # invalid_grant means refresh_token is revoked/expired/invalid → FATAL
                                    if error_type == "invalid_grant":
                                        should_clear_tokens = True
                                        is_fatal = True
                                except Exception:
                                    # If we can't parse, assume 401 means invalid token → FATAL
                                    if resp.status == 401:
                                        should_clear_tokens = True
                                        is_fatal = True
                            
                            # If FATAL: clear tokens and raise OAuthReauthRequired
                            if is_fatal:
                                if should_clear_tokens:
                                    await self.runtime.storage.delete(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
                                raise OAuthReauthRequired(f"Ошибка обновления токена: HTTP {resp.status} (invalid_grant)")
                            
                            # If TEMPORARY (429, 5xx, etc): DO NOT clear tokens, raise RuntimeError
                            raise RuntimeError(f"Временная ошибка refresh: HTTP {resp.status}")
                        
                        try:
                            json_data = await resp.json()
                        except Exception:
                            # Parse error with 200 OK - TEMPORARY, not FATAL
                            # DO NOT clear tokens, DO NOT raise OAuthReauthRequired
                            raise RuntimeError(f"Ошибка парсинга ответа OAuth: {text[:200]}")
                        
                        # Вычисляем expires_at
                        tokens_to_save = dict(json_data)
                        if "expires_in" in json_data:
                            expires_in = json_data.get("expires_in")
                            if isinstance(expires_in, (int, float)) and expires_in > 0:
                                tokens_to_save["expires_at"] = time.time() + expires_in
                            elif isinstance(expires_in, str):
                                try:
                                    expires_in_int = int(expires_in)
                                    if expires_in_int > 0:
                                        tokens_to_save["expires_at"] = time.time() + expires_in_int
                                except (ValueError, TypeError):
                                    pass
                        
                        # Если refresh_token не вернулся в ответе, сохраняем старый
                        if "refresh_token" not in tokens_to_save and refresh_token:
                            tokens_to_save["refresh_token"] = refresh_token
                        
                        # Сохраняем обновленные токены
                        await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, tokens_to_save)
                        
                        access_token = tokens_to_save.get("access_token")
                        if not access_token:
                            # Response was 200 but no access_token - FATAL (server returned broken response)
                            # Clear tokens and raise OAuthReauthRequired
                            await self.runtime.storage.delete(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
                            raise OAuthReauthRequired("Access token не получен после refresh (FATAL)")
                        
                        return access_token
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # Network errors - TEMPORARY, DO NOT clear tokens, DO NOT convert to OAuthReauthRequired
                # Re-raise as-is for caller to handle
                raise
            except OAuthReauthRequired:
                # FATAL: tokens already cleared if needed, re-raise for caller
                raise
            except RuntimeError:
                # TEMPORARY: parse errors, 429, 5xx, etc - DO NOT clear tokens, re-raise as-is
                raise
            except Exception as e:
                # Unexpected errors - assume TEMPORARY, DO NOT clear tokens, DO NOT raise OAuthReauthRequired
                raise RuntimeError(f"Ошибка обновления токена (temporary): {str(e)}")

        async def get_access_token() -> str:
            """Получить валидный access_token с автоматическим обновлением.
            
            IMPORTANT:
            OAuthReauthRequired is raised ONLY when user re-authorization is truly required.
            Temporary errors (network, 429, 5xx, parse) do NOT trigger re-auth flow.
            
            Поведение:
            - Загружает токены из storage
            - Проверяет валидность (expires_at)
            - Если токен валиден → возвращает его
            - Если токен истёк → пытается refresh (с блокировкой для параллельных запросов)
            - Если refresh успешен → возвращает новый токен
            - Если refresh выбрасывает OAuthReauthRequired (FATAL) → пробрасывает дальше
            - Если refresh выбрасывает другую ошибку (TEMPORARY) → пробрасывает как есть
            
            Returns:
                Валидный access_token
                
            Raises:
                OAuthReauthRequired: если требуется повторная авторизация (FATAL)
                RuntimeError: для временных ошибок (TEMPORARY)
            """
            tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
            if not tokens or not isinstance(tokens, dict):
                # Если токены невалидны (например, невалидный JSON в storage),
                # пытаемся очистить их явно
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message="Токены не найдены в storage или невалидны - требуется повторная авторизация",
                    plugin=self.metadata.name,
                    context={"tokens": str(tokens)[:100] if tokens else "None", "tokens_type": type(tokens).__name__}
                )
                try:
                    await self.runtime.storage.delete(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
                except Exception:
                    pass  # Игнорируем ошибки при очистке
                raise OAuthReauthRequired("Токены не найдены или невалидны. Требуется повторная авторизация.")
            
            access_token = tokens.get("access_token")
            if not access_token:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message="Access token отсутствует в сохранённых токенах - требуется повторная авторизация",
                    plugin=self.metadata.name,
                    context={"has_tokens": True, "token_keys": list(tokens.keys()) if tokens else []}
                )
                raise OAuthReauthRequired("Access token отсутствует. Требуется повторная авторизация.")
            
            # Проверяем истечение токена
            expires_at = tokens.get("expires_at")
            now = time.time()
            
            # Если expires_at не установлен, считаем токен валидным (старая схема)
            # Используем запас 60 секунд для предсказуемости
            if expires_at is not None:
                if isinstance(expires_at, (int, float)):
                    # Токен валиден если expires_at > now + 60 секунд
                    if expires_at > (now + 60):
                        # Токен валиден - возвращаем его
                        return access_token
                    # Токен истёк или истекает в ближайшие 60 секунд - нужен refresh
                    # Используем блокировку для предотвращения параллельных refresh
                    async with self._refresh_lock:
                        # ВСЕГДА читаем токен из storage заново после получения блокировки
                        # (возможно, другой запрос уже обновил токен)
                        tokens = await self.runtime.storage.get(self.TOKEN_NAMESPACE, self.TOKEN_KEY)
                        if not tokens or not isinstance(tokens, dict):
                            # Если токены отсутствуют после получения блокировки,
                            # это означает что другой запрос попытался сделать refresh и не удался
                            # (токены были удалены). Не пытаемся делать refresh снова.
                            raise OAuthReauthRequired("Токены не найдены или невалидны. Требуется повторная авторизация.")
                        
                        new_access_token = tokens.get("access_token")
                        if not new_access_token:
                            raise OAuthReauthRequired("Access token отсутствует. Требуется повторная авторизация.")
                        
                        new_expires_at = tokens.get("expires_at")
                        # Пересчитываем now после получения блокировки (могло пройти время)
                        now_after_lock = time.time()
                        
                        # Если токен уже обновлен другим запросом, используем его
                        if new_expires_at:
                            if isinstance(new_expires_at, (int, float)):
                                # Проверяем, что новый токен валиден (не истекает в ближайшие 60 секунд)
                                if new_expires_at > (now_after_lock + 60):
                                    return new_access_token
                                # Если новый токен тоже истек, продолжаем обновление
                        
                        # Пытаемся обновить (только если токен не был обновлен другим запросом)
                        from core.utils.operation import operation
                        try:
                            async with operation("oauth.refresh_token", self.metadata.name, self.runtime):
                                new_token = await _refresh_access_token()
                            return new_token
                        except OAuthReauthRequired:
                            # FATAL: refresh_token invalid or 200 without access_token
                            # Tokens already deleted, raise for user to re-authorize
                            raise
                        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
                            # TEMPORARY: network, timeout, 429, 5xx, parse errors
                            # Do NOT clear tokens, do NOT raise OAuthReauthRequired
                            # Retry once for network errors only
                            if isinstance(e, (aiohttp.ClientError, asyncio.TimeoutError)):
                                try:
                                    async with operation("oauth.refresh_token", self.metadata.name, self.runtime):
                                        new_token = await _refresh_access_token()
                                    return new_token
                                except OAuthReauthRequired:
                                    # FATAL on retry
                                    raise
                                except Exception as retry_error:
                                    # TEMPORARY on retry - still don't raise OAuthReauthRequired
                                    raise RuntimeError(
                                        f"Не удалось обновить токен после retry (temporary): {str(retry_error)}"
                                    )
                            # Non-network temporary errors: don't retry, just propagate
                            raise
                        except Exception as e:
                            # Unexpected errors - propagate as-is, don't convert to OAuthReauthRequired
                            raise RuntimeError(f"Неожиданная ошибка при refresh: {str(e)}")
            
            # Токен валиден (expires_at проверен или отсутствует) - логируем для отладки
            await self.runtime.service_registry.call(
                "logger.log",
                level="debug",
                message=f"Access token валиден, expires_at={expires_at}, осталось {expires_at - now:.0f} секунд" if expires_at else "Access token валиден (expires_at не установлен)",
                plugin=self.metadata.name,
                context={"expires_at": expires_at, "now": now, "remaining_seconds": expires_at - now if expires_at else None}
            )
            return access_token

        async def get_tokens() -> Optional[Dict[str, Any]]:
            """Получить сохранённые токены (internal service, deprecated).

            Этот сервис предназначен только для внутреннего использования другими
            плагинами через `runtime.service_registry.call("oauth_yandex.get_tokens")`.
            Ни при каких условиях токены не регистрируются как публичный HTTP-эндпоинт.
            
            ВАЖНО: Для получения валидного access_token используйте get_access_token().
            Этот метод оставлен для обратной совместимости.
            """
            # Для обратной совместимости возвращаем токены как есть
            # Но рекомендуется использовать get_access_token()
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

            # Логируем запрос на валидацию токена
            await self.runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"OAuth validate_token request: GET {url}",
                plugin=self.metadata.name,
                context={"url": url}
            )

            try:
                session = await self._get_http_session()
                async with session:
                    async with await session.get(url, headers=headers) as resp:
                        text = await resp.text()
                        # Логируем ответ
                        await self.runtime.service_registry.call(
                            "logger.log",
                            level="info" if resp.status == 200 else "warning",
                            message=f"OAuth validate_token response: GET {url} -> HTTP {resp.status}",
                            plugin=self.metadata.name,
                            context={"status_code": resp.status, "response_preview": text[:200]}
                        )
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                            except Exception:
                                data = {'raw': text}
                            return {'valid': True, 'status': 200, 'info': data}
                        else:
                            await self.runtime.service_registry.call(
                                "logger.log",
                                level="warning",
                                message=f"OAuth validate_token failed: HTTP {resp.status}, body: {text[:200]}",
                                plugin=self.metadata.name,
                                context={"status_code": resp.status}
                            )
                            return {'valid': False, 'status': resp.status, 'body': text}
            except Exception as e:
                await self.runtime.service_registry.call(
                    "logger.log",
                    level="error",
                    message=f"OAuth validate_token exception: {type(e).__name__}: {str(e)}",
                    plugin=self.metadata.name,
                    context={"error": str(e), "error_type": type(e).__name__}
                )
                return {'valid': False, 'reason': 'request_failed', 'error': str(e)}

        async def set_tokens(tokens: Dict[str, Any]) -> None:
            """Сохранить токены (internal/test service).
            
            Автоматически вычисляет expires_at если есть expires_in и нет expires_at.
            """
            if not isinstance(tokens, dict):
                raise ValueError("tokens должен быть словарём")
            
            # Вычисляем expires_at если есть expires_in и нет expires_at
            tokens_to_save = dict(tokens)
            if "expires_at" not in tokens_to_save and "expires_in" in tokens_to_save:
                expires_in = tokens_to_save.get("expires_in")
                if isinstance(expires_in, (int, float)) and expires_in > 0:
                    tokens_to_save["expires_at"] = time.time() + expires_in
                elif isinstance(expires_in, str):
                    try:
                        expires_in_int = int(expires_in)
                        if expires_in_int > 0:
                            tokens_to_save["expires_at"] = time.time() + expires_in_int
                    except (ValueError, TypeError):
                        pass
            
            await self.runtime.storage.set(self.TOKEN_NAMESPACE, self.TOKEN_KEY, tokens_to_save)

        # Регистрируем сервисы
        await self.runtime.service_registry.register("oauth_yandex.configure", configure)
        await self.runtime.service_registry.register("oauth_yandex.get_status", get_status)
        await self.runtime.service_registry.register("oauth_yandex.get_authorize_url", get_authorize_url)
        await self.runtime.service_registry.register("oauth_yandex.exchange_code", exchange_code)
        await self.runtime.service_registry.register("oauth_yandex.get_access_token", get_access_token)
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
            await self.runtime.service_registry.unregister("oauth_yandex.get_access_token")
            await self.runtime.service_registry.unregister("oauth_yandex.get_tokens")
            await self.runtime.service_registry.unregister("oauth_yandex.validate_token")
            await self.runtime.service_registry.unregister("oauth_yandex.set_tokens")
        except Exception:
            pass

        self.runtime = None
