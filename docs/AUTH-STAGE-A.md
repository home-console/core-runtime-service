# API Key Authentication — Stage A

> **Статус:** Реализовано (Stage A)  
> **Версия:** 1.0  
> **Архитектурный принцип:** Boundary-layer authentication

---

## Обзор

API Key authentication реализован как **boundary-layer** на уровне HTTP (ApiModule и AdminModule). 

**Ключевой принцип:**
- ✅ Auth логика **НЕ проникает** в CoreRuntime, RuntimeModule, ServiceRegistry или доменные модули
- ✅ Всё изолировано на уровне HTTP boundary
- ✅ Доменные модули (devices, automation, presence) **НЕ знают** про auth
- ✅ ServiceRegistry **НЕ изменён** — сигнатуры сервисов остались прежними

---

## Архитектура

### Boundary-Layer

```
HTTP Request
    ↓
[ApiModule Middleware] ← validate_api_key(), RequestContext
    ↓
[ApiModule Handler] ← check_service_scope()
    ↓
[ServiceRegistry.call()] ← НЕ знает про auth
    ↓
[Domain Modules] ← НЕ знают про auth
```

### RequestContext

Контекст авторизации передаётся через `request.state.auth_context` (FastAPI):

```python
@dataclass
class RequestContext:
    subject: str      # "api_key:key_id"
    scopes: List[str] # ["devices.read", "devices.write"]
    is_admin: bool    # True для администраторов
    source: str       # "api_key"
```

---

## Использование

### 1. Хранение API Keys

API keys хранятся в `runtime.storage` namespace `"auth_api_keys"`:

```python
# Структура данных ключа
key_data = {
    "subject": "api_key:my_key_123",
    "scopes": ["devices.read", "devices.write", "automation.*"],
    "is_admin": False
}

# Сохранение
await runtime.storage.set("auth_api_keys", "actual_api_key_string", key_data)
```

### 2. HTTP Request с API Key

```bash
curl -H "Authorization: Bearer <api_key>" \
     http://localhost:8000/api/devices/list
```

### 3. Проверка прав

Правила проверки scopes:

- **Администраторы** (`is_admin=True`) → полный доступ ко всем сервисам
- **Административные сервисы** (`admin.*`) → требуют `is_admin=True`
- **Обычные сервисы** → проверка scopes:
  - `"namespace.action"` (точное совпадение)
  - `"namespace.*"` (все действия в namespace)
  - `"*"` (все действия)

**Примеры:**

| Service Name | Required Scope | Примеры |
|--------------|----------------|---------|
| `devices.list` | `devices.list` или `devices.*` | ✅ `["devices.*"]` |
| `devices.set_state` | `devices.set_state` или `devices.*` | ✅ `["devices.*"]` |
| `automation.trigger` | `automation.trigger` или `automation.*` | ✅ `["automation.*"]` |
| `admin.v1.runtime` | `is_admin=True` | ❌ без admin прав |

---

## Реализация

### Модули

1. **`modules/api/auth.py`** — boundary-layer auth логика:
   - `RequestContext` dataclass
   - `validate_api_key()` — валидация ключа
   - `check_service_scope()` — проверка прав
   - `require_auth_middleware()` — FastAPI middleware

2. **`modules/api/module.py`** — интеграция:
   - Middleware для извлечения API Key
   - Проверка scopes перед `service_registry.call()`
   - Сохранение `RequestContext` в `request.state`

### AdminModule

AdminModule **НЕ требует изменений** — он регистрирует endpoints через `HttpRegistry`, которые обрабатываются ApiModule с уже интегрированным auth.

---

## Примеры

### Создание API Key

```python
# В скрипте или через admin API
api_key = "my_secret_key_12345"

key_data = {
    "subject": "api_key:my_key_123",
    "scopes": ["devices.read", "devices.write"],
    "is_admin": False
}

await runtime.storage.set("auth_api_keys", api_key, key_data)
```

### Создание Admin Key

```python
admin_key = "admin_secret_key_67890"

admin_data = {
    "subject": "api_key:admin_key_678",
    "scopes": [],  # Не используется для admin
    "is_admin": True
}

await runtime.storage.set("auth_api_keys", admin_key, admin_data)
```

### Использование в HTTP запросах

```bash
# Успешный запрос с валидным ключом
curl -H "Authorization: Bearer my_secret_key_12345" \
     http://localhost:8000/api/devices/list

# Ошибка 401 (нет ключа)
curl http://localhost:8000/api/devices/list

# Ошибка 403 (нет прав)
curl -H "Authorization: Bearer key_without_devices_scope" \
     http://localhost:8000/api/devices/list
```

---

## Обработка ошибок

| Код | Условие | Описание |
|-----|---------|----------|
| 401 | `context is None` | Нет авторизации (ключ не передан или невалиден) |
| 403 | `context is not None` но нет прав | Ключ валиден, но недостаточно прав |
| 404 | Сервис не найден | Обычная ошибка (не связана с auth) |

---

## Future-Ready

Архитектура подготовлена для расширения:

### Stage B: Users & Sessions

```python
@dataclass
class RequestContext:
    subject: str      # "user:user_id" или "session:session_id"
    scopes: List[str]
    is_admin: bool
    source: str       # "api_key" | "session" | "oauth"
    user_id: Optional[str] = None  # Для users
    session_id: Optional[str] = None  # Для sessions
```

### Stage C: OAuth

```python
# validate_oauth_token() аналогично validate_api_key()
context = await validate_oauth_token(runtime, oauth_token)
```

### Stage D: Fine-grained Permissions

```python
# Более детальные scopes
scopes = [
    "devices.read",
    "devices.write:light",
    "automation.trigger:schedule"
]
```

---

## Важные ограничения

### ✅ Что работает

- API Key authentication на boundary-layer
- Проверка scopes перед вызовом сервисов
- Административные права
- Изоляция от CoreRuntime и доменных модулей

### ❌ Что НЕ реализовано (Stage A)

- Управление API keys через API (только через storage напрямую)
- Ротация ключей
- Rate limiting
- Audit logging
- Users и sessions
- OAuth

---

## Тестирование

### Ручное тестирование

1. Создать API key через storage
2. Выполнить запрос с ключом
3. Проверить успешный ответ
4. Выполнить запрос без ключа → 401
5. Выполнить запрос с ключом без прав → 403

### Пример теста

```python
# Создать ключ
await runtime.storage.set(
    "auth_api_keys",
    "test_key",
    {
        "subject": "api_key:test",
        "scopes": ["devices.read"],
        "is_admin": False
    }
)

# Запрос с ключом
response = requests.get(
    "http://localhost:8000/api/devices/list",
    headers={"Authorization": "Bearer test_key"}
)
assert response.status_code == 200

# Запрос без ключа
response = requests.get("http://localhost:8000/api/devices/list")
assert response.status_code == 401
```

---

## См. также

- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракты Core Runtime
- [07-RUNTIME-MODULE-CONTRACT.md](07-RUNTIME-MODULE-CONTRACT.md) — контракт RuntimeModule
- `modules/api/auth.py` — реализация boundary-layer auth
- `modules/api/module.py` — интеграция auth в ApiModule
