# Архитектура: Stub vs Real Яндекс интеграция

## Обзор

Home Console поддерживает два варианта интеграции с Яндекс Умным Домом:

| Параметр | Stub | Real |
|----------|------|------|
| **Файл** | `yandex_smart_home_stub.py` | `yandex_smart_home_real.py` |
| **Класс** | `YandexSmartHomeStubPlugin` | `YandexSmartHomeRealPlugin` |
| **Источник** | Fake-устройства (hardcoded) | Реальный API Яндекса |
| **API** | `https://api.iot.yandex.net/...` | `https://api.iot.yandex.net/...` |
| **Токены** | Не требуются | От `oauth_yandex` |
| **Управление** | Не поддерживается | Не поддерживается (v0) |
| **Совместимость** | 100% идентична real | 100% идентична stub |

## Архитектурная идея

**Проблема:** 
- При разработке нужны fake-устройства для тестирования
- В production нужны реальные устройства
- Не хочется менять код других плагинов (devices, automation)

**Решение:**
- Оба варианта (stub и real) имеют идентичный API
- Оба публикуют одинаковые события
- Другие плагины работают без изменений
- Достаточно заменить один плагин на другой

## Сравнение интеграции

### Stub-плагин (для разработки)

```
┌─────────────────────────────────────┐
│   Home Console Runtime              │
│                                     │
│  ┌──────────────────────────────┐  │
│  │ yandex_smart_home_stub       │  │
│  │                              │  │
│  │ • Генерирует fake-устройства │  │
│  │ • Не нужны токены            │  │
│  │ • Не нужна сеть              │  │
│  │ • Быстро                     │  │
│  └──────────────────────────────┘  │
│            ↓ (события)              │
│  ┌──────────────────────────────┐  │
│  │ DevicesModule                │  │
│  │ AutomationModule             │  │
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘
```

### Real-плагин (для production)

```
┌──────────────────────────────────────────────┐
│   Home Console Runtime                       │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │ yandex_smart_home_real                 │ │
│  │                                        │ │
│  │ • Получает токены из oauth_yandex      │ │
│  │ • Вызывает Яндекс API                  │ │
│  │ • Преобразует в стандартный формат    │ │
│  │ • Публикует события                    │ │
│  └────────────────────────────────────────┘ │
│                  ↓                          │
│         GET /user/devices                   │
│              ↓                              │
│  ┌────────────────────────────────────────┐ │
│  │   https://api.iot.yandex.net/         │ │
│  │   (Яндекс API)                        │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │ oauth_yandex                           │ │
│  │ (Управление токенами)                  │ │
│  └────────────────────────────────────────┘ │
│            ↓ (события)                      │
│  ┌────────────────────────────────────────┐ │
│  │ DevicesModule                          │ │
│  │ AutomationModule                       │ │
│  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

## API Идентичность

### Сервис

Оба плагина предоставляют **одинаковый сервис:**

```python
devices = await runtime.service_registry.call("yandex.sync_devices")
```

### Возвращаемый формат

Оба возвращают **идентичный формат:**

```python
[
    {
        "provider": "yandex",           # ← Обязателен!
        "external_id": "...",           # ← Стабильный ID
        "type": "light|switch|sensor",  # ← Тип устройства
        "capabilities": [...],          # ← Список возможностей
        "state": {...},                 # ← Состояние
    },
    # ...
]
```

### События

Оба публикуют **идентичное событие:**

```python
# Сигнал
await runtime.event_bus.publish("external.device_discovered", {
    "provider": "yandex",
    "external_id": "...",
    "type": "...",
    "capabilities": [...],
    "state": {...},
})

# Подписчик (DevicesModule)
async def on_device_discovered(event_type: str, data: dict):
    # НЕ интересует, stub это или real
    # Просто регистрирует устройство
    device = Device(external_id=data["external_id"], ...)
```

## Различия

### Источник данных

**Stub:**
```python
devices = [
    {
        "external_id": "yandex-light-kitchen",
        "type": "light",
        "capabilities": ["on_off", "brightness"],
        "state": {"on": True, "brightness": 75},
    },
    # ... (hardcoded)
]
```

**Real:**
```python
# 1. Получить токены
tokens = await runtime.service_registry.call("oauth_yandex.get_tokens")

# 2. Вызвать API
GET https://api.iot.yandex.net/v1.0/user/devices \
    Authorization: Bearer <access_token>

# 3. Преобразовать ответ в стандартный формат
devices = [
    {
        "external_id": "...",
        "type": "...",
        # ...
    }
]
```

### Зависимости

**Stub:**
- Нет зависимостей от других плагинов
- Нет сетевых вызовов
- Самодостаточен

**Real:**
- Зависит от `oauth_yandex` (получение токенов)
- Требует `aiohttp` (HTTP запросы)
- Требует Интернет соединение
- Требует действительный `access_token`

## Переключение между Stub и Real

### Вариант 1: Изменение кода

**Было:**
```python
from plugins.test import YandexSmartHomeStubPlugin

plugin = YandexSmartHomeStubPlugin(runtime)
```

**Стало:**
```python
from plugins.yandex_smart_home import YandexSmartHomeRealPlugin

plugin = YandexSmartHomeRealPlugin(runtime)
```

### Вариант 2: Конфигурация окружения (рекомендуется)

```python
import os
from plugins.test import YandexSmartHomeStubPlugin
from plugins.yandex_smart_home import YandexSmartHomeRealPlugin

YANDEX_MODE = os.getenv("YANDEX_MODE", "stub")  # stub или real

if YANDEX_MODE == "real":
    plugin = YandexSmartHomeRealPlugin(runtime)
else:
    plugin = YandexSmartHomeStubPlugin(runtime)
```

### Вариант 3: Auto-load (если оба загружаются)

Если в `console.py` включен auto-load, оба плагина загружаются автоматически.
В этом случае можно:

1. Не вызывать `sync_devices()` для stub
2. Вызывать `sync_devices()` только для real
3. Остальные плагины не замечают разницы

## Трансформация API Яндекса

### Входной формат (из API Яндекса)

```json
{
  "devices": [
    {
      "id": "yandex-light-kitchen",
      "name": "Свет кухни",
      "type": "devices.types.light",
      "capabilities": [
        {
          "type": "devices.capabilities.on_off",
          "retrievable": true,
          "reportable": true
        },
        {
          "type": "devices.capabilities.range",
          "retrievable": true,
          "reportable": true,
          "parameters": {
            "instance": "brightness",
            "range": { "min": 0, "max": 100 }
          }
        }
      ],
      "states": [
        {
          "type": "devices.capabilities.on_off",
          "state": { "instance": "on", "value": true }
        },
        {
          "type": "devices.capabilities.range",
          "state": { "instance": "brightness", "value": 75 }
        }
      ]
    }
  ]
}
```

### Выходной формат (стандартный)

```python
{
    "provider": "yandex",
    "external_id": "yandex-light-kitchen",     # ← Из "id"
    "type": "light",                            # ← Из "type" (light)
    "capabilities": ["on_off", "range"],        # ← Из "capabilities"
    "state": {
        "on": True,                             # ← Из "states"
        "range": 75
    }
}
```

### Трансформация

| Входное | Выходное | Логика |
|---------|----------|--------|
| `id` | `external_id` | Копирование |
| `type: "devices.types.light"` | `type: "light"` | Последняя часть после точки |
| `capabilities[].type: "devices.capabilities.on_off"` | `capabilities: "on_off"` | Последняя часть после точки |
| `states[].state.value` | `state.on / state.range / ...` | В зависимости от capability |

## Когда использовать Stub vs Real

### Используйте Stub

✅ **Разработка**
- Быстрое тестирование без сети
- Не нужны реальные Яндекс аккаунты
- Предсказуемые fake-данные

✅ **Unit-тесты**
- Изолированное тестирование логики
- Нет зависимостей от внешних сервисов

✅ **Smoke-тесты**
- Быстрая проверка интеграции
- Проверка цепочки событий

### Используйте Real

✅ **Production**
- Реальные устройства пользователя
- Актуальная информация из Яндекса

✅ **Integration-тесты**
- Проверка работы с реальным API
- Проверка обработки ошибок (истечение токена и т.д.)

✅ **Демонстрация**
- Показать работу с настоящими устройствами

## Безопасность

### Stub-плагин

- ✅ Безопасен для любого использования
- ✅ Нет доступа к реальным данным
- ✅ Можно использовать в публичных демонстрациях (без реальных токенов)

### Real-плагин

- ⚠️ Требует действительный `access_token`
- ⚠️ Не хранит токены (для безопасности)
- ⚠️ Требует HTTPS для передачи токена
- ⚠️ Не делает refresh token (в v0)

## Тестирование

### Smoke-тест для Stub

```bash
python smoke_yandex_sync.py
```

### Smoke-тест для Real

```bash
python smoke_real_yandex_sync.py
```

Смотрите `smoke_real_yandex_sync.py` для примеров с mock-данными.

## Расширение (будущее)

### Возможные улучшения

1. **Real-плагин v1:**
   - Управление устройствами (set_device_state)
   - Refresh token
   - Polling / Webhook

2. **Alice интеграция:**
   - Отдельный плагин для управления Алисой
   - Не смешивать с синхронизацией устройств

3. **UI расширения:**
   - Выбор режима (stub vs real) в UI
   - Показ источника данных (stub vs real)

## Заключение

**Ключевая идея:** 
- Stub и Real — **идентичные внешне**
- Разные **только внутри** (источник данных)
- Другие плагины **не замечают разницу**
- Можно переключаться **без изменения кода**

Это позволяет:
- ✅ Разрабатывать быстро (stub)
- ✅ Тестировать безопасно (stub + real)
- ✅ Развертывать в production (real)
- ✅ Переключаться на лету (конфигурация)
