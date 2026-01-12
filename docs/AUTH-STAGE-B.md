# API Key Authentication — Stage B (Users & Sessions)

> **Статус:** Реализовано (Stage B)  
> **Версия:** 2.0  
> **Архитектурный принцип:** Boundary-layer authentication  
> **Основа:** [AUTH-STAGE-A.md](AUTH-STAGE-A.md)

---

## Обзор

Stage B расширяет Stage A поддержкой **users и sessions**:

- ✅ **Users** — хранение пользователей в storage
- ✅ **Sessions** — cookie-based authentication
- ✅ **Session expiration** — автоматическое истечение сессий
- ✅ **Dual authentication** — API Key (Bearer) или Session (Cookie)
- ✅ **Backward compatible** — API Keys продолжают работать

**Ключевой принцип:**
- Auth логика **НЕ проникает** в CoreRuntime, RuntimeModule, ServiceRegistry или доменные модули
- Всё изолировано на уровне HTTP boundary
- Доменные модули **НЕ знают** про auth

---

## Архитектура

### Dual Authentication Flow

```
HTTP Request
    ↓
[ApiModule Middleware]
    ├─→ Authorization: Bearer <api_key> → validate_api_key()
    └─→ Cookie: session_id → validate_session()
    ↓
[RequestContext] ← user_id, session_id (Stage B)
    ↓
[ApiModule Handler] ← check_service_scope()
    ↓
[ServiceRegistry.call()] ← НЕ знает про auth
```

### RequestContext (Stage B)

Расширенный контекст авторизации:

```python
@dataclass
class RequestContext:
    subject: str              # "api_key:key_id" | "user:user_id" | "session:session_id"
    scopes: List[str]         # ["devices.read", "devices.write"]
    is_admin: bool            # True для администраторов
    source: str               # "api_key" | "session" | "oauth"
    user_id: Optional[str]    # ID пользователя (для users и sessions)
    session_id: Optional[str] # ID сессии (для sessions)
```

---

## Storage Structure

### Users

Namespace: `"auth_users"`

```python
user_data = {
    "user_id": "user_123",
    "username": "john_doe",
    "scopes": ["devices.read", "devices.write", "automation.*"],
    "is_admin": False,
    "created_at": 1234567890.0
}
```

### Sessions

Namespace: `"auth_sessions"`

```python
session_data = {
    "user_id": "user_123",
    "created_at": 1234567890.0,
    "expires_at": 1234654290.0  # 24 hours by default
}
```

### API Keys (Stage A)

Namespace: `"auth_api_keys"`

```python
key_data = {
    "subject": "api_key:key_id",
    "scopes": ["devices.read"],
    "is_admin": False
}
```

---

## Использование

### 1. Создание пользователя

```python
user_id = "user_123"

user_data = {
    "user_id": user_id,
    "username": "john_doe",
    "scopes": ["devices.read", "devices.write"],
    "is_admin": False,
    "created_at": time.time()
}

await runtime.storage.set("auth_users", user_id, user_data)
```

### 2. Создание сессии

```python
from modules.api.auth import create_session

# Создать сессию для пользователя (24 часа по умолчанию)
session_id = await create_session(runtime, "user_123")

# Создать сессию с кастомным expiration (1 час)
session_id = await create_session(runtime, "user_123", expiration_seconds=3600)
```

### 3. HTTP Request с Session (Cookie)

```bash
# Установить cookie (через браузер или HTTP client)
curl -b "session_id=<session_id>" \
     http://localhost:8000/api/devices/list

# Или через Set-Cookie header (после login)
curl -c cookies.txt http://localhost:8000/api/auth/login
curl -b cookies.txt http://localhost:8000/api/devices/list
```

### 4. HTTP Request с API Key (Bearer)

```bash
# API Key продолжает работать (Stage A)
curl -H "Authorization: Bearer <api_key>" \
     http://localhost:8000/api/devices/list
```

### 5. Приоритет авторизации

1. **API Key** (Authorization: Bearer) — если присутствует, используется
2. **Session** (Cookie: session_id) — если API Key отсутствует

---

## Примеры

### Полный цикл: Login → Session → Request

```python
# 1. Создать пользователя
user_id = "user_123"
await runtime.storage.set("auth_users", user_id, {
    "user_id": user_id,
    "username": "john",
    "scopes": ["devices.read", "devices.write"],
    "is_admin": False,
    "created_at": time.time()
})

# 2. Login (создать сессию)
from modules.api.auth import create_session
session_id = await create_session(runtime, user_id)

# 3. HTTP Request с session cookie
# Cookie: session_id=<session_id>
# → RequestContext будет содержать user_id и session_id
```

### Удаление сессии (Logout)

```python
from modules.api.auth import delete_session

await delete_session(runtime, session_id)
```

### Проверка истечения сессии

Сессии автоматически проверяются на expiration:

```python
# При validate_session():
# - Если expires_at < current_time → сессия удаляется, возвращается None
# - Если пользователь не найден → сессия удаляется, возвращается None
```

---

## API для управления (Future)

Для полной интеграции можно добавить admin endpoints:

```python
# POST /admin/v1/auth/users
# Создать пользователя

# POST /admin/v1/auth/login
# Создать сессию (вернуть session_id в Set-Cookie)

# POST /admin/v1/auth/logout
# Удалить сессию

# GET /admin/v1/auth/me
# Получить текущего пользователя из RequestContext
```

---

## Обработка ошибок

| Код | Условие | Описание |
|-----|---------|----------|
| 401 | `context is None` | Нет авторизации (нет ключа/сессии или невалидны) |
| 403 | `context is not None` но нет прав | Ключ/сессия валидны, но недостаточно прав |
| 404 | Сервис не найден | Обычная ошибка (не связана с auth) |

---

## Session Management

### Expiration

- **По умолчанию:** 24 часа (`DEFAULT_SESSION_EXPIRATION_SECONDS`)
- **Кастомное:** передать `expiration_seconds` в `create_session()`

### Cleanup

Сессии автоматически удаляются при:
- Истечении срока (`expires_at < current_time`)
- Пользователь не найден в storage
- Явный вызов `delete_session()`

### Security

- Session ID генерируется через `secrets.token_urlsafe(32)` (cryptographically secure)
- Сессии хранятся в storage (персистентно)
- При истечении сессия удаляется автоматически

---

## Migration from Stage A

Stage B **полностью обратно совместим** с Stage A:

- ✅ API Keys продолжают работать
- ✅ Существующий код не требует изменений
- ✅ Sessions — дополнительная опция

**Что изменилось:**
- `RequestContext` расширен (`user_id`, `session_id`)
- Middleware поддерживает cookies
- Добавлены функции `validate_session()`, `create_session()`, `delete_session()`

---

## Future-Ready

Архитектура подготовлена для расширения:

### Stage C: OAuth

```python
async def validate_oauth_token(runtime: Any, oauth_token: str) -> Optional[RequestContext]:
    # Аналогично validate_api_key() и validate_session()
    # source="oauth"
    pass
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

### Stage E: Multi-factor Authentication

```python
@dataclass
class RequestContext:
    # ... existing fields ...
    mfa_verified: bool = False
    mfa_method: Optional[str] = None
```

---

## Тестирование

### Ручное тестирование

1. Создать пользователя в storage
2. Создать сессию через `create_session()`
3. Выполнить запрос с cookie `session_id`
4. Проверить успешный ответ
5. Выполнить запрос без cookie → 401
6. Выполнить запрос с истёкшей сессией → 401

### Пример теста

```python
# Создать пользователя
await runtime.storage.set("auth_users", "user_123", {
    "user_id": "user_123",
    "username": "test_user",
    "scopes": ["devices.read"],
    "is_admin": False,
    "created_at": time.time()
})

# Создать сессию
from modules.api.auth import create_session
session_id = await create_session(runtime, "user_123")

# Запрос с session cookie
response = requests.get(
    "http://localhost:8000/api/devices/list",
    cookies={"session_id": session_id}
)
assert response.status_code == 200

# Запрос без cookie
response = requests.get("http://localhost:8000/api/devices/list")
assert response.status_code == 401
```

---

## См. также

- [AUTH-STAGE-A.md](AUTH-STAGE-A.md) — Stage A (API Keys)
- [04-CORE-RUNTIME-CONTRACT.md](04-CORE-RUNTIME-CONTRACT.md) — контракты Core Runtime
- [07-RUNTIME-MODULE-CONTRACT.md](07-RUNTIME-MODULE-CONTRACT.md) — контракт RuntimeModule
- `modules/api/auth.py` — реализация boundary-layer auth
