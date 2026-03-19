#!/usr/bin/env python3
"""
Утилита для установки Yandex session cookies для Quasar API.

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
    python dev-scripts/set_yandex_cookies.py
    
Или напрямую через API:
    curl -X POST http://localhost:8000/oauth/yandex/cookies \
      -H "Content-Type: application/json" \
      -d '{"Session_id": "...", "yandexuid": "...", "sessionid2": "..."}'
"""
import asyncio
import sys
from pathlib import Path

# Добавляем путь к core-runtime в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.runtime.runtime import CoreRuntime


async def main():
    print("=== Установка Yandex Session Cookies для Quasar API ===\n")
    print("Quasar API (iot.quasar.yandex.ru) требует cookies из активной сессии Яндекса.")
    print("OAuth токен НЕ работает для Quasar API.\n")
    
    print("Введите cookies из вашей активной сессии яндекса:")
    print("(Откройте DevTools в браузере → Application → Cookies → https://yandex.ru)\n")
    
    cookies = {}
    
    # Основные cookies
    session_id = input("Session_id (обязательно): ").strip()
    if not session_id:
        print("❌ Session_id обязателен!")
        return
    cookies["Session_id"] = session_id
    
    yandexuid = input("yandexuid (обязательно): ").strip()
    if not yandexuid:
        print("❌ yandexuid обязателен!")
        return
    cookies["yandexuid"] = yandexuid
    
    # Дополнительные cookies
    sessionid2 = input("sessionid2 (опционально, Enter чтобы пропустить): ").strip()
    if sessionid2:
        cookies["sessionid2"] = sessionid2
    
    i_cookie = input("i (опционально, Enter чтобы пропустить): ").strip()
    if i_cookie:
        cookies["i"] = i_cookie
    
    l_cookie = input("L (опционально, Enter чтобы пропустить): ").strip()
    if l_cookie:
        cookies["L"] = l_cookie
    
    print("\n📝 Сохраняю cookies...")
    
    # Создаём runtime и сохраняем cookies
    runtime = CoreRuntime()
    try:
        await runtime.initialize()
        
        # Сохраняем через service
        await runtime.service_registry.call("oauth_yandex.set_cookies", cookies=cookies)
        
        print("✅ Cookies успешно сохранены!")
        print(f"\nСохранённые cookies: {list(cookies.keys())}")
        print("\n🚀 Quasar WebSocket теперь сможет подключиться к API.")
        print("Перезапустите core-runtime для применения изменений.")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
