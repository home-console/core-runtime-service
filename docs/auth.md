# Authentication & Authorization

> **Статус:** Реализовано  
> **Принцип:** Boundary-layer — auth изолирован в ApiModule, не проникает в CoreRuntime

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

### API Key

**Хранение:** `runtime.storage` namespace `"auth_api_keys"`

```python
key_data = {
    "subject": "api_key:my_key_123",
    "scopes": ["devices.read", "devices.write"],
    "is_admin": False
}
await runtime.storage.set("auth_api_keys", "actual_api_key_string", key_data)
```

**Использование:**
```bash
curl -H "Authorization: Bearer <api_key>" http://localhost:8000/api/devices/list
```

### Sessions

**Хранение:** 
- Users: `"auth_users"` namespace
- Sessions: `"auth_sessions"` namespace

**Использование:**
```bash
# Создание сессии (через API)
POST /api/auth/login
Cookie: session_id=<session_id>
```

**Приоритет:** API Key (Bearer header) → Session (Cookie)

---

## Authorization

### Authorization Policy Layer

Единая точка проверок: `modules/api/authz.py`

```python
from modules.api.authz import require as authz_require, AuthorizationError

try:
    authz_require(context, "devices.list")
except AuthorizationError:
    raise HTTPException(403, "Forbidden")
```

### Логика проверки

1. **Нет контекста** → отказ
2. **is_admin=True** → разрешено
3. **Полный wildcard (`*`)** → разрешено
4. **Admin действия (`admin.*`)** → требуется `admin.*` scope
5. **Обычные действия** → проверка mapping:
   - Точное совпадение scope
   - Wildcard для namespace (`devices.*`)
   - Если action не найден → отказ

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
