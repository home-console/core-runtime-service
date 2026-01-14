# Client Manager Plugin

Плагин для интеграции Client Manager Service в Core Runtime.

## Режимы работы

Плагин поддерживает два режима работы, которые выбираются через переменную окружения `CLIENT_MANAGER_MODE`:

### 1. Standalone режим (по умолчанию)

Запускает Client Manager как отдельный FastAPI сервер на порту 10000.

**Преимущества:**
- Полная изоляция от основного API
- Независимая конфигурация и масштабирование
- Не конфликтует с основными роутами

**Использование:**
```bash
export CLIENT_MANAGER_MODE=standalone
# или не указывать (standalone по умолчанию)
```

**Endpoints:**
- REST API: `http://localhost:10000/api/*`
- WebSocket: `ws://localhost:10000/ws`
- Admin WebSocket: `ws://localhost:10000/admin/ws`

### 2. Integrated режим

Монтирует роуты Client Manager в основной API (порт 8000).

**Преимущества:**
- Единая точка входа для всех API
- Общая аутентификация и авторизация
- Упрощённая архитектура

**Использование:**
```bash
export CLIENT_MANAGER_MODE=integrated
```

**Endpoints:**
- REST API: `http://localhost:8000/api/client-manager/*`
- WebSocket: `ws://localhost:8000/ws` (или настраиваемый префикс)
- Admin WebSocket: `ws://localhost:8000/admin/ws` (или настраиваемый префикс)

## Конфигурация

Плагин поддерживает два способа конфигурации (в порядке приоритета):

### 1. Через Storage API ядра (рекомендуется)

Конфигурация хранится в `runtime.storage` (namespace: `plugin_config`, key: `client_manager`).

**Преимущества:**
- Управление через компоненты ядра (соответствует архитектуре)
- Персистентность между перезапусками
- Единая точка управления конфигурацией

**Структура конфигурации:**
```json
{
  "mode": "integrated",
  "host": "0.0.0.0",
  "port": "10000",
  "ws_prefix": "/client-manager"
}
```

**Установка через Storage API:**
```python
# Через сервис или напрямую
await runtime.storage.set("plugin_config", "client_manager", {
    "mode": "integrated",
    "ws_prefix": "/client-manager"
})
```

**Пример через Admin API:**
```bash
# Установить режим integrated через storage
curl -X POST http://localhost:8000/api/admin/v1/storage/set \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "plugin_config",
    "key": "client_manager",
    "value": {
      "mode": "integrated",
      "ws_prefix": "/client-manager"
    }
  }'
```

**Параметры конфигурации:**
- `mode` - режим работы: `"integrated"` или `"standalone"` (по умолчанию: `"standalone"`)
- `host` - хост для standalone режима (по умолчанию: `"0.0.0.0"`)
- `port` - порт для standalone режима (по умолчанию: `"10000"`)
- `ws_prefix` - префикс для WebSocket endpoints в integrated режиме (по умолчанию: `""`)

### 2. Через переменные окружения (fallback)

Если конфигурация в storage отсутствует, используется fallback на переменные окружения.

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `CLIENT_MANAGER_MODE` | Режим работы: `integrated` или `standalone` | `standalone` |
| `CLIENT_MANAGER_HOST` | Хост для standalone режима | `0.0.0.0` |
| `CLIENT_MANAGER_PORT` | Порт для standalone режима | `10000` |
| `CLIENT_MANAGER_WS_PREFIX` | Префикс для WebSocket endpoints в integrated режиме | (без префикса) |

### Примеры конфигурации

**Standalone режим с кастомным портом:**
```bash
export CLIENT_MANAGER_MODE=standalone
export CLIENT_MANAGER_PORT=10001
```

**Integrated режим с префиксом для WebSocket:**
```bash
export CLIENT_MANAGER_MODE=integrated
export CLIENT_MANAGER_WS_PREFIX=/client-manager
# WebSocket будет доступен на /client-manager/ws
```

## Архитектура

### Standalone режим

```
┌─────────────────┐
│  Core Runtime   │
│   (порт 8000)   │
└─────────────────┘
         │
         │ HTTP API
         │
┌─────────────────┐
│ Client Manager  │
│  (порт 10000)   │
└─────────────────┘
```

### Integrated режим

```
┌─────────────────────────────────┐
│      Core Runtime               │
│       (порт 8000)               │
│                                 │
│  ┌──────────────────────────┐  │
│  │   Основные API роуты      │  │
│  └──────────────────────────┘  │
│  ┌──────────────────────────┐  │
│  │  Client Manager роуты    │  │
│  │  /api/client-manager/*  │  │
│  └──────────────────────────┘  │
│  ┌──────────────────────────┐  │
│  │  Client Manager WebSocket│  │
│  │  /ws, /admin/ws         │  │
│  └──────────────────────────┘  │
└─────────────────────────────────┘
```

## Запуск

### Базовый запуск

Плагин загружается автоматически из каталога `plugins/client_manager/`. Просто запустите Core Runtime:

```bash
python main.py
```

### ⚙️ Выбор режима работы

Режим работы выбирается через переменную окружения `CLIENT_MANAGER_MODE`:

#### 1. Integrated режим (рекомендуется) - всё на одном порту

```bash
# Установить режим интеграции
export CLIENT_MANAGER_MODE=integrated

# Запустить Core Runtime
python main.py
```

**Результат:**
- ✅ Всё на одном порту: `http://localhost:8000`
- ✅ Основной API: `http://localhost:8000/api/*`
- ✅ Client Manager REST API: `http://localhost:8000/api/client-manager/*`
- ✅ Client Manager WebSocket: `ws://localhost:8000/ws`
- ✅ Admin WebSocket: `ws://localhost:8000/admin/ws`

**Или через .env файл:**
```bash
# Создать/отредактировать .env в корне проекта
echo "CLIENT_MANAGER_MODE=integrated" >> .env
python main.py
```

#### 2. Standalone режим (по умолчанию) - отдельный порт

```bash
# Вариант 1: Без явного указания (standalone по умолчанию)
python main.py

# Вариант 2: Явное указание режима
export CLIENT_MANAGER_MODE=standalone
python main.py

# Вариант 3: С кастомным портом
export CLIENT_MANAGER_MODE=standalone
export CLIENT_MANAGER_PORT=10001
python main.py
```

**Результат:**
- Основной API: `http://localhost:8000`
- Client Manager API: `http://localhost:10000/api/*`
- Client Manager WebSocket: `ws://localhost:10000/ws`

### Настройка WebSocket префикса (только для integrated режима)

Если нужно изменить пути WebSocket endpoints в integrated режиме:

```bash
export CLIENT_MANAGER_MODE=integrated
export CLIENT_MANAGER_WS_PREFIX=/client-manager
python main.py
```

**Результат:**
- Client Manager WebSocket: `ws://localhost:8000/client-manager/ws`
- Admin WebSocket: `ws://localhost:8000/client-manager/admin/ws`

### Проверка работы

После запуска проверьте логи:

```bash
# Должно быть сообщение:
# [INFO] Client Manager запущен на 0.0.0.0:10000 (standalone режим)
# или
# [INFO] Client Manager интегрирован в основной API (integrated режим)
```

Проверьте endpoints:

```bash
# Standalone режим
curl http://localhost:10000/api/clients

# Integrated режим
curl http://localhost:8000/api/client-manager/clients
```

## Выбор режима

**Используйте standalone режим, если:**
- Нужна полная изоляция Client Manager
- Требуется независимое масштабирование
- Есть конфликты с основными роутами

**Используйте integrated режим, если:**
- Нужна единая точка входа для всех API
- Требуется общая аутентификация
- Хотите упростить архитектуру

## Миграция между режимами

Переключение между режимами не требует изменений в коде клиентов, только изменение переменной окружения `CLIENT_MANAGER_MODE`. Однако:

- В standalone режиме endpoints доступны на порту 10000
- В integrated режиме REST API endpoints имеют префикс `/api/client-manager`
- WebSocket endpoints могут иметь настраиваемый префикс через `CLIENT_MANAGER_WS_PREFIX`
