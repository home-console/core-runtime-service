#!/usr/bin/env python3
"""
Утилита для установки Yandex session cookies для Quasar API.

Важно: этот скрипт находится внутри плагина `oauth_yandex`, потому что
ядро/модули не должны содержать yandex-специфичные неймспейсы/инструкции.

Quasar API требует cookies из активной сессии Яндекса, а не OAuth токен.

Как получить cookies:
1. Откройте https://yandex.ru в браузере
2. Войдите в свой аккаунт
3. Откройте DevTools (F12) → Application → Cookies → https://yandex.ru
4. Скопируйте значения важных cookies:
   - Session_id
   - yandexuid
   - sessionid2
   - i (опционально)
   - L (опционально)

Использование:
    python3 core-runtime-service/plugins/oauth_yandex/dev_scripts/set_yandex_cookies.py

Или напрямую через API:
    curl -X POST http://localhost:8000/oauth/yandex/cookies \
      -H "Content-Type: application/json" \
      -d '{"Session_id": "...", "yandexuid": "...", "sessionid2": "..."}'
"""

import asyncio
import sys
from pathlib import Path

# Add core-runtime-service to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.runtime.runtime import CoreRuntime


async def main() -> None:
    print("=== Установка Yandex Session Cookies для Quasar API ===\n")
    print("Quasar API (iot.quasar.yandex.ru) требует cookies из активной сессии Яндекса.")
    print("OAuth токен НЕ работает для Quasar API.\n")

    print("Введите cookies из вашей активной сессии яндекса:")
    print("(Откройте DevTools в браузере → Application → Cookies → https://yandex.ru)\n")

    cookies: dict[str, str] = {}

    session_id = input("Session_id (обязательно): ").strip()
    if not session_id:
        print("Session_id обязателен!")
        return
    cookies["Session_id"] = session_id

    yandexuid = input("yandexuid (обязательно): ").strip()
    if not yandexuid:
        print("yandexuid обязателен!")
        return
    cookies["yandexuid"] = yandexuid

    sessionid2 = input("sessionid2 (опционально, Enter чтобы пропустить): ").strip()
    if sessionid2:
        cookies["sessionid2"] = sessionid2

    i_cookie = input("i (опционально, Enter чтобы пропустить): ").strip()
    if i_cookie:
        cookies["i"] = i_cookie

    l_cookie = input("L (опционально, Enter чтобы пропустить): ").strip()
    if l_cookie:
        cookies["L"] = l_cookie

    print("\nСохраняю cookies через сервис oauth_yandex.set_cookies ...")

    # NOTE: This script is best-effort; runtime wiring may differ across environments.
    runtime = CoreRuntime()  # type: ignore[call-arg]
    try:
        init = getattr(runtime, "initialize", None)
        if callable(init):
            await init()
        else:
            await runtime.start()

        await runtime.service_registry.call("oauth_yandex.set_cookies", cookies=cookies)
        print("Cookies успешно сохранены.")
        print(f"Сохранённые cookies: {list(cookies.keys())}")
    finally:
        shutdown = getattr(runtime, "shutdown", None)
        if callable(shutdown):
            await shutdown()


if __name__ == "__main__":
    asyncio.run(main())

