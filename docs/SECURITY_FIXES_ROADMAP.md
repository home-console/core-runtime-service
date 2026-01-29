# Security Audit Report — Action Items

**Дата:** 27 января 2026  
**Статус:** 🟡 **ACTIVE MITIGATION REQUIRED**

---

## Executive Summary

Проведён детальный security audit проекта `core-runtime-service` по OWASP Top 10 (2021).

**Найдено:**
- 🔴 1 CRITICAL уязвимость (SSRF)
- 🟠 3 HIGH/MEDIUM уязвимости
- 🟡 2 LOW уязвимости

**Статус:** Проект имеет базовую безопасность, но требуются срочные исправления перед production.

---

## Critical Issues (должны быть исправлены немедленно)

### 🔴 Issue #1: SSRF in RemotePluginProxy

**Файл:** `plugins/remote_plugin_proxy.py` (строки 64-110)

**Проблема:**
```python
async def _http_call(self, endpoint: str, ...):
    url = f"{self.remote_url}{endpoint}"
    # ❌ НЕТ ВАЛИДАЦИИ URL
    async with aiohttp.ClientSession() as session:
        async with await session.get(url) as resp:
            ...
```

**Риск:** Плагины могут выполнять HTTP запросы к приватным IP адресам (localhost, внутренние сервисы).

**Исправление:**
```python
# 1. Импортируем валидатор
from modules.api.security.url_validator import validate_url_for_plugin

# 2. Добавляем валидацию
async def _http_call(self, endpoint: str, ...):
    url = f"{self.remote_url}{endpoint}"
    
    # SECURITY: Валидируем URL перед запросом
    try:
        validate_url_for_plugin(url)
    except BadRequestError as e:
        raise RuntimeError(f"URL validation failed: {str(e)}")
    
    async with aiohttp.ClientSession() as session:
        ...
```

**Тестирование:**
```bash
# Добавить unit tests в tests/security/test_url_validator.py
pytest tests/security/test_url_validator.py -v
```

---

## High/Medium Issues (исправить на неделю)

### 🟠 Issue #2: No Idempotency Support

**Файл:** Любые endpoints с state-changing операциями

**Проблема:**
- Нет защиты от duplicate requests
- Race conditions при быстрых повторных нажатиях
- Возможны двойные команды

**Исправление:**
```python
# 1. Добавить middleware в modules/api/module.py
from modules.api.security import idempotency_middleware

app.add_middleware(idempotency_middleware)

# 2. Клиент отправляет:
headers = {
    "Idempotency-Key": f"{device_id}:{uuid.uuid4()}"
}
response = client.post("/api/devices/set_state", headers=headers, ...)
```

**Тестирование:**
```bash
# Отправить два одинаковых запроса с одним Idempotency-Key
# Должны вернуться одинаковые результаты
```

---

### 🟠 Issue #3: No JWT Key Rotation

**Файл:** `modules/api/auth/jwt_tokens.py`, `modules/api/auth/constants.py`

**Проблема:**
- JWT secret хранится в storage и не меняется
- Скомпрометированный ключ невозможно "отозвать"
- Нет `kid` (Key ID) в JWT

**Исправление (Phase 1):**
1. Добавить multi-key support
2. Обновить `create_access_token()` чтобы добавлять `kid` в header

```python
# modules/api/auth/jwt_tokens.py

# Добавить класс для управления ключами
class JWTKeyRotation:
    async def get_current_key(self, runtime) -> str:
        """Получить текущий активный ключ"""
        pass
    
    async def get_all_keys(self, runtime) -> List[Dict]:
        """Получить все ключи (для валидации)"""
        pass
    
    async def rotate_key(self, runtime) -> str:
        """Повернуть ключ (generate new, mark old as grace period)"""
        pass

async def create_access_token(data: dict, runtime) -> str:
    """
    Создаёт JWT с `kid` (Key ID).
    """
    rotation = JWTKeyRotation()
    current_key = await rotation.get_current_key(runtime)
    key_id = await rotation.get_key_id(current_key)
    
    headers = {"kid": key_id}
    token = jwt.encode(
        data, 
        current_key, 
        algorithm=JWT_ALGORITHM,
        headers=headers
    )
    return token
```

**Тестирование:**
```bash
# Тест на ротацию ключей
pytest tests/auth/test_jwt_rotation.py -v
```

---

### 🟠 Issue #4: No Dependency Scanning

**Файл:** CI configuration

**Проблема:**
- Нет автоматической проверки на уязвимые зависимости
- Устаревшие пакеты могут остаться незамеченными

**Исправление:**
1. Добавить `pip-audit` в requirements-dev.txt
2. Добавить GitHub Actions workflow:

```yaml
# .github/workflows/security.yml
name: Security Scan

on: [push, pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install pip-audit
      - run: pip-audit
      
      - name: Check npm audit
        run: npm audit --prefix admin-ui-service
```

---

## Low Priority Issues (исправить в течение месяца)

### 🟡 Issue #5: Missing JWT ID (jti) for Revocation

**Файл:** `modules/api/auth/jwt_tokens.py`

**Решение:**
- Добавить `jti` (JWT ID) в claims
- При logout добавлять `jti` в revocation list
- При валидации проверять revocation list

---

## Implementation Roadmap

| Неделя | Задача | Приоритет | Сложность |
|--------|--------|-----------|-----------|
| АСАП | Добавить SSRF валидацию | 🔴 P0 | ⭐⭐ |
| Неделя 1 | Idempotency middleware | 🟠 P1 | ⭐ |
| Неделя 2 | JWT key rotation | 🟠 P1 | ⭐⭐⭐ |
| Неделя 3 | Dependency scanning | 🟡 P2 | ⭐ |
| Месяц 1 | JWT jti + revocation | 🟡 P2 | ⭐⭐ |

---

## Files Added/Modified

**Добавлены:**
- ✅ `modules/api/security/__init__.py` (новый)
- ✅ `modules/api/security/url_validator.py` (новый)
- ✅ `modules/api/security/idempotency.py` (новый)

**Требуют обновления:**
- ⏳ `plugins/remote_plugin_proxy.py` (добавить SSRF валидацию)
- ⏳ `modules/api/module.py` (добавить idempotency middleware)
- ⏳ `modules/api/auth/jwt_tokens.py` (добавить rotation)

---

## Testing Checklist

```bash
# Юнит-тесты
pytest tests/security/ -v

# SSRF валидация
pytest tests/security/test_url_validator.py -v

# Idempotency
pytest tests/security/test_idempotency.py -v

# JWT
pytest tests/auth/ -v

# Интеграционные тесты
pytest tests/integration/ -v
```

---

## References

- [SECURITY_AUDIT.md](./SECURITY_AUDIT.md) — полный отчёт
- [OWASP Top 10 (2021)](https://owasp.org/Top10/)
- [SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [JWT Best Practices](https://tools.ietf.org/html/rfc8725)

---

**Последнее обновление:** 27 января 2026
