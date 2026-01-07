# Best Practices: yandex_smart_home_real_v0

## Содержание

1. [Инициализация](#инициализация)
2. [Обработка ошибок](#обработка-ошибок)
3. [Производительность](#производительность)
4. [Безопасность](#безопасность)
5. [Мониторинг](#мониторинг)
6. [Testing](#testing)

---

## Инициализация

### ✅ Правильный порядок загрузки

```python
async def main():
    runtime = CoreRuntime(storage)
    
    # 1. Logger (первым, так как нужен для логирования)
    logger = SystemLoggerPlugin(runtime)
    await runtime.plugin_manager.load_plugin(logger)
    await runtime.plugin_manager.start_plugin("system_logger")
    
    # 2. OAuth (нужен для получения токенов)
    oauth = OAuthYandexPlugin(runtime)
    await runtime.plugin_manager.load_plugin(oauth)
    await runtime.plugin_manager.start_plugin("oauth_yandex")
    
    # 3. Devices (нужен для регистрации external устройств)
    devices = DevicesPlugin(runtime)
    await runtime.plugin_manager.load_plugin(devices)
    await runtime.plugin_manager.start_plugin("devices")
    
    # 4. Real Yandex (зависит от oauth и devices)
    yandex = YandexSmartHomeRealPlugin(runtime)
    await runtime.plugin_manager.load_plugin(yandex)
    await runtime.plugin_manager.start_plugin("yandex_smart_home_real")
    
    # 5. Остальные плагины
    # ...
```

### ❌ Неправильный порядок

```python
# ✗ Неправильно: real плагин загружен до oauth
yandex = YandexSmartHomeRealPlugin(runtime)
await runtime.plugin_manager.load_plugin(yandex)

oauth = OAuthYandexPlugin(runtime)
await runtime.plugin_manager.load_plugin(oauth)  # ← Слишком поздно!

# Результат: sync_devices() вернёт ошибку "oauth_yandex.get_tokens не найден"
```

### Проверка готовности

```python
# Проверить, что все зависимости загружены
async def ensure_yandex_ready(runtime):
    # 1. Проверить oauth плагин
    oauth_status = runtime.plugin_manager.get_plugin_state("oauth_yandex")
    if not oauth_status["is_started"]:
        raise RuntimeError("oauth_yandex не запущен")
    
    # 2. Проверить real плагин
    yandex_status = runtime.plugin_manager.get_plugin_state("yandex_smart_home_real")
    if not yandex_status["is_started"]:
        raise RuntimeError("yandex_smart_home_real не запущен")
    
    # 3. Проверить наличие access_token
    tokens = await runtime.service_registry.call("oauth_yandex.get_tokens")
    if not tokens or "access_token" not in tokens:
        raise ValueError("OAuth токены не установлены. Авторизуйтесь сначала.")
    
    return True
```

---

## Обработка ошибок

### ✅ Правильная обработка ошибок

```python
async def sync_devices_safely():
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        return {
            "status": "success",
            "count": len(devices),
            "devices": devices,
        }
    
    except ValueError as e:
        # Ошибка валидации (tokenы отсутствуют)
        error_msg = str(e)
        
        if "Токены не найдены" in error_msg:
            return {
                "status": "unauthorized",
                "message": "Сначала авторизуйтесь в Яндексе",
                "action": "redirect_to_oauth",
            }
        
        return {"status": "error", "message": error_msg}
    
    except RuntimeError as e:
        # Ошибка выполнения (API ошибка, сетевая ошибка)
        error_msg = str(e)
        
        if "HTTP 401" in error_msg:
            # Токен истёк
            return {
                "status": "token_expired",
                "message": "Токен истёк. Переавторизуйтесь",
                "action": "redirect_to_oauth",
            }
        
        elif "HTTP 5" in error_msg:
            # Server error (Яндекс недоступен)
            return {
                "status": "api_error",
                "message": "Сервер Яндекса недоступен. Попробуйте позже",
                "retry_after": 300,  # Повторить через 5 минут
            }
        
        elif "Сетевая ошибка" in error_msg:
            # Network error
            return {
                "status": "network_error",
                "message": "Ошибка интернета. Проверьте соединение",
                "retry_after": 60,
            }
        
        return {"status": "error", "message": error_msg}
    
    except Exception as e:
        # Неожиданная ошибка
        return {
            "status": "unknown_error",
            "message": "Неожиданная ошибка",
            "details": str(e),
        }
```

### ❌ Неправильная обработка ошибок

```python
# ✗ Неправильно: игнорирование ошибок
try:
    devices = await runtime.service_registry.call("yandex.sync_devices")
except:
    pass  # ← Ошибка скрывается, пользователь не знает, что произошло

# ✗ Неправильно: слишком общая ошибка
except Exception:
    return "Error"  # ← Невозможно диагностировать проблему

# ✗ Неправильно: retry без верхнего предела
while True:
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        break
    except:
        await asyncio.sleep(1)  # ← Бесконечный retry может заблокировать аккаунт
```

---

## Производительность

### ✅ Асинхронный вызов

```python
# Правильно: асинхронно, не блокирует
async def handle_sync_request():
    devices = await runtime.service_registry.call("yandex.sync_devices")
    
    # Эта операция не блокирует другие запросы
    # runtime может обрабатывать другие запросы параллельно
    
    return devices
```

### ✅ Кеширование

```python
class DeviceCache:
    def __init__(self, ttl_seconds=300):
        self.cache = None
        self.ttl = ttl_seconds
        self.last_sync = None
    
    async def get_devices(self, runtime):
        now = time.time()
        
        # Если кеш свежий, вернуть его
        if self.cache and (now - self.last_sync) < self.ttl:
            return self.cache
        
        # Иначе, синхронизировать заново
        self.cache = await runtime.service_registry.call("yandex.sync_devices")
        self.last_sync = now
        
        return self.cache

# Использование
device_cache = DeviceCache(ttl_seconds=300)
devices = await device_cache.get_devices(runtime)
```

### ✅ Параллельные операции

```python
# Если нужно обработать много устройств, делать это параллельно
async def process_devices_in_batch():
    devices = await runtime.service_registry.call("yandex.sync_devices")
    
    # Обработать в батчах по 10
    batch_size = 10
    for i in range(0, len(devices), batch_size):
        batch = devices[i:i+batch_size]
        
        # Обработать батч параллельно
        await asyncio.gather(
            *[process_device(device) for device in batch]
        )

async def process_device(device):
    # Обработка одного устройства
    await runtime.state_engine.set(
        f"external_device.{device['external_id']}",
        device
    )
```

### ❌ Неправильный подход

```python
# ✗ Синхронный блокирующий вызов
devices = runtime.service_registry.call("yandex.sync_devices")  # ← Без await!
# ← Это вернёт coroutine, а не результат

# ✗ Множественные последовательные вызовы
for i in range(10):
    devices = await runtime.service_registry.call("yandex.sync_devices")
    # ← Каждый вызов ждёт предыдущего (100-500ms * 10)

# ✓ Правильно: параллельные вызовы
results = await asyncio.gather(
    *[runtime.service_registry.call("yandex.sync_devices") for _ in range(10)]
)
```

---

## Безопасность

### ✅ Безопасное управление токенами

```python
# Правильно: токены получаются через oauth_yandex
async def get_devices_securely():
    # 1. Не передавать токены в аргументах
    devices = await runtime.service_registry.call("yandex.sync_devices")
    # ← oauth_yandex.get_tokens() вызывается ВНУТРИ плагина
    
    # 2. Не логировать токены
    # Плагин НЕ логирует access_token
    
    # 3. Real plugin НЕ хранит токены
    # Токены хранятся только в storage через oauth_yandex
    
    return devices
```

### ❌ Небезопасные практики

```python
# ✗ Передача токена явно
devices = await runtime.service_registry.call(
    "yandex.sync_devices",
    access_token="secret_token"  # ← НИКОГДА так не делайте!
)

# ✗ Логирование токена
try:
    devices = await runtime.service_registry.call("yandex.sync_devices")
except Exception as e:
    print(f"Error: {e}")  # ← Может содержать токен в сообщении об ошибке
    logger.error(str(e))

# ✗ Хранение токена в плагине
class BadPlugin:
    async def on_load(self):
        self.access_token = await runtime.service_registry.call(
            "oauth_yandex.get_tokens"
        )  # ← Сохранение токена в плагине
        # Если плагин взломан, токен скомпрометирован
```

### ✅ HTTPS только

```python
# Правильно: real plugin использует HTTPS для API запроса
# В plugins/yandex_smart_home_real.py:
url = "https://api.iot.yandex.net/v1.0/user/devices"
# ← HTTPS защищает access_token при передаче

# Проверить, что используется HTTPS в конфигурации
assert url.startswith("https://"), "Must use HTTPS for API requests"
```

### ✅ Обработка истечения токена

```python
async def handle_token_expiry():
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
    except RuntimeError as e:
        if "HTTP 401" in str(e):
            # Токен истёк
            # Очистить старый токен
            await runtime.service_registry.call(
                "oauth_yandex.set_tokens",
                {}  # Пустой токен
            )
            
            # Перенаправить пользователя на переавторизацию
            raise ValueError("Токен истёк. Переавторизуйтесь")
```

---

## Мониторинг

### ✅ Логирование

```python
async def log_sync_operation():
    start = time.time()
    
    try:
        devices = await runtime.service_registry.call("yandex.sync_devices")
        duration = time.time() - start
        
        # Логировать успех
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"Синхронизация завершена: {len(devices)} устройств",
                context={
                    "duration_ms": int(duration * 1000),
                    "device_count": len(devices),
                }
            )
        except Exception:
            pass
        
        return devices
    
    except Exception as e:
        duration = time.time() - start
        
        # Логировать ошибку
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Ошибка синхронизации: {str(e)}",
                context={
                    "duration_ms": int(duration * 1000),
                    "error": str(e),
                }
            )
        except Exception:
            pass
        
        raise
```

### ✅ Метрики

```python
class YandexSyncMetrics:
    def __init__(self):
        self.total_syncs = 0
        self.successful_syncs = 0
        self.failed_syncs = 0
        self.last_sync_time = None
        self.last_device_count = 0
    
    async def record_sync(self, success, device_count=0, error=None):
        self.total_syncs += 1
        self.last_sync_time = time.time()
        
        if success:
            self.successful_syncs += 1
            self.last_device_count = device_count
        else:
            self.failed_syncs += 1
    
    def get_stats(self):
        return {
            "total_syncs": self.total_syncs,
            "successful": self.successful_syncs,
            "failed": self.failed_syncs,
            "success_rate": self.successful_syncs / max(self.total_syncs, 1),
            "last_device_count": self.last_device_count,
        }

# Использование
metrics = YandexSyncMetrics()

try:
    devices = await runtime.service_registry.call("yandex.sync_devices")
    await metrics.record_sync(success=True, device_count=len(devices))
except Exception as e:
    await metrics.record_sync(success=False, error=str(e))
```

---

## Testing

### ✅ Unit-тестирование с mock

```python
import unittest
from unittest.mock import AsyncMock, patch

class TestYandexRealPlugin(unittest.TestCase):
    
    async def test_sync_devices_with_mock_tokens(self):
        # Setup
        runtime = CoreRuntime(SimpleMemoryStorage())
        
        # Mock oauth_yandex.get_tokens
        async def mock_get_tokens():
            return {"access_token": "fake_token"}
        
        runtime.service_registry.register("oauth_yandex.get_tokens", mock_get_tokens)
        
        # Mock API response
        mock_response = {
            "devices": [
                {
                    "id": "test-device",
                    "type": "devices.types.light",
                    "capabilities": [{"type": "devices.capabilities.on_off"}],
                    "states": [{"type": "devices.capabilities.on_off", "state": {"value": True}}]
                }
            ]
        }
        
        # Load plugin
        plugin = YandexSmartHomeRealPlugin(runtime)
        await runtime.plugin_manager.load_plugin(plugin)
        
        # Test
        with patch("aiohttp.ClientSession") as mock_session:
            # Setup mock
            # ...
            
            devices = await runtime.service_registry.call("yandex.sync_devices")
            
            # Assert
            assert len(devices) == 1
            assert devices[0]["external_id"] == "test-device"
    
    async def test_sync_devices_without_tokens(self):
        # Setup
        runtime = CoreRuntime(SimpleMemoryStorage())
        
        # Mock oauth_yandex.get_tokens (no tokens)
        async def mock_get_tokens():
            return None  # ← Нет токенов
        
        runtime.service_registry.register("oauth_yandex.get_tokens", mock_get_tokens)
        
        # Load plugin
        plugin = YandexSmartHomeRealPlugin(runtime)
        await runtime.plugin_manager.load_plugin(plugin)
        
        # Test
        with self.assertRaises(ValueError) as cm:
            await runtime.service_registry.call("yandex.sync_devices")
        
        # Assert
        assert "Токены не найдены" in str(cm.exception)
```

### ✅ Integration-тестирование

```python
# Для тестирования с реальным API (осторожно!)
async def test_with_real_api():
    runtime = CoreRuntime(storage)
    
    # Установить реальный токен (из переменной окружения)
    import os
    real_token = os.getenv("YANDEX_API_TOKEN")
    if not real_token:
        pytest.skip("YANDEX_API_TOKEN не установлен")
    
    # Установить токен
    await runtime.service_registry.call(
        "oauth_yandex.set_tokens",
        {"access_token": real_token}
    )
    
    # Load plugin
    plugin = YandexSmartHomeRealPlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    
    # Test
    devices = await runtime.service_registry.call("yandex.sync_devices")
    
    # Assert
    assert len(devices) > 0
    assert all("external_id" in d for d in devices)
    assert all("type" in d for d in devices)
```

### ✅ Smoke-тест

```bash
# Используйте существующий smoke-тест
cd core-runtime-service
python smoke_real_yandex_sync.py
```

---

## Чек-лист перед production

### Инициализация
- [ ] Все плагины загружены в правильном порядке
- [ ] logger загружен перед real plugin
- [ ] oauth_yandex загружен перед real plugin
- [ ] devices plugin загружен перед real plugin

### Функциональность
- [ ] yandex.sync_devices() возвращает правильный формат
- [ ] События external.device_discovered публикуются
- [ ] devices_plugin регистрирует устройства
- [ ] automation_plugin может использовать устройства

### Обработка ошибок
- [ ] Обработана ошибка "Токены не найдены"
- [ ] Обработана ошибка "HTTP 401" (токен истёк)
- [ ] Обработана сетевая ошибка
- [ ] Ошибки не скрывают токены

### Безопасность
- [ ] Токены НЕ передаются в параметрах
- [ ] Токены НЕ логируются
- [ ] API запрос использует HTTPS
- [ ] Обработано истечение токена

### Мониторинг
- [ ] Логируются синхронизации
- [ ] Логируются ошибки
- [ ] Собираются метрики
- [ ] Есть возможность диагностики

### Тестирование
- [ ] Smoke-тест проходит
- [ ] Unit-тесты есть
- [ ] Integration-тесты есть
- [ ] Тесты с mock данными
- [ ] Тесты обработки ошибок

---

## Заключение

Следуя этим best practices, вы обеспечите:
- ✅ Надежность
- ✅ Безопасность
- ✅ Производительность
- ✅ Легкость диагностики
- ✅ Простоту расширения

Enjoy! 🚀
