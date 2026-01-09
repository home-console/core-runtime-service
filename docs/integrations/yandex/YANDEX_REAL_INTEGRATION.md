# Интеграция Real Plugin: Пошаговое руководство

## Общий поток

```
┌──────────────────────────────────────────────────────────┐
│ 1. Пользователь открывает UI (admin-ui-service)         │
│    ↓                                                      │
│ 2. Заполняет OAuth конфигурацию (Client ID, Secret)     │
│    POST /oauth/yandex/configure                         │
│    ↓                                                      │
│ 3. Кликает "Авторизоваться в Яндексе"                   │
│    GET /oauth/yandex/authorize-url → window.open()      │
│    ↓                                                      │
│ 4. Авторизуется в Яндексе, получает code                │
│    ↓                                                      │
│ 5. Вводит code в UI                                      │
│    POST /oauth/yandex/exchange-code → access_token      │
│    ↓                                                      │
│ 6. UI показывает "✓ Яндекс подключён"                    │
│    ↓                                                      │
│ 7. Бэкенд вызывает yandex.sync_devices()                │
│    (может быть автоматически или по команде)            │
│    ↓                                                      │
│ 8. Real plugin получает устройства из API Яндекса        │
│    ↓                                                      │
│ 9. Публикует external.device_discovered события          │
│    ↓                                                      │
│ 10. devices_plugin регистрирует устройства               │
│     ↓                                                     │
│ 11. UI может показать список устройств                   │
└──────────────────────────────────────────────────────────┘
```

## Шаг 1: Инициализация Runtime

### В `console.py` или `main.py`:

```python
from core.runtime import CoreRuntime
from plugins.system_logger_plugin import SystemLoggerPlugin
from plugins.oauth_yandex import OAuthYandexPlugin
from plugins.yandex_smart_home_real import YandexSmartHomeRealPlugin
from plugins.devices_plugin import DevicesPlugin

async def main():
    # 1. Создать runtime
    storage = AsyncSqliteStorage("data/console.db")  # или другой storage
    runtime = CoreRuntime(storage)
    
    # 2. Загрузить плагины в правильном порядке
    # - logger (нужен для всех остальных)
    # - oauth_yandex (нужен для real-плагина)
    # - devices (нужен для регистрации устройств)
    # - yandex_smart_home_real
    
    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)
    await runtime.plugin_manager.start_plugin(logger.metadata.name)
    
    oauth = OAuthYandexPlugin(runtime)
    await runtime.plugin_manager.load_plugin(oauth)
    await runtime.plugin_manager.start_plugin(oauth.metadata.name)
    
    devices = DevicesPlugin(runtime)
    await runtime.plugin_manager.load_plugin(devices)
    await runtime.plugin_manager.start_plugin(devices.metadata.name)
    
    # Real Yandex plugin
    yandex = YandexSmartHomeRealPlugin(runtime)
    await runtime.plugin_manager.load_plugin(yandex)
    await runtime.plugin_manager.start_plugin(yandex.metadata.name)
    
    # 3. Запустить HTTP сервер
    await runtime.start()
    
    # ... остальной код
```

## Шаг 2: OAuth Конфигурация (Backend)

OAuth конфигурация хранится в storage после вызова `oauth_yandex.configure`:

```python
# Это вызывается из UI
await runtime.service_registry.call(
    "oauth_yandex.configure",
    client_id="123456.apps.yandexcloud.net",
    client_secret="secret_from_yandex",
    redirect_uri="http://localhost:3000/callback"
)

# Или programmatically
await runtime.service_registry.call(
    "oauth_yandex.set_tokens",
    {
        "access_token": "real_token_from_yandex",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
)
```

## Шаг 3: Получение Устройств

### Вариант A: Manual (по команде)

```python
# Когда пользователь кликает "Синхронизировать устройства"
devices = await runtime.service_registry.call("yandex.sync_devices")

# Отправить результат пользователю
return {
    "status": "success",
    "devices_count": len(devices),
    "devices": devices,
}
```

### Вариант B: Automatic (при авторизации)

```python
# После успешного exchange_code в oauth_yandex

# Добавить auto-call в on_start()
async def on_exchange_code_complete():
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        print(f"Автоматическая синхронизация: {len(devices)} устройств")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")
```

### Вариант C: Scheduled (периодическая)

```python
# Синхронизировать каждый час
async def auto_sync_task():
    while True:
        try:
            await asyncio.sleep(3600)  # каждый час
            devices = await runtime.service_registry.call("yandex.sync_devices")
            print(f"Плановая синхронизация: {len(devices)} устройств")
        except Exception:
            pass  # Игнорируем ошибки при плановой синхронизации
```

## Шаг 4: Обработка Событий (в devices_plugin)

Real plugin публикует `external.device_discovered` события, которые обрабатывает devices_plugin:

```python
# devices_plugin получает событие
async def on_external_device_discovered(event_type: str, data: dict):
    external_id = data["external_id"]
    device_type = data["type"]
    capabilities = data["capabilities"]
    state = data["state"]
    
    # Регистрирует как external device в state_engine
    await runtime.state_engine.set(
        f"external_devices.{external_id}",
        {
            "provider": data["provider"],
            "type": device_type,
            "capabilities": capabilities,
            "state": state,
        }
    )
    
    # Может создать mapping с internal device
    # automation может использовать это в автоматизации
```

## Шаг 5: UI Интеграция (admin-ui-service)

### Компонент OAuth

В `OAuthPage.tsx`:

```typescript
// 1. Получить статус при загрузке
const loadStatus = async () => {
    const s = await getOAuthStatus();
    setStatus(s);
}

// 2. Настроить OAuth (заполнить Client ID, Secret, Redirect URI)
const handleConfigure = async () => {
    await configureOAuth({
        client_id,
        client_secret,
        redirect_uri
    });
}

// 3. Авторизоваться (открыть окно Яндекса)
const handleAuthorize = async () => {
    const url = await getAuthorizeUrl();
    window.open(url, '_blank');
}

// 4. Обменять code (когда пользователь вернулся)
const handleExchangeCode = async () => {
    await exchangeCode(code);  // → access_token сохранится в backend
}
```

### Компонент Синхронизации

```typescript
// Добавить кнопку в UI
<button onClick={syncDevices}>
    Синхронизировать устройства
</button>

// Обработчик
const syncDevices = async () => {
    try {
        setLoading(true);
        const devices = await fetch("/api/yandex/sync-devices");
        setDevices(devices);
        setMessage("✓ Синхронизировано");
    } catch (err) {
        setMessage(`✗ Ошибка: ${err.message}`);
    } finally {
        setLoading(false);
    }
}
```

### HTTP Endpoint (Backend)

```python
# В api_gateway_plugin или как отдельный эндпоинт
@app.post("/api/yandex/sync-devices")
async def sync_devices_endpoint():
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        return {
            "status": "success",
            "count": len(devices),
            "devices": devices,
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 400
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}, 500
```

## Обработка Ошибок

### Ошибка: "Токены не найдены"

**Причина:** Пользователь не авторизован в Яндексе

**Решение:**
```python
try:
    devices = await runtime.service_registry.call("yandex.sync_devices")
except ValueError as e:
    if "Токены не найдены" in str(e):
        # Перенаправить на OAuth страницу
        return {"status": "unauthorized", "redirect": "/oauth"}
```

### Ошибка: "HTTP 401 Unauthorized"

**Причина:** Токен истёк

**Решение:**
```python
except RuntimeError as e:
    if "HTTP 401" in str(e):
        # Попросить переавторизоваться
        # Очистить старый токен
        await runtime.service_registry.call(
            "oauth_yandex.set_tokens",
            {}  # Очистить токены
        )
        return {"status": "token_expired", "redirect": "/oauth"}
```

### Ошибка: "Сетевая ошибка"

**Причина:** Нет интернета или API Яндекса недоступен

**Решение:**
```python
except RuntimeError as e:
    if "Сетевая ошибка" in str(e):
        # Retry позже (можно использовать background task)
        return {"status": "error", "retry_after": 60}
```

## Пример: Полный Workflow

```python
# 1. Инициализировать runtime с real plugin
runtime = CoreRuntime(storage)
await setup_plugins(runtime)

# 2. Пользователь заполняет OAuth форму
await runtime.service_registry.call(
    "oauth_yandex.configure",
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
    redirect_uri="http://localhost:3000/callback"
)

# 3. Пользователь авторизуется и получает code
# (это происходит в браузере через Яндекс)

# 4. UI отправляет code на бэкенд
await runtime.service_registry.call(
    "oauth_yandex.exchange_code",
    code="код_из_яндекса"
)
# ← Теперь access_token сохранён в storage

# 5. Синхронизировать устройства
devices = await runtime.service_registry.call("yandex.sync_devices")

# ← Real plugin:
#   a) Получит access_token из oauth_yandex
#   b) Вызовет GET https://api.iot.yandex.net/v1.0/user/devices
#   c) Преобразует ответ
#   d) Опубликует external.device_discovered события
#   e) Вернёт список устройств

# 6. Devices plugin регистрирует устройства
# (это происходит автоматически при обработке события)

# 7. Показать пользователю результат
print(f"Синхронизировано {len(devices)} устройств")
for device in devices:
    print(f"  - {device['external_id']}: {device['type']}")
```

## Безопасность

### Checklist

- ✅ Не передавать Client Secret в браузер
- ✅ Не хранить access_token в браузере
- ✅ Использовать HTTPS для передачи токенов
- ✅ Не логировать access_token в лог-файлы
- ✅ Проверять статус перед каждой синхронизацией
- ✅ Обрабатывать истечение токена
- ✅ Не делать retry автоматически (может заблокировать аккаунт)

## Производительность

### Оптимизация

1. **Кеширование:**
   ```python
   # Кешировать результаты на 5 минут
   if cache.get("yandex_devices_cache"):
       return cache.get("yandex_devices_cache")
   ```

2. **Async/await:**
   ```python
   # Все операции асинхронные, не блокируют
   # Можно вызывать несколько sync_devices() параллельно
   ```

3. **Batch операции:**
   ```python
   # Если много устройств, обработать batch-ами
   for device in devices[::100]:  # По 100 за раз
       await process_device(device)
   ```

## Мониторинг

### Логирование

```python
# Real plugin автоматически логирует важные события
# через runtime.service_registry.call("logger.log", ...)

# Примеры:
# - "yandex_smart_home_real_v0 запущен"
# - "Ошибка получения токенов от oauth_yandex"
# - "Ошибка публикации события для устройства ..."
```

### Метрики

```python
# Можно отслеживать:
# - Количество устройств
# - Время синхронизации
# - Ошибки
# - Частоту вызовов API

async def sync_devices_with_metrics():
    start = time.time()
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        duration = time.time() - start
        
        # Отправить метрики
        await metrics.record({
            "name": "yandex.sync_devices",
            "status": "success",
            "devices_count": len(devices),
            "duration_ms": duration * 1000,
        })
        
        return devices
    except Exception as e:
        await metrics.record({
            "name": "yandex.sync_devices",
            "status": "error",
            "error": str(e),
        })
        raise
```

## Заключение

Real plugin успешно интегрируется с остальной системой благодаря:
- ✅ Идентичному API со stub
- ✅ Использованию oauth_yandex для управления токенами
- ✅ Публикации стандартных событий
- ✅ Отсутствию прямых зависимостей от UI

Это позволяет разрабатывать быстро (stub), а потом переключиться на production (real) без изменения кода приложения.
