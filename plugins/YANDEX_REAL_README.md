# yandex_smart_home_real_v0 Plugin

## Описание

Плагин **yandex_smart_home_real_v0** синхронизирует реальные устройства из API Яндекса в Home Console.

**Архитектура:**
- Plugin-first, in-process
- Получает токены через `oauth_yandex.get_tokens()`
- НЕ хранит токены (только использует)
- НЕ знает OAuth деталей
- Полностью совместим со stub-плагином `yandex_smart_home_stub`

## Функциональность

### Сервис: `yandex.sync_devices()`

Синхронизирует устройства из реального API Яндекса.

**Что происходит:**

1. Получает `access_token` через `oauth_yandex.get_tokens()`
2. Выполняет HTTP GET запрос к `https://api.iot.yandex.net/v1.0/user/devices`
3. Преобразует каждое устройство в стандартный формат
4. Публикует событие `external.device_discovered` для каждого устройства
5. Возвращает список преобразованных устройств

**Пример использования:**

```python
devices = await runtime.service_registry.call("yandex.sync_devices")
```

**Возвращает:**

```python
[
    {
        "provider": "yandex",
        "external_id": "yandex-light-kitchen",
        "type": "light",
        "capabilities": ["on_off", "brightness"],
        "state": {"on": True, "brightness": 75},
    },
    # ...
]
```

## События

### Событие: `external.device_discovered`

Публикуется для каждого устройства, полученного из API.

**Payload:**

```python
{
    "provider": "yandex",
    "external_id": "<id>",
    "type": "<light|switch|sensor|climate|...>",
    "capabilities": ["on_off", "brightness", ...],
    "state": { ... }
}
```

**Подписчики:**

- `devices_plugin` — регистрирует внешние устройства
- `automation_plugin` — может использовать для автоматизации

## Требования

### Зависимости:

1. **oauth_yandex** — плагин для OAuth авторизации
   - Должен быть загружен и авторизован перед вызовом `sync_devices()`
   - Должен содержать действительный `access_token`

2. **aiohttp** — для HTTP запросов
   - Должен быть установлен в окружении

### Окружение:

- Python 3.10+
- asyncio

## Примеры использования

### Пример 1: Загрузка плагина и синхронизация

```python
from plugins.yandex_smart_home_real import YandexSmartHomeRealPlugin
from core.runtime import CoreRuntime

async def main():
    runtime = CoreRuntime(storage)
    
    # Загрузить и запустить плагин
    plugin = YandexSmartHomeRealPlugin(runtime)
    await runtime.plugin_manager.load_plugin(plugin)
    await runtime.plugin_manager.start_plugin(plugin.metadata.name)
    
    # Синхронизировать устройства
    devices = await runtime.service_registry.call("yandex.sync_devices")
    print(f"Синхронизировано {len(devices)} устройств")
```

### Пример 2: Подписка на события об обнаружении

```python
async def on_device_discovered(event_type: str, data: dict):
    print(f"Обнаружено устройство: {data['external_id']}")
    print(f"  Тип: {data['type']}")
    print(f"  Возможности: {data['capabilities']}")

runtime.event_bus.subscribe("external.device_discovered", on_device_discovered)

# Синхронизировать устройства (это опубликует события)
await runtime.service_registry.call("yandex.sync_devices")
```

## Обработка ошибок

### Нет токенов

```python
ValueError: Токены не найдены или access_token отсутствует. 
            Сначала авторизуйтесь через oauth_yandex.
```

**Решение:** Авторизуйтесь через OAuth перед вызовом `sync_devices()`.

### Ошибка API Яндекса

```python
RuntimeError: Ошибка Яндекс API: HTTP 401 — Unauthorized
```

**Возможные причины:**
- Токен истёк
- Токен неверный
- Доступ запрещен

**Решение:** Переавторизуйтесь.

### Нет сетевого соединения

```python
RuntimeError: Сетевая ошибка при запросе к Яндекс API: ...
```

**Решение:** Проверьте интернет соединение.

## Совместимость со stub-плагином

Плагин полностью совместим с `yandex_smart_home_stub`:

1. **API идентичен:**
   - Оба предоставляют сервис `yandex.sync_devices()`
   - Оба публикуют событие `external.device_discovered`

2. **Формат устройств идентичен:**
   - Оба используют один и тот же формат payload
   - Можно заменить stub на real без изменения других плагинов

3. **Взаимодействие с другими плагинами:**
   - `devices_plugin` не отличает stub от real
   - `automation_plugin` не отличает stub от real

## Ограничения

**НЕ реализовано:**
- ❌ Управление устройствами (set_device_state)
- ❌ Интеграция с Алисой
- ❌ Refresh token
- ❌ Polling / Retry
- ❌ Webhooks / Callbacks
- ❌ Хранение состояния устройств

**Это разработано намеренно** для соблюдения принципа разделения ответственности. 

Для управления устройствами используйте отдельный плагин.

## Архитектурные принципы

1. **Plugin-first:** Плагин самостоятельный, не знает о других системах
2. **In-process:** Выполняется в том же процессе, что и runtime
3. **Event-driven:** Общается через event_bus
4. **Service-driven:** Регистрирует сервисы через service_registry
5. **Stateless:** НЕ хранит состояние (кроме конфигурации через oauth_yandex)
6. **Minimal API:** Предоставляет только необходимое

## Отладка

### Включить логирование

Плагин использует сервис `logger.log` для логирования. Если у вас загружен `system_logger_plugin`, логи будут выводиться в stdout:

```
{"level": "info", "message": "yandex_smart_home_real_v0 запущен", ...}
```

### Проверить статус

```python
plugins = runtime.plugin_manager.list_plugins()
if "yandex_smart_home_real" in plugins:
    state = runtime.plugin_manager.get_plugin_state("yandex_smart_home_real")
    print(f"Плагин загружен: {state['is_loaded']}")
    print(f"Плагин запущен: {state['is_started']}")
```

## Testing

Для тестирования используйте mock-токены:

```python
async def mock_get_tokens():
    return {"access_token": "fake_token_for_testing"}

runtime.service_registry.register("oauth_yandex.get_tokens", mock_get_tokens)
```

Примеры mock-тестов см. в `smoke_real_yandex_sync.py`.

## Лицензия

MIT
