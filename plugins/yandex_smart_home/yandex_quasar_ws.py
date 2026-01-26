"""
Realtime клиент WebSocket Quasar для Яндекс Умного дома.

⚠️ КРИТИЧЕСКИ ВАЖНО — АРХИТЕКТУРНОЕ ПРАВИЛО:

Quasar API (iot.quasar.yandex.ru) — это ВНУТРЕННИЙ reverse-engineered API Яндекса.

❌ НЕ использует OAuth Bearer token
❌ НЕ принимает Authorization: Bearer заголовки
❌ НЕ работает с публичным OAuth API

✅ Работает ИСКЛЮЧИТЕЛЬНО через cookies сессии Яндекса:
   - Session_id (обязательно)
   - yandexuid (обязательно)
   - sessionid2 (желательно)
   
Cookies берутся из активной браузерной сессии яндекса (https://yandex.ru).
Попытка использовать OAuth token приведёт к HTTP 401 Unauthorized.

Это аналогично тому, как работает мобильное приложение Яндекс —
оно НЕ использует OAuth, а авторизуется через cookies.

Установка cookies:
  python3 dev-scripts/set_yandex_cookies.py
или через API:
  POST /oauth/yandex/cookies

См. plugins/yandex_smart_home/QUASAR_WEBSOCKET.md для деталей.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set
import asyncio
import contextlib
import inspect
import json
import random
from urllib.parse import urlparse

import aiohttp
from aiohttp import ServerTimeoutError
from yarl import URL

from .api_client import YandexAPIClient
from .device_transformer import DeviceTransformer


class YandexQuasarWS:
    """
    WebSocket клиент для Quasar API (iot.quasar.yandex.ru).
    
    ⚠️ ВАЖНО: Использует ТОЛЬКО cookies, НЕ OAuth token!
    
    Quasar — внутренний API Яндекса, который работает как мобильное приложение:
    авторизация через cookies сессии, а не через OAuth Bearer token.
    
    Требуемые cookies:
    - Session_id (обязательно)
    - yandexuid (обязательно)  
    - sessionid2 (желательно)
    
    Cookies загружаются через:
    - oauth_yandex.get_cookies() service
    - или storage: namespace="yandex", key="cookies"
    """

    def __init__(self, runtime: Any, plugin_name: str):
        self.runtime = runtime
        self.plugin_name = plugin_name
        self.api_client = YandexAPIClient(runtime, plugin_name)
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._runner: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._subscribers: Dict[str, Set[Callable[[Dict[str, Any]], Any]]] = {}
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._cookie_jar: Optional[aiohttp.CookieJar] = None
        self._current_cookies: Optional[Dict[str, str]] = None

    @property
    def runner(self) -> Optional[asyncio.Task]:
        return self._runner

    async def start(self) -> None:
        if self._runner and not self._runner.done():
            return
        self._stop_event.clear()
        self._runner = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._runner:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._session:
            with contextlib.suppress(Exception):
                await self._session.close()
            self._session = None

    def subscribe(self, device_id: str, callback: Callable[[Dict[str, Any]], Any]) -> Callable[[], None]:
        """Подписка на обновления конкретного устройства."""
        self._subscribers.setdefault(device_id, set()).add(callback)

        def unsubscribe() -> None:
            self._subscribers.get(device_id, set()).discard(callback)

        return unsubscribe

    async def _run_loop(self) -> None:
        backoff = 1.0
        consecutive_errors = 0
        max_consecutive_errors = 10  # Максимум ошибок подряд перед остановкой
        
        while not self._stop_event.is_set():
            try:
                cookies = await self._load_cookies()
                if not cookies:
                    await self._log(
                        "error",
                        "Quasar WS: cookies required but not found. Quasar API requires Yandex session cookies (Session_id, yandexuid). Use yandex.set_cookies service or configure oauth_yandex plugin to provide cookies."
                    )
                    # Ждём и пытаемся снова — возможно куки появятся
                    await asyncio.sleep(30)
                    continue
                
                # Валидация обязательных cookies
                required = ["Session_id", "yandexuid"]
                missing = [k for k in required if k not in cookies]
                if missing:
                    await self._log(
                        "error",
                        f"Quasar WS: missing required cookies: {missing}. Have: {list(cookies.keys())}",
                        missing_cookies=missing,
                        available_cookies=list(cookies.keys())
                    )
                    await asyncio.sleep(30)
                    continue
                
                await self._log(
                    "info",
                    f"Quasar WS: using cookies for auth (NO OAuth token)",
                    cookie_count=len(cookies),
                    cookie_names=list(cookies.keys()),
                    has_session_id="Session_id" in cookies,
                    has_yandexuid="yandexuid" in cookies
                )
                
                devices, updates_url = await self._fetch_devices_and_url(cookies)
                await self._seed_and_publish(devices)
                backoff = 1.0
                consecutive_errors = 0  # Сбрасываем счетчик при успешном подключении
                await self._consume_ws(updates_url, cookies)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Специальная обработка таймаута ожидания PONG от сервера
                # Это нормальное поведение - сервер Quasar может не отвечать на PING
                if isinstance(e, ServerTimeoutError) or e.__class__.__name__ == "ServerTimeoutError" or "No PONG received" in str(e):
                    await self._log(
                        "debug",
                        f"Quasar WS heartbeat timeout (server may not respond to PING, reconnecting): {e}",
                        error_type=type(e).__name__,
                        error_msg=str(e),
                    )
                    # Небольшая пауза перед повторным подключением — не увеличиваем счетчик consecutive_errors
                    # Это не критическая ошибка, просто переподключаемся
                    await asyncio.sleep(2 + random.random())
                    backoff = 1.0
                    continue

                consecutive_errors += 1
                await self._log(
                    "error",
                    f"Quasar WS loop error: {type(e).__name__}: {e}",
                    error_type=type(e).__name__,
                    error_msg=str(e),
                    backoff=round(backoff, 2),
                    consecutive_errors=consecutive_errors,
                )

                # Если слишком много ошибок подряд - останавливаем попытки
                if consecutive_errors >= max_consecutive_errors:
                    await self._log(
                        "error",
                        f"Quasar WS: too many consecutive errors ({consecutive_errors}), stopping reconnection attempts. Fix the issue and restart the plugin.",
                        consecutive_errors=consecutive_errors,
                    )
                    break  # Выходим из цикла

                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 2, 30.0)

    async def _fetch_devices_and_url(self, cookies: Dict[str, str]) -> tuple[List[Dict[str, Any]], str]:
        """
        Fetch devices list from Quasar API using cookies (NO OAuth token).
        
        ⚠️ ARCHITECTURAL RULE: NEVER add Authorization header here!
        Quasar API rejects OAuth Bearer tokens with HTTP 401.
        """
        url = "https://iot.quasar.yandex.ru/m/v3/user/devices"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        # CRITICAL: NO Authorization header! Quasar uses cookies ONLY.
        assert "Authorization" not in headers, "NEVER use OAuth with Quasar API!"
        
        timeout = aiohttp.ClientTimeout(total=15)
        jar = self._cookie_jar_from(cookies)
        async with aiohttp.ClientSession(timeout=timeout, cookie_jar=jar) as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                await self._log(
                    "debug",
                    f"Quasar devices response: HTTP {resp.status}",
                    status=resp.status,
                    response_preview=text[:200] if resp.status != 200 else "OK"
                )
                if resp.status != 200:
                    raise RuntimeError(f"Quasar devices HTTP {resp.status}: {text[:500]}. Hint: Quasar API requires valid Yandex session cookies, not OAuth token.")
                try:
                    data = await resp.json()
                except Exception as parse_err:
                    raise RuntimeError(f"Quasar devices parse error: {parse_err} — {text[:200]}")
        updates_url = data.get("updates_url")
        devices = data.get("devices") or []
        if not updates_url:
            raise RuntimeError("updates_url missing in Quasar response")
        
        # Валидация и нормализация updates_url
        if not isinstance(updates_url, str):
            raise ValueError(f"Invalid updates_url type: {type(updates_url)}, expected str")
        
        # Убеждаемся, что URL начинается с ws:// или wss://
        if not updates_url.startswith(('ws://', 'wss://')):
            # Если URL начинается с http:// или https://, заменяем на ws:// или wss://
            if updates_url.startswith('https://'):
                updates_url = updates_url.replace('https://', 'wss://', 1)
            elif updates_url.startswith('http://'):
                updates_url = updates_url.replace('http://', 'ws://', 1)
            else:
                # Если нет протокола, добавляем wss://
                updates_url = f"wss://{updates_url.lstrip('/')}"
        
        return devices, updates_url

    async def _consume_ws(self, updates_url: str, cookies: Dict[str, str]) -> None:
        """
        Consume Quasar WebSocket using cookies (NO OAuth token).
        
        ⚠️ ARCHITECTURAL RULE: NEVER add Authorization header here!
        WebSocket will reject OAuth Bearer tokens.
        """
        # Валидация URL
        if not updates_url or not isinstance(updates_url, str):
            raise ValueError(f"Invalid updates_url: {updates_url}")
        
        # Обновляем сессию если cookies изменились
        if self._current_cookies != cookies:
            # Закрываем старую сессию если есть
            if self._session and not self._session.closed:
                await self._session.close()
            # Создаем новую сессию с обновленными cookies
            self._cookie_jar = self._cookie_jar_from(cookies)
            self._session = aiohttp.ClientSession(cookie_jar=self._cookie_jar)
            self._current_cookies = cookies.copy()
        elif not self._session or self._session.closed:
            # Создаем сессию если её нет
            self._cookie_jar = self._cookie_jar_from(cookies)
            self._session = aiohttp.ClientSession(cookie_jar=self._cookie_jar)
            self._current_cookies = cookies.copy()
        
        headers = {
            "Origin": "https://iot.quasar.yandex.ru",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        # CRITICAL: NO Authorization header! Quasar WS uses cookies ONLY.
        assert "Authorization" not in headers, "NEVER use OAuth with Quasar WebSocket!"
        
        # YandexStation передает updates_url напрямую как строку
        # Используем heartbeat=60 как в YandexStation (увеличенный интервал для избежания таймаутов)
        try:
            async with self._session.ws_connect(updates_url, headers=headers, heartbeat=60) as ws:
                self._ws = ws
                await self._log("info", "Quasar WS connected", url=updates_url[:80])
                async for msg in ws:
                    if self._stop_event.is_set():
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        exc = ws.exception()
                        raise exc or RuntimeError("WebSocket closed")
                await self._log("warning", "Quasar WS finished (loop exit)")
        except (TypeError, AttributeError) as e:
            # Если ошибка с raw_host, пробуем использовать URL объект
            if "raw_host" in str(e) or "str" in str(e):
                await self._log("debug", f"Retrying WS connect with URL object: {e}")
                ws_url = URL(updates_url)
                async with self._session.ws_connect(ws_url, headers=headers, heartbeat=60) as ws:
                    self._ws = ws
                    await self._log("info", "Quasar WS connected (via URL object)", url=updates_url[:80])
                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            exc = ws.exception()
                            raise exc or RuntimeError("WebSocket closed")
                    await self._log("warning", "Quasar WS finished (loop exit)")
            else:
                raise

    async def _handle_message(self, raw: str) -> None:
        try:
            envelope = json.loads(raw)
            if envelope.get("operation") != "update_states":
                return
            payload_raw = envelope.get("message")
            payload = json.loads(payload_raw) if payload_raw else {}
            updated = payload.get("updated_devices") or []
            for device in updated:
                await self._process_device_update(device)
        except Exception as e:
            await self._log("error", f"Failed to process WS message: {type(e).__name__}: {e}")

    async def _process_device_update(self, device: Dict[str, Any]) -> None:
        device_id = device.get("id") or device.get("device_id")
        if not device_id:
            return

        caps = DeviceTransformer._extract_capabilities(device.get("capabilities", []))
        states_list: List[Dict[str, Any]] = []

        # Прямые states если есть
        if isinstance(device.get("states"), list):
            states_list.extend(device.get("states") or [])
        if isinstance(device.get("state"), list):
            states_list.extend(device.get("state") or [])

        # В обновлениях Яндекса значения могут лежать внутри capabilities.state
        for cap in device.get("capabilities", []) or []:
            if isinstance(cap, dict) and cap.get("state") is not None:
                states_list.append({"type": cap.get("type"), "state": cap.get("state")})

        state = DeviceTransformer._extract_state(states_list, caps)

        # ВАЖНО: Публикуем обновление ВСЕГДА, даже если state пустой
        # Это нужно для сброса pending состояния, даже если обновление не содержит изменений
        # Сохраняем состояние для кеша
        self._devices[device_id] = {"state": state or {}, "raw": device}
        
        # Публикуем обновление - если state пустой, это все равно сбросит pending
        # Это важно для случаев, когда устройство уже в нужном состоянии
        await self._publish_state(device_id, state or {})
        
        # Логируем для отладки
        await self._log(
            "debug",
            f"Processed device update from WS",
            device_id=device_id,
            state=state,
            has_on="on" in (state or {}),
        )

    async def _seed_and_publish(self, devices: List[Dict[str, Any]]) -> None:
        for device in devices:
            device_id = device.get("id")
            if not device_id:
                continue
            caps = DeviceTransformer._extract_capabilities(device.get("capabilities", []))
            raw_states = device.get("states") or []
            state = DeviceTransformer._extract_state(raw_states, caps)
            if state:
                self._devices[device_id] = {"state": state, "raw": device}
                await self._publish_state(device_id, state)

    async def _publish_state(self, device_id: str, state: Dict[str, Any]) -> None:
        """Публикует обновление состояния устройства из WebSocket.
        
        Args:
            device_id: external_id устройства (ID из Quasar API)
            state: словарь с состоянием (например, {"on": True})
        """
        payload = {"external_id": device_id, "state": state}
        
        # Логируем публикацию для отладки
        await self._log(
            "debug",
            f"Publishing state update from WS",
            external_id=device_id,
            state=state,
        )
        
        try:
            await self.runtime.event_bus.publish("external.device_state_reported", payload)
            await self._log(
                "debug",
                f"State update published successfully",
                external_id=device_id,
            )
        except Exception as e:
            await self._log(
                "error",
                f"Failed to publish state update: {e}",
                external_id=device_id,
                state=state,
            )
        
        # Вызываем подписчиков
        for cb in list(self._subscribers.get(device_id, [])):
            try:
                result = cb(payload)
                if inspect.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                continue

    def _cookie_jar_from(self, cookies: Optional[Dict[str, str]]) -> aiohttp.CookieJar:
        """Создает CookieJar с cookies для Quasar API.
        
        ВАЖНО: Cookies должны быть установлены для домена .yandex.ru
        чтобы работать с iot.quasar.yandex.ru
        """
        jar = aiohttp.CookieJar(unsafe=True)  # unsafe=True для cross-domain cookies
        if cookies:
            # Используем URL объект для правильной установки cookies
            base_url = URL("https://iot.quasar.yandex.ru")
            
            # Устанавливаем cookies используя SimpleCookie для правильного формата
            from http.cookies import SimpleCookie
            cookie_dict = SimpleCookie()
            for name, value in cookies.items():
                cookie_dict[name] = str(value)
                # Устанавливаем domain для работы со всеми поддоменами yandex.ru
                cookie_dict[name]["domain"] = ".yandex.ru"
                cookie_dict[name]["path"] = "/"
            
            # Обновляем jar с cookies
            jar.update_cookies(cookie_dict, response_url=base_url)
            
            # Также устанавливаем для yandex.ru напрямую (на всякий случай)
            yandex_url = URL("https://yandex.ru")
            jar.update_cookies(cookie_dict, response_url=yandex_url)
        
        return jar

    async def _load_cookies(self) -> Optional[Dict[str, str]]:
        """Попытка получить cookies из service_registry, иначе None."""
        # Приоритет 1: yandex_device_auth.get_session (device auth сохраняет cookies)
        try:
            if await self.runtime.service_registry.has_service("yandex_device_auth.get_session"):
                session = await self.runtime.service_registry.call("yandex_device_auth.get_session")
                if isinstance(session, dict) and session.get("linked"):
                    # Пытаемся получить cookies из storage (device_auth сохраняет их там)
                    try:
                        stored = await self.runtime.storage.get("yandex", "cookies")
                        if isinstance(stored, dict) and stored:
                            await self._log("debug", "Loaded cookies from yandex_device_auth", cookie_count=len(stored))
                            return stored
                    except Exception as e:
                        await self._log("debug", f"Failed to load cookies from storage: {e}")
        except Exception as e:
            await self._log("debug", f"Failed to check yandex_device_auth.get_session: {e}")
        
        # Приоритет 2: сервис oauth_yandex.get_cookies если реализован (для обратной совместимости)
        try:
            if await self.runtime.service_registry.has_service("oauth_yandex.get_cookies"):
                cookies = await self.runtime.service_registry.call("oauth_yandex.get_cookies")
                if isinstance(cookies, dict) and cookies:
                    await self._log("debug", "Loaded cookies from oauth_yandex", cookie_count=len(cookies))
                    return cookies
        except Exception as e:
            await self._log("debug", f"Failed to load cookies from oauth_yandex: {e}")
        
        # Приоритет 3: storage namespace yandex -> cookies (fallback)
        try:
            stored = await self.runtime.storage.get("yandex", "cookies")
            if isinstance(stored, dict) and stored:
                await self._log("debug", "Loaded cookies from storage fallback", cookie_count=len(stored))
                return stored
        except Exception as e:
            await self._log("debug", f"Failed to load cookies from storage fallback: {e}")
        
        return None

    async def _log(self, level: str, message: str, **context: Any) -> None:
        with contextlib.suppress(Exception):
            await self.runtime.service_registry.call(
                "logger.log",
                level=level,
                message=message,
                plugin=self.plugin_name,
                context=context or None,
            )
