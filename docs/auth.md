# Authentication & Authorization

> **Статус:** Реализовано + JWT + ACL  
> **Принцип:** Boundary-layer — auth изолирован в ApiModule, не проникает в CoreRuntime  
> **JWT:** Access tokens (15 мин) + Refresh tokens (7 дней)  
> **ACL:** Ownership + Shared resources для гостевого доступа

---

## Архитектура

```
HTTP Request
    ↓
[ApiModule Middleware] ← validate_api_key() / validate_session()
    ↓
[RequestContext] ← передаётся через request.state
    ↓
[ApiModule Handler] ← authz.require(ctx, action)
    ↓
[ServiceRegistry.call()] ← НЕ знает про auth
    ↓
[Domain Modules] ← НЕ знают про auth
```

**Ключевой принцип:** Auth логика полностью изолирована на уровне HTTP boundary. CoreRuntime, RuntimeModule, ServiceRegistry и доменные модули не знают про auth.

**Trusted Services Model:** Authorization выполняется ТОЛЬКО на boundary-слое (ApiModule, AdminModule). ServiceRegistry, RuntimeModule и доменные сервисы считаются trusted и не выполняют проверки доступа. Прямые вызовы сервисов через `service_registry.call()` допустимы только из trusted-кода (модулей и плагинов).

---

## RequestContext

Контекст авторизации передаётся через `request.state.auth_context`:

```python
@dataclass
class RequestContext:
    subject: str              # "api_key:key_id" | "user:user_id" | "session:session_id"
    scopes: List[str]         # ["devices.read", "devices.write"]
    is_admin: bool            # True для администраторов
    source: str               # "api_key" | "session"
    user_id: Optional[str]    # ID пользователя (для sessions)
    session_id: Optional[str] # ID сессии (для sessions)
```

---

## Authentication

### JWT Access Tokens (Рекомендуется)

**Тип:** Stateless JWT tokens (HS256)

**Использование:**
```bash
# Login - получаем access_token и refresh_token
POST /admin/v1/auth/login
Body: {"user_id": "user123", "password": "secure_password"}
Response: {
    "ok": true,
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "refresh_xyz...",
    "expires_in": 900,
    "token_type": "Bearer"
}

# Использование access_token
curl -H "Authorization: Bearer <access_token>" http://localhost:8000/api/devices/list

# Обновление access_token
POST /admin/v1/auth/refresh
Body: {"refresh_token": "refresh_xyz..."}
Response: {
    "ok": true,
    "access_token": "new_jwt_token...",
    "refresh_token": "new_refresh_token...",  # Ротируется
    "expires_in": 900
}
```

**Особенности:**
- Access token живёт 15 минут (короткоживущий)
- Refresh token живёт 7 дней (долгоживущий)
- Refresh token ротируется при каждом обновлении (безопасность)
- JWT secret хранится в `auth_config` namespace

### API Key

**Хранение:** `runtime.storage` namespace `"auth_api_keys"`

```python
key_data = {
    "subject": "api_key:my_key_123",
    "scopes": ["devices.read", "devices.write"],
    "is_admin": False,
    "created_at": 1234567890.0,
    "last_used": 1234567895.0,
    "expires_at": None  # Опционально
}
await runtime.storage.set("auth_api_keys", "actual_api_key_string", key_data)
```

**Использование:**
```bash
curl -H "Authorization: Bearer <api_key>" http://localhost:8000/api/devices/list
```

### Sessions (Legacy)

**Хранение:** 
- Users: `"auth_users"` namespace (включая `password_hash`)
- Sessions: `"auth_sessions"` namespace (с метаданными: `client_ip`, `user_agent`, `last_used`)

**Использование:**
```bash
# Создание сессии (legacy, рекомендуется использовать JWT)
POST /admin/v1/auth/login  # Теперь возвращает JWT, но сессии тоже поддерживаются
Body: {"user_id": "user123", "password": "secure_password", "client_ip?": "...", "user_agent?": "..."}
Cookie: session_id=<session_id>  # Опционально, если нужны cookie-based сессии

# Список активных сессий
GET /admin/v1/auth/sessions?user_id=user123  # опциональный фильтр
# Возвращает: [{session_id, user_id, created_at, expires_at, last_used, client_ip?, user_agent?}]

# Отзыв конкретной сессии
POST /admin/v1/auth/sessions/revoke
Body: {"session_id": "..."}

# Отзыв всех сессий пользователя
POST /admin/v1/auth/sessions/revoke-all
Body: {"user_id": "user123"}
```

**Password Management:**
```bash
# Установка пароля
POST /admin/v1/auth/password/set
Body: {"user_id": "user123", "password": "new_password"}

# Смена пароля (требует старый пароль)
POST /admin/v1/auth/password/change
Body: {"user_id": "user123", "old_password": "old", "new_password": "new"}
```

**Password Policies:**
- Минимальная длина: 8 символов
- Максимальная длина: 128 символов
- Требуется: заглавные буквы, строчные буквы, цифры
- Опционально: специальные символы (можно включить через `REQUIRE_SPECIAL_CHAR`)

**Приоритет:** API Key (Bearer header) → Session (Cookie)

---

## Authorization

### Authorization Policy Layer

Единая точка проверок: `modules/api/authz.py`

Поддерживает:
- **Scope-based authorization** (действие → scope)
- **Resource-Based Authorization** с ACL (ownership + shared_with)
- **Self-service** проверки для auth операций

```python
from modules.api.authz import require as authz_require, AuthorizationError

# Простая проверка действия
try:
    authz_require(context, "devices.list")
except AuthorizationError:
    raise HTTPException(403, "Forbidden")

# Проверка с ресурсом (ACL)
try:
    resource = {"owner_id": "user123", "shared_with": ["user456"]}
    authz_require(context, "devices.get", resource)
except AuthorizationError:
    raise HTTPException(403, "Forbidden")
```

### Логика проверки

#### 1. Проверка действия (Scope-based)

1. **Нет контекста** → отказ (кроме специальных случаев)
2. **is_admin=True** → разрешено (полный доступ)
3. **Полный wildcard (`*`)** → разрешено
4. **Admin действия (`admin.*`)** → требуется `admin.*` scope
5. **Обычные действия** → проверка mapping:
   - Точное совпадение scope
   - Wildcard для namespace (`devices.*`)
   - Если action не найден → отказ

#### 2. Проверка ресурса (Resource-Based с ACL)

Если `resource` предоставлен:

1. **Ownership:** `owner_id == ctx.user_id` → разрешено
2. **Shared access:** `ctx.user_id in shared_with` → разрешено
3. **Self-service:** для auth операций `target_user_id == ctx.user_id` → разрешено
4. **Admin override:** `ctx.is_admin` → разрешено
5. **Иначе** → запрещено

### Action → Scope Mapping

```python
ACTION_SCOPE_MAP = {
    "devices.list": "devices.read",
    "devices.set_state": "devices.write",
    "automation.trigger": "automation.write",
    "presence.set": "presence.write",
    # ...
}
```

**Примеры:**

| Action | Required Scope | Примеры |
|--------|---------------|---------|
| `devices.list` | `devices.read` или `devices.*` | ✅ `["devices.*"]` |
| `devices.set_state` | `devices.write` или `devices.*` | ✅ `["devices.*"]` |
| `admin.v1.runtime` | `admin.*` или `is_admin=True` | ❌ без admin прав |

---

## Security Features

### Rate Limiting

Защита от brute force: 5 попыток в минуту для auth, 100 запросов в минуту для API.

**Хранение:** `"auth_rate_limits"` namespace

### Audit Logging

Отслеживание всех auth событий: `auth_success`, `auth_failure`, `key_revoked`, `session_created`, `rate_limit_exceeded`.

**Хранение:** `"auth_audit_log"` namespace

### Revocation

Отзыв ключей/сессий через `revoke_api_key()` / `revoke_session()`.

**Хранение:** `"auth_revoked"` namespace

### Timing Attack Protection

Использование `secrets.compare_digest()` для константного времени валидации.

### Input Validation

Валидация при создании ключей/пользователей/сессий.

### Password Security

- **Хеширование:** bcrypt с автоматической генерацией salt
- **Проверка:** `verify_password()` использует timing-safe сравнение
- **Политики:** настраиваемые требования к сложности пароля
- **Автоматический отзыв сессий:** при смене пароля все сессии пользователя отзываются

### Session Management

- **Метаданные:** каждая сессия хранит `client_ip`, `user_agent`, `created_at`, `last_used`
- **Отслеживание использования:** `last_used` обновляется при каждой валидации (не чаще раза в минуту)
- **Управление:** список сессий, отзыв конкретной сессии, отзыв всех сессий пользователя
- **Автоматическая очистка:** истекшие сессии удаляются при валидации

### JWT Token Management

- **Access tokens:** JWT (stateless), 15 минут жизни
- **Refresh tokens:** долгоживущие (7 дней), хранятся в storage
- **Ротация:** refresh token ротируется при каждом обновлении
- **Отзыв:** refresh tokens можно отозвать через `revoke_refresh_token()`

### Resource-Based Authorization (ACL)

- **Ownership:** каждый ресурс может иметь `owner_id`
- **Shared access:** ресурсы могут иметь `shared_with` (список user_id)
- **Self-service:** пользователи могут управлять своими ресурсами
- **Admin override:** администраторы имеют доступ ко всем ресурсам

**Пример структуры устройства с ACL:**
```python
device = {
    "id": "device_123",
    "owner_id": "user123",  # Владелец
    "shared_with": ["user456", "user789"],  # Гостевой доступ
    "name": "Свет кухни",
    "type": "light",
    ...
}
```

**Правила доступа:**
- `user123` (owner) → полный доступ
- `user456`, `user789` (shared) → доступ на чтение/запись
- `user999` (не owner, не в shared) → нет доступа
- `admin` → полный доступ ко всем устройствам

---

## Storage Namespaces

- `auth_api_keys` — API keys
- `auth_users` — Users
- `auth_sessions` — Sessions
- `auth_rate_limits` — Rate limiting counters
- `auth_audit_log` — Audit log entries
- `auth_revoked` — Revoked keys/sessions

---

## Файлы

- `modules/api/auth.py` — Authentication (API Key, Sessions)
- `modules/api/authz.py` — Authorization Policy Layer
- `modules/api/module.py` — HTTP handlers integration
- `tests/test_auth.py` — Authentication tests
- `tests/test_authz.py` — Authorization tests

---

## См. также

- [07-RUNTIME-MODULE-CONTRACT.md](07-RUNTIME-MODULE-CONTRACT.md) — контракт модулей
- [08-PLUGIN-CONTRACT.md](08-PLUGIN-CONTRACT.md) — контракт плагинов
