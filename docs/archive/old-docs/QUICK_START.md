# Quick Start: yandex_smart_home_real_v0

Быстрое руководство для запуска Real plugin Яндекса в Home Console.

## ⚡ 5-минутная инициализация

### 1. Проверить зависимости

```bash
cd core-runtime-service

# Проверить что aiohttp установлен
python -c "import aiohttp; print('✓ aiohttp OK')"

# Если нет:
pip install aiohttp
```

### 2. Проверить наличие плагинов

```bash
# Должны существовать:
ls -la plugins/base_plugin.py
ls -la plugins/oauth_yandex.py
ls -la plugins/yandex_smart_home_real.py      # ← Новый плагин
ls -la plugins/yandex_smart_home_stub.py
ls -la plugins/devices_plugin.py
ls -la plugins/system_logger_plugin.py
```

### 3. Запустить smoke-тест

```bash
# Для real plugin (с mock данными)
python smoke_real_yandex_sync.py

# Ожидаемый результат:
# ✓ sync_devices returned 3 devices
# ✓ 3 events received
# ✓ All assertions passed!
```

### 4. Убедиться что stub ещё работает

```bash
# Для stub plugin (старый)
python smoke_yandex_sync.py

# Ожидаемый результат:
# Returned devices: [...]
```

## 🚀 Запуск в production

### Используя auto-load (рекомендуется)

Если `console.py` имеет `_auto_load_plugins()`, то:

```bash
# Real plugin загружается автоматически
python console.py

# Real plugin:
# 1. Загружается как любой другой плагин
# 2. Готов к вызову yandex.sync_devices()
# 3. Может быть заменён stub без изменения кода
```

### Использование в коде

```python
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import AsyncSqliteStorage

async def main():
    storage = AsyncSqliteStorage("data/console.db")
    runtime = CoreRuntime(storage)
    
    # ... загрузить плагины ...
    
    # Real plugin загружен и готов
    devices = await runtime.service_registry.call("yandex.sync_devices")
    print(f"Synced {len(devices)} devices")
```

## 📋 Пошаговый workflow

### Этап 1: OAuth конфигурация

Пользователь заполняет OAuth параметры (в UI):

```typescript
// admin-ui-service/src/pages/OAuthPage.tsx

// 1. Ввести Client ID, Secret, Redirect URI
// 2. Кликнуть "Сохранить конфигурацию"
await configureOAuth({
    client_id: "YOUR_CLIENT_ID",
    client_secret: "YOUR_CLIENT_SECRET",
    redirect_uri: "http://localhost:3000/callback"
});
```

**Backend:** 
- `POST /oauth/yandex/configure` 
- Сохраняет в storage (oauth_yandex)

### Этап 2: Авторизация

Пользователь авторизуется в Яндексе:

```typescript
// 1. Кликнуть "Авторизоваться в Яндексе"
// 2. Откроется окно Яндекса
// 3. Авторизуется
// 4. Вернётся в приложение с code в URL
const url = await getAuthorizeUrl();
window.open(url, '_blank');

// 5. Пользователь копирует code из URL
// 6. Вводит code в форму
await exchangeCode(code);
```

**Backend:**
- `GET /oauth/yandex/authorize-url` → URL Яндекса
- `POST /oauth/yandex/exchange-code` → access_token сохранён

### Этап 3: Синхронизация устройств

Бэкенд синхронизирует устройства:

```python
# Автоматически или по команде
devices = await runtime.service_registry.call("yandex.sync_devices")

# Real plugin:
# 1. Получает access_token из oauth_yandex
# 2. Вызывает API Яндекса
# 3. Преобразует устройства
# 4. Публикует external.device_discovered события
# 5. devices_plugin регистрирует устройства
```

### Этап 4: Использование устройств

Приложение может использовать синхронизированные устройства:

```python
# Получить список устройств
devices = await runtime.state_engine.get("devices")

# Использовать в automation
# automation_plugin может создавать правила для этих устройств
```

## 🔧 Типичные операции

### Синхронизировать устройства

```python
async def sync_devices():
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        return {"status": "success", "count": len(devices)}
    except ValueError:
        return {"status": "error", "message": "Not authorized"}
    except RuntimeError as e:
        if "HTTP 401" in str(e):
            # Переавторизоваться
            return {"status": "token_expired"}
        return {"status": "error", "message": str(e)}
```

### Получить статус

```python
async def get_status():
    status = await runtime.service_registry.call("oauth_yandex.get_status")
    
    return {
        "configured": status.get("configured"),
        "authorized": status.get("authorized"),
        "expires_at": status.get("expires_at"),
    }
```

### Подписаться на события

```python
async def on_device_discovered(event_type: str, data: dict):
    print(f"Device: {data['external_id']}")
    print(f"Type: {data['type']}")
    print(f"State: {data['state']}")

runtime.event_bus.subscribe("external.device_discovered", on_device_discovered)

# Теперь будет вызываться при каждом обнаружении устройства
```

## 🐛 Отладка

### Проверить что плагин загружен

```python
plugins = runtime.plugin_manager.list_plugins()
print("Loaded plugins:", plugins)

# Должно содержать:
# - 'yandex_smart_home_real'
```

### Проверить что сервис зарегистрирован

```python
try:
    devices = await runtime.service_registry.call("yandex.sync_devices")
    print("✓ Service registered and working")
except Exception as e:
    print(f"✗ Service error: {e}")
```

### Включить логирование

```python
# Если загружен system_logger_plugin, логи выводятся в stdout:

# [INFO] yandex_smart_home_real_v0 запущен
# [INFO] Синхронизация завершена: 3 устройств
# [ERROR] Ошибка синхронизации: ...
```

### Проверить OAuth токены

```python
# Debug endpoint (только для разработки)
tokens = await runtime.service_registry.call("oauth_yandex.get_tokens")
print(f"Access token: {tokens.get('access_token', 'NOT SET')}")
print(f"Expires in: {tokens.get('expires_in')} seconds")
```

## 📚 Дополнительные ресурсы

| Документ | Описание |
|----------|----------|
| [YANDEX_REAL_README.md](plugins/YANDEX_REAL_README.md) | Полная документация плагина |
| [STUB_VS_REAL.md](plugins/STUB_VS_REAL.md) | Сравнение архитектур stub vs real |
| [YANDEX_REAL_INTEGRATION.md](YANDEX_REAL_INTEGRATION.md) | Пошаговое руководство интеграции |
| [YANDEX_BEST_PRACTICES.md](YANDEX_BEST_PRACTICES.md) | Best practices |
| [YANDEX_CODE_EXAMPLES.md](YANDEX_CODE_EXAMPLES.md) | Примеры кода |
| [smoke_real_yandex_sync.py](smoke_real_yandex_sync.py) | Smoke-тест |

## ❓ FAQ

### Q: Как переключиться со stub на real?

**A:** Просто замените импорт:

```python
# Было:
from plugins.yandex_smart_home_stub import YandexSmartHomeStubPlugin
plugin = YandexSmartHomeStubPlugin(runtime)

# Стало:
from plugins.yandex_smart_home_real import YandexSmartHomeRealPlugin
plugin = YandexSmartHomeRealPlugin(runtime)

# Остальной код не меняется!
```

### Q: Real plugin требует действительный OAuth?

**A:** Да, real plugin требует действительный `access_token` от Яндекса. 
Используйте stub для разработки без OAuth.

### Q: Что если токен истёк?

**A:** Обработка встроена:

```python
try:
    devices = await runtime.service_registry.call("yandex.sync_devices")
except RuntimeError as e:
    if "HTTP 401" in str(e):
        # Токен истёк, переавторизуйтесь
        await runtime.service_registry.call("oauth_yandex.set_tokens", {})
```

### Q: Как использовать real plugin в тестах?

**A:** Используйте mock-токены:

```python
async def mock_get_tokens():
    return {"access_token": "fake_token_for_testing"}

runtime.service_registry.register("oauth_yandex.get_tokens", mock_get_tokens)

# Теперь можно тестировать с real plugin
```

### Q: Какие плагины должны быть загружены перед real?

**A:** Обязательные:
1. `system_logger` (для логирования)
2. `oauth_yandex` (для токенов)
3. `devices` (для регистрации устройств)

### Q: Real plugin хранит токены?

**A:** Нет. Токены хранит `oauth_yandex` плагин. Real plugin только использует их.

### Q: Могу ли я вызвать sync_devices() параллельно несколько раз?

**A:** Да, это безопасно. Каждый вызов независим.

### Q: Как настроить периодическую синхронизацию?

**A:** См. [YANDEX_CODE_EXAMPLES.md](YANDEX_CODE_EXAMPLES.md) - раздел "Периодическая синхронизация"

## 🎯 Контрольный список

Перед запуском:

- [ ] aiohttp установлен
- [ ] plugins/yandex_smart_home_real.py существует
- [ ] smoke_real_yandex_sync.py проходит
- [ ] smoke_yandex_sync.py (stub) всё ещё проходит
- [ ] console.py загружает плагины

Для production:

- [ ] OAuth конфигурирован правильно
- [ ] Логирование включено
- [ ] Обработка ошибок реализована
- [ ] Периодическая синхронизация настроена
- [ ] Мониторинг включен
- [ ] Backup плана есть (fallback на stub?)

## 🚀 Готово!

Real plugin ready to use!

```bash
# Проверить
python smoke_real_yandex_sync.py

# Ожидаемый результат
# ✓ All assertions passed!
# === Test Complete ===
```

Наслаждайтесь! 🎉
