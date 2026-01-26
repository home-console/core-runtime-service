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
                    cookie_names=list(cookies.keys())
                )
                
                devices, updates_url = await self._fetch_devices_and_url(cookies)
                await self._seed_and_publish(devices)
                backoff = 1.0
                await self._consume_ws(updates_url, cookies)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await self._log(
                    "error",
                    f"Quasar WS loop error: {type(e).__name__}: {e}",
                    error_type=type(e).__name__,
                    error_msg=str(e),
                    backoff=round(backoff, 2),
                )
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
        return devices, updates_url

    async def _consume_ws(self, updates_url: str, cookies: Dict[str, str]) -> None:
        """
        Consume Quasar WebSocket using cookies (NO OAuth token).
        
        ⚠️ ARCHITECTURAL RULE: NEVER add Authorization header here!
        WebSocket will reject OAuth Bearer tokens.
        """
        headers = {
            "Origin": "https://iot.quasar.yandex.ru",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        # CRITICAL: NO Authorization header! Quasar WS uses cookies ONLY.
        assert "Authorization" not in headers, "NEVER use OAuth with Quasar WebSocket!"
        
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(cookie_jar=self._cookie_jar_from(cookies))
        async with self._session.ws_connect(updates_url, headers=headers, heartbeat=25) as ws:
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

        # Сохраняем и уведомляем только если есть полезные данные
        if state:
            self._devices[device_id] = {"state": state, "raw": device}
            await self._publish_state(device_id, state)

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
        payload = {"external_id": device_id, "state": state}
        with contextlib.suppress(Exception):
            await self.runtime.event_bus.publish("external.device_state_reported", payload)
        for cb in list(self._subscribers.get(device_id, [])):
            try:
                result = cb(payload)
                if inspect.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                continue

    def _cookie_jar_from(self, cookies: Optional[Dict[str, str]]) -> aiohttp.CookieJar:
        if self._cookie_jar:
            # Если уже есть куки и не переданы новые — используем текущие
            if not cookies:
                return self._cookie_jar
            existing = self._cookie_jar.filter_cookies("https://iot.quasar.yandex.ru")
            if existing:
                return self._cookie_jar
        jar = aiohttp.CookieJar()
        if cookies:
            parsed = urlparse("https://iot.quasar.yandex.ru")
            for name, value in cookies.items():
                jar.update_cookies({name: value}, response_url=parsed.geturl())
        self._cookie_jar = jar
        return jar

    async def _load_cookies(self) -> Optional[Dict[str, str]]:
        """Попытка получить cookies из service_registry, иначе None."""
        # Приоритет: сервис oauth_yandex.get_cookies если реализован
        try:
            if await self.runtime.service_registry.has_service("oauth_yandex.get_cookies"):
                cookies = await self.runtime.service_registry.call("oauth_yandex.get_cookies")
                if isinstance(cookies, dict):
                    return cookies
        except Exception:
            pass
        # Альтернативно: storage namespace yandex -> cookies
        try:
            stored = await self.runtime.storage.get("yandex", "cookies")
            if isinstance(stored, dict):
                return stored
        except Exception:
            pass
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
