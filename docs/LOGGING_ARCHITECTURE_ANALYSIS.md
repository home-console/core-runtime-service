# Анализ архитектуры логирования

**Дата**: 2026-01-16  
**Статус**: Требует обсуждения и рефакторинга

## Резюме

Текущая архитектура логирования имеет несколько проблем:
1. **Избыточное логирование** - фронтенд отправляет каждый запрос на `/admin/v1/request-logs/log`, создавая дополнительные запросы
2. **Не видно исходящих запросов** - исходящие запросы логируются, но могут не иметь правильного `request_id`
3. **Смешение целей** - нет четкого разделения между логами для консоли и логами для UI

## Текущее состояние

### Проблемы

1. **Избыточное логирование**
   - Фронтенд отправляет каждый HTTP запрос на `/admin/v1/request-logs/log`
   - Это создает дополнительные запросы (видно в логах: `POST /admin/v1/request-logs/log`)
   - Двойное логирование: фронтенд логирует свои запросы, бэкенд тоже логирует через middleware

2. **Не видно исходящих запросов**
   - Исходящие запросы логируются через `request_logger.create_http_session`
   - Но они могут не иметь правильного `request_id` (если запрос не в контексте HTTP запроса)
   - Логи могут не отображаться в UI или в консоли

3. **Смешение целей логирования**
   - Нет четкого разделения между:
     - Логами в консоль (stdout) - для разработчиков
     - Логами в request_logger - для UI и отладки
     - Логами в файл - для продакшена

## Архитектура

### Компоненты

#### 1. LoggerModule (`modules/logger/module.py`)
- **Назначение**: Централизованное логирование в stdout
- **Формат**: Простой текст `[LEVEL] [plugin] message (context)`
- **Использование**: Прямой `print()` в stdout (не через logging)
- **Сервис**: `logger.log(level, message, **context)`

**Проблемы**:
- Дублирует логи в `request_logger` (если есть `request_id`)
- Нет фильтрации по источнику
- Все логи идут в stdout, даже если они уже в request_logger

#### 2. RequestLoggerModule (`modules/request_logger/module.py`)
- **Назначение**: Хранение логов каждого HTTP запроса с привязкой к `request_id`
- **Хранение**: В памяти (последние 1000 запросов)
- **Сервисы**:
  - `request_logger.log(request_id, level, message, **context)`
  - `request_logger.get_request_logs(request_id)`
  - `request_logger.list_requests(limit, offset)`
  - `request_logger.create_http_session(source)` - обёртка над aiohttp для логирования исходящих запросов

**Проблемы**:
- Исходящие запросы могут не иметь `request_id` (если не в контексте HTTP запроса)
- Логи хранятся только в памяти (теряются при перезапуске)
- Нет персистентности

#### 3. RequestLoggerMiddleware (`modules/request_logger/middleware.py`)
- **Назначение**: Перехват HTTP запросов и автоматическое логирование
- **Функции**:
  - Генерация `request_id` для каждого запроса
  - Захват метаданных запроса/ответа (headers, body)
  - Сохранение в `request_logger`

**Проблемы**:
- Логирует все запросы, включая `/admin/v1/request-logs/log` (хотя есть проверка)
- Дублирует логирование с фронтендом

#### 4. LoggedClientSession (`modules/request_logger/http_client.py`)
- **Назначение**: Обёртка над `aiohttp.ClientSession` для логирования исходящих запросов
- **Механизм**: Использует `aiohttp.TraceConfig` для перехвата запросов
- **Логирование**:
  - В `request_logger` (с `request_id`)
  - В `logger` (в stdout)

**Проблемы**:
- Если запрос не в контексте HTTP запроса, `request_id` может быть случайным UUID
- Двойное логирование (в `request_logger` и `logger`)

#### 5. Frontend Logging (`admin-ui-service/src/api/http.ts`)
- **Назначение**: Логирование HTTP запросов с фронтенда
- **Механизм**: Отправка логов на `/admin/v1/request-logs/log`
- **Проблемы**:
  - Создает дополнительные HTTP запросы
  - Дублирует логирование с бэкенд middleware
  - Может создавать рекурсию (логирование запроса на логирование)

## Потоки данных

### Входящий HTTP запрос

```
1. HTTP Request → RequestLoggerMiddleware
   ├─ Генерирует request_id
   ├─ Захватывает метаданные запроса
   └─ Логирует в request_logger

2. RequestLoggerMiddleware → Handler
   └─ Выполняет запрос

3. Handler → LoggerModule (если вызывает logger.log)
   ├─ Выводит в stdout
   └─ Дублирует в request_logger (если есть request_id)

4. Handler → LoggedClientSession (если делает исходящий запрос)
   ├─ Логирует в request_logger (с request_id)
   └─ Логирует в logger (в stdout)

5. Response → RequestLoggerMiddleware
   ├─ Захватывает метаданные ответа
   └─ Сохраняет в request_logger

6. Frontend → POST /admin/v1/request-logs/log
   └─ Дублирует логирование (если фронтенд тоже логирует)
```

### Исходящий HTTP запрос (не в контексте HTTP запроса)

```
1. Plugin → LoggedClientSession
   ├─ Генерирует случайный request_id (если нет контекста)
   ├─ Логирует в request_logger
   └─ Логирует в logger (в stdout)

2. Проблема: request_id не связан с HTTP запросом
   └─ Логи могут не отображаться в UI правильно
```

## Рекомендации

### 1. Разделение ответственности

**LoggerModule** (stdout):
- Только важные события (errors, warnings, key info)
- Не дублировать логи из request_logger
- Фильтрация по уровню через `LOG_LEVEL`

**RequestLoggerModule** (UI/отладка):
- Все детали запросов (для отладки)
- Полные метаданные (headers, body, timing)
- Привязка к `request_id`

### 2. Убрать двойное логирование

**Вариант A**: Фронтенд не логирует, только бэкенд
- Убрать `sendLogToBackend` из `http.ts`
- Бэкенд middleware логирует все входящие запросы

**Вариант B**: Фронтенд логирует только свои запросы, бэкенд - свои
- Фронтенд логирует только запросы к внешним API (если есть)
- Бэкенд логирует все свои запросы

**Рекомендация**: Вариант A (бэкенд логирует все)

### 3. Улучшить логирование исходящих запросов

**Проблема**: Исходящие запросы могут не иметь правильного `request_id`

**Решение**:
- Использовать `contextvars` для передачи `request_id` через async контекст
- Если нет `request_id`, создавать отдельный "outgoing request" с собственным ID
- В UI показывать исходящие запросы отдельно или привязанными к входящим

### 4. Оптимизация производительности

**Проблема**: Много запросов на `/admin/v1/request-logs/log`

**Решение**:
- Батчинг: собирать логи и отправлять пачками
- Throttling: ограничить частоту отправки
- Или убрать фронтенд логирование полностью

### 5. Персистентность

**Проблема**: Логи теряются при перезапуске

**Решение**:
- Опциональное сохранение в БД (SQLite/PostgreSQL)
- Ротация логов (удаление старых)
- Экспорт в файл

## Предлагаемая архитектура

### Упрощенная схема

```
HTTP Request
    ↓
RequestLoggerMiddleware (захватывает request_id, метаданные)
    ↓
Handler
    ├─→ LoggerModule (только важные события в stdout)
    └─→ LoggedClientSession (исходящие запросы)
        ├─→ RequestLoggerModule (детальные логи с request_id)
        └─→ LoggerModule (только ошибки в stdout)
    ↓
Response
    ↓
RequestLoggerMiddleware (сохраняет метаданные ответа)
```

### Правила логирования

1. **LoggerModule (stdout)**:
   - Только `ERROR`, `WARNING`, ключевые `INFO`
   - Не дублировать логи из request_logger
   - Формат: `[LEVEL] [plugin] message`

2. **RequestLoggerModule (UI)**:
   - Все детали запросов
   - Полные метаданные
   - Привязка к `request_id`

3. **Исходящие запросы**:
   - Всегда логировать в request_logger
   - В logger только ошибки
   - Привязка к `request_id` родительского запроса (если есть)

## Примеры проблем

### Пример 1: Избыточные запросы

**Ситуация**: Пользователь делает 2 действия (например, проверка статуса OAuth)

**Логи**:
```
INFO: GET /oauth/yandex/status HTTP/1.1" 200 OK
INFO: POST /admin/v1/request-logs/log HTTP/1.1" 200 OK  ← лишний запрос
INFO: GET /oauth/yandex/status HTTP/1.1" 200 OK
INFO: POST /admin/v1/request-logs/log HTTP/1.1" 200 OK  ← лишний запрос
```

**Проблема**: Каждый запрос с фронтенда создает дополнительный запрос на логирование

**Решение**: Убрать фронтенд логирование, бэкенд middleware уже логирует все

### Пример 2: Исходящие запросы без request_id

**Ситуация**: OAuth плагин делает запрос к Яндекс API вне контекста HTTP запроса

**Код**:
```python
# В oauth_yandex/plugin.py
session = await self._get_http_session()  # Использует request_logger.create_http_session
async with session.post(TOKEN_ENDPOINT, data=data) as resp:
    ...
```

**Проблема**: 
- `get_request_id()` возвращает `None` (нет HTTP контекста)
- Создается случайный UUID: `trace_config_ctx.request_id = str(uuid.uuid4())`
- Логи не привязаны к родительскому запросу

**Решение**: 
- Использовать отдельный тип запроса "outgoing" без привязки к HTTP
- Или передавать `request_id` явно через параметры

### Пример 3: Двойное логирование

**Ситуация**: OAuth плагин логирует запрос дважды

**Логи**:
```
[INFO] [oauth_yandex] OAuth exchange_code request: POST https://oauth.yandex.ru/token
[INFO] [oauth_yandex] Outgoing HTTP POST https://oauth.yandex.ru/token
[INFO] [oauth_yandex] Outgoing HTTP POST https://oauth.yandex.ru/token -> HTTP 200
[INFO] [oauth_yandex] OAuth exchange_code response: POST https://oauth.yandex.ru/token -> HTTP 200
```

**Проблема**: 
- Явное логирование в `oauth_yandex/plugin.py` (строки 1 и 4)
- Автоматическое логирование через `LoggedClientSession` (строки 2 и 3)

**Решение**: 
- Убрать явное логирование, оставить только автоматическое
- Или убрать автоматическое логирование в stdout, оставить только в request_logger

## Вопросы для обсуждения

1. **Нужно ли фронтенд логирование?**
   - Если да, то как избежать дублирования?
   - Если нет, то как убрать без потери функциональности?

2. **Как показывать исходящие запросы в UI?**
   - Отдельный список?
   - Привязанные к входящим запросам?
   - Фильтр по направлению (incoming/outgoing)?

3. **Нужна ли персистентность логов?**
   - Если да, то в БД или файл?
   - Как долго хранить?
   - Ротация?

4. **Как оптимизировать производительность?**
   - Батчинг логов?
   - Throttling?
   - Асинхронная запись?

5. **Уровни логирования для stdout?**
   - Только ERROR/WARNING?
   - Или включать INFO для ключевых событий?

## Метрики для мониторинга

- Количество запросов на `/admin/v1/request-logs/log`
- Размер памяти для request_logger
- Количество логов в stdout
- Время обработки запросов логирования
