# Версионирование API

> **Статус:** Stable (v0.2.0)  
> **Версия документа:** 1.0

---

## Обзор

Core Runtime поддерживает версионирование API для сервисов и HTTP endpoints. Это позволяет:
- Поддерживать несколько версий API одновременно
- Плавно мигрировать клиентов на новые версии
- Помечать устаревшие версии как deprecated
- Удалять старые версии после периода deprecation

---

## Стратегия версионирования

### Принципы

1. **Семантическое версионирование**: Используйте формат `v1`, `v2`, `v3` и т.д.
2. **Обратная совместимость**: Старые версии остаются доступными до полного удаления
3. **Deprecation период**: Устаревшие версии помечаются как deprecated и остаются доступными минимум 6 месяцев
4. **Миграция**: Клиенты должны мигрировать на новые версии в течение deprecation периода

### Поддержка нескольких версий

Core Runtime позволяет регистрировать несколько версий одного сервиса или endpoint одновременно:

```python
# Регистрация v1
await service_registry.register("devices.list", list_devices_v1, version="v1")

# Регистрация v2 (новая версия с улучшениями)
await service_registry.register("devices.list", list_devices_v2, version="v2")

# Обе версии доступны одновременно
result_v1 = await service_registry.call("devices.list.v1")
result_v2 = await service_registry.call("devices.list.v2")
```

---

## Версионирование сервисов (ServiceRegistry)

### Регистрация версионированного сервиса

```python
async def list_devices_v1(runtime):
    """Версия 1 - старый формат ответа."""
    return {"devices": [...]}

async def list_devices_v2(runtime):
    """Версия 2 - новый формат ответа с метаданными."""
    return {
        "data": [...],
        "meta": {"total": 10, "page": 1}
    }

# Регистрация обеих версий
await runtime.service_registry.register("devices.list", list_devices_v1, version="v1")
await runtime.service_registry.register("devices.list", list_devices_v2, version="v2")
```

### Вызов версионированного сервиса

```python
# Вызов v1
result_v1 = await runtime.service_registry.call("devices.list.v1")

# Вызов v2
result_v2 = await runtime.service_registry.call("devices.list.v2")
```

### Проверка доступных версий

```python
# Получить список всех версий сервиса
versions = await runtime.service_registry.get_versions("devices.list")
# Вернёт: ["v1", "v2"]
```

### Пометить версию как deprecated

```python
# Пометить v1 как устаревшую
await runtime.service_registry.mark_deprecated("devices.list", "v1")

# Проверить, является ли версия deprecated
is_deprecated = await runtime.service_registry.is_deprecated("devices.list", "v1")
# Вернёт: True
```

---

## Версионирование HTTP endpoints (HttpRegistry)

### Регистрация версионированного endpoint

```python
from core.http_registry import HttpEndpoint

# Регистрация v1
runtime.http.register(HttpEndpoint(
    method="GET",
    path="/devices",
    service="devices.list",
    description="Список устройств (v1)",
    version="v1"
))

# Регистрация v2
runtime.http.register(HttpEndpoint(
    method="GET",
    path="/devices",
    service="devices.list",
    description="Список устройств (v2) - улучшенный формат",
    version="v2"
))
```

### Автоматическое добавление версии к пути

HttpRegistry автоматически добавляет версию к пути:
- `path="/devices"` + `version="v1"` → `/v1/devices`
- `path="/devices"` + `version="v2"` → `/v2/devices`

### Проверка доступных версий

```python
# Получить список всех версий endpoint
versions = runtime.http.get_versions("devices.list")
# Вернёт: ["v1", "v2"]
```

### Пометить версию как deprecated

```python
# Пометить v1 как устаревшую
runtime.http.mark_deprecated("devices.list", "v1")

# Проверить, является ли версия deprecated
is_deprecated = runtime.http.is_deprecated("devices.list", "v1")
# Вернёт: True
```

### Deprecated endpoints в OpenAPI

При генерации OpenAPI схемы, deprecated endpoints автоматически помечаются:
- Добавляется поле `"deprecated": true`
- В summary добавляется префикс `[DEPRECATED]`

---

## Стратегия миграции версий

### Этап 1: Введение новой версии

1. Реализуйте новую версию сервиса/endpoint
2. Зарегистрируйте новую версию параллельно со старой
3. Протестируйте новую версию
4. Обновите документацию

```python
# Старая версия уже существует
await service_registry.register("devices.list", list_devices_v1, version="v1")

# Добавляем новую версию
await service_registry.register("devices.list", list_devices_v2, version="v2")
```

### Этап 2: Deprecation старой версии

1. Пометите старую версию как deprecated
2. Уведомите клиентов о необходимости миграции
3. Обновите документацию с предупреждением

```python
# Помечаем v1 как deprecated
await service_registry.mark_deprecated("devices.list", "v1")

# Уведомляем клиентов через логирование или метрики
await runtime.service_registry.call(
    "logger.log",
    level="warning",
    message="devices.list.v1 is deprecated, migrate to v2",
    module="api"
)
```

### Этап 3: Период deprecation (минимум 6 месяцев)

1. Старая версия остаётся доступной
2. Мониторьте использование старой версии
3. Помогайте клиентам мигрировать на новую версию

### Этап 4: Удаление старой версии

1. Убедитесь, что все клиенты мигрировали
2. Удалите старую версию из кода
3. Обновите документацию

```python
# Удаляем старую версию
await service_registry.unregister("devices.list.v1")
```

---

## Best Practices

### 1. Всегда указывайте версию явно

```python
# ✅ Хорошо: явная версия
await service_registry.register("devices.list", handler, version="v1")

# ❌ Плохо: неявная версия (может привести к конфликтам)
await service_registry.register("devices.list", handler)
```

### 2. Используйте семантическое версионирование

```python
# ✅ Хорошо: v1, v2, v3
version="v1"

# ❌ Плохо: нестандартные форматы
version="1.0"
version="alpha"
version="beta"
```

### 3. Документируйте изменения между версиями

```python
async def list_devices_v2(runtime):
    """
    Версия 2 списка устройств.
    
    Изменения по сравнению с v1:
    - Добавлены метаданные (total, page)
    - Изменён формат ответа (data вместо devices)
    - Добавлена поддержка пагинации
    
    Migration guide: см. docs/MIGRATION_V1_TO_V2.md
    """
    ...
```

### 4. Мониторьте использование deprecated версий

```python
# В middleware или logging
if await service_registry.is_deprecated(service_name, version):
    await log_deprecated_usage(service_name, version, client_id)
```

### 5. Предоставляйте migration guide

Создавайте документацию по миграции между версиями:
- Что изменилось
- Как обновить код клиента
- Примеры миграции
- Временные рамки

---

## Примеры использования

### Пример 1: Простое версионирование сервиса

```python
# Плагин регистрирует две версии сервиса
class DevicesPlugin(BasePlugin):
    async def on_start(self):
        # v1 - старый формат
        async def list_v1():
            return {"devices": [...]}
        
        # v2 - новый формат
        async def list_v2():
            return {
                "data": [...],
                "meta": {"total": 10}
            }
        
        await self.runtime.service_registry.register(
            "devices.list", list_v1, version="v1"
        )
        await self.runtime.service_registry.register(
            "devices.list", list_v2, version="v2"
        )
```

### Пример 2: Версионирование HTTP endpoint

```python
# Регистрация двух версий endpoint
runtime.http.register(HttpEndpoint(
    method="GET",
    path="/devices",
    service="devices.list",
    version="v1",
    description="Список устройств (v1 - deprecated)"
))

runtime.http.register(HttpEndpoint(
    method="GET",
    path="/devices",
    service="devices.list",
    version="v2",
    description="Список устройств (v2 - recommended)"
))

# Помечаем v1 как deprecated
runtime.http.mark_deprecated("devices.list", "v1")
```

### Пример 3: Проверка версий перед вызовом

```python
# Проверяем доступные версии
versions = await service_registry.get_versions("devices.list")
if "v2" in versions:
    # Используем новую версию
    result = await service_registry.call("devices.list.v2")
else:
    # Fallback на старую версию
    result = await service_registry.call("devices.list.v1")
```

---

## Ограничения

1. **Нет автоматической миграции**: Клиенты должны вручную обновлять код для использования новых версий
2. **Нет автоматического удаления**: Deprecated версии не удаляются автоматически, требуется ручное удаление
3. **Нет метрик использования**: Core Runtime не отслеживает использование версий автоматически (можно добавить через middleware)

---

## См. также

- [Core Runtime Contract](04-CORE-RUNTIME-CONTRACT.md) - общий контракт Core Runtime
- [Service Registry](core/service_registry.py) - реализация ServiceRegistry
- [HTTP Registry](core/http_registry.py) - реализация HttpRegistry
