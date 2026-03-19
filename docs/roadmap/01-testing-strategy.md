# 🧪 Testing Strategy — Стратегия тестирования

**Приоритет:** 🔴 КРИТИЧЕСКИЙ  
**Срок:** 2 недели (до 28 февраля 2026)  
**Ответственный:** Dev Team

---

## 🎯 Цель

Достичь **80%+ test coverage** для всех критических компонентов системы.

---

## 📊 Текущее состояние

### Проблемы:
- ❌ Только 16 тестовых файлов на 2806 Python файлов
- ❌ Coverage < 30%
- ❌ Критические модули без тестов:
  - `modules/api/auth/*` (14 файлов) — 0% после рефакторинга
  - `modules/admin/` — нет тестов авторизации
  - `modules/automation/` — нет unit тестов
  - `client-manager-service` — огромный плагин без тестов
  - HTTP endpoints в ApiModule — нет интеграционных тестов

### Риски:
- 🔥 Регрессии при изменениях
- 🔥 Невозможность уверенного рефакторинга
- 🔥 Production баги
- 🔥 Долгий onboarding новых разработчиков

---

## 📋 План действий

### Неделя 1: Auth модуль + Core компоненты

#### День 1-2: Auth модуль (14 файлов)
```bash
tests/auth/
  test_api_keys.py           # api_keys.py
  test_sessions.py           # sessions.py
  test_jwt_tokens.py         # jwt_tokens.py
  test_passwords.py          # passwords.py
  test_users.py              # users.py
  test_revocation.py         # revocation.py
  test_audit.py              # audit.py
  test_rate_limiting.py      # rate_limiting.py
  test_middleware.py         # middleware.py
  test_utils.py              # utils.py
  test_context.py            # context.py
```

**Приоритет тестов:**
1. `test_api_keys.py` — validate_api_key(), create_api_key()
2. `test_sessions.py` — validate_session(), create_session()
3. `test_jwt_tokens.py` — validate_jwt_token(), generate_access_token()
4. `test_passwords.py` — hash_password(), verify_password()
5. `test_middleware.py` — require_auth_middleware()

**Шаблон теста:**
```python
"""
Тесты для modules/api/auth/api_keys.py
"""
import pytest
from modules.api.auth import validate_api_key, create_api_key
from modules.api.auth.constants import AUTH_API_KEYS_NAMESPACE

@pytest.fixture
def mock_runtime():
    """Mock CoreRuntime для изоляции тестов."""
    # ...

class TestValidateApiKey:
    """Тесты для validate_api_key()."""
    
    @pytest.mark.asyncio
    async def test_valid_api_key_returns_context(self, mock_runtime):
        """Тест: валидный API key возвращает RequestContext."""
        # Arrange
        api_key = "test_key_123"
        key_data = {
            "subject": "user:test",
            "scopes": ["devices.read"],
            "is_admin": False,
            "expires_at": None
        }
        mock_runtime.storage.get.return_value = key_data
        
        # Act
        context = await validate_api_key(mock_runtime, api_key)
        
        # Assert
        assert context is not None
        assert context.subject == "user:test"
        assert "devices.read" in context.scopes
        assert context.is_admin is False
        assert context.source == "api_key"
    
    @pytest.mark.asyncio
    async def test_nonexistent_key_returns_none(self, mock_runtime):
        """Тест: несуществующий ключ возвращает None."""
        mock_runtime.storage.get.return_value = None
        
        context = await validate_api_key(mock_runtime, "invalid_key")
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self, mock_runtime):
        """Тест: истекший ключ возвращает None."""
        import time
        api_key = "expired_key"
        key_data = {
            "subject": "user:test",
            "scopes": ["devices.read"],
            "is_admin": False,
            "expires_at": time.time() - 3600  # Истёк час назад
        }
        mock_runtime.storage.get.return_value = key_data
        mock_runtime.storage.delete.return_value = True
        
        context = await validate_api_key(mock_runtime, api_key)
        
        assert context is None
        mock_runtime.storage.delete.assert_called_once()
```

#### День 3-4: AdminModule тесты
```bash
tests/modules/
  test_admin_module.py       # Основной модуль
  test_admin_services.py     # Сервисы (create_user, etc.)
  test_admin_endpoints.py    # HTTP endpoints
```

**Что тестировать:**
- ✅ Регистрация сервисов
- ✅ HTTP контракты
- ✅ User management flow
- ✅ API key management
- ✅ Session management
- ✅ Authorization checks

#### День 5: AutomationModule тесты
```bash
tests/modules/
  test_automation_module.py  # Основной модуль
```

**Что тестировать:**
- ✅ Lifecycle (register, start, stop)
- ✅ Event subscriptions
- ✅ Service calls

---

### Неделя 2: Интеграционные тесты + CI/CD

#### День 6-7: HTTP endpoints
```bash
tests/integration/
  test_api_endpoints.py      # REST API endpoints
  test_auth_flow.py          # Полный auth flow
  test_devices_api.py        # Devices endpoints
  test_admin_api.py          # Admin endpoints
```

**Пример интеграционного теста:**

```python
"""
Интеграционные тесты для API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from core.runtime.runtime import CoreRuntime


@pytest.fixture
async def test_runtime(memory_adapter):
    """Создать тестовый runtime с загруженными модулями."""
    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    yield runtime
    await runtime.shutdown()


@pytest.fixture
def test_client(test_runtime):
    """FastAPI TestClient для интеграционных тестов."""
    api_module = test_runtime.module_manager.get_module("api")
    return TestClient(api_module.app)


def test_create_api_key_endpoint(test_client):
    """Тест: POST /api/v1/auth/api-keys создаёт ключ."""
    # Arrange
    request_data = {
        "subject": "user:test",
        "scopes": ["devices.read"],
        "expires_in": 3600
    }

    # Act
    response = test_client.post("/api/v1/auth/api-keys", json=request_data)

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert "api_key" in data
    assert data["subject"] == "user:test"


def test_get_devices_requires_auth(test_client):
    """Тест: GET /api/v1/devices требует аутентификацию."""
    # Act
    response = test_client.get("/api/v1/devices")

    # Assert
    assert response.status_code == 401  # Unauthorized


def test_get_devices_with_valid_key(test_client):
    """Тест: GET /api/v1/devices с валидным ключом."""
    # Arrange - создаём API key
    create_response = test_client.post("/api/v1/auth/api-keys", json={
        "subject": "user:test",
        "scopes": ["devices.read"]
    })
    api_key = create_response.json()["api_key"]

    # Act
    response = test_client.get(
        "/api/v1/devices",
        headers={"Authorization": f"Bearer {api_key}"}
    )

    # Assert
    assert response.status_code == 200
```

#### День 8-9: CI/CD Setup
```yaml
# .github/workflows/tests.yml
name: Tests

on:
  push:
    branches: [ master, develop ]
  pull_request:
    branches: [ master, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        cd core-runtime-service
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov
    
    - name: Run tests with coverage
      run: |
        cd core-runtime-service
        pytest \
          --cov=core \
          --cov=modules \
          --cov=plugins \
          --cov-report=term-missing \
          --cov-report=xml \
          --cov-report=html \
          --cov-fail-under=80
    
    - name: Upload coverage reports
      uses: codecov/codecov-action@v3
      with:
        file: ./core-runtime-service/coverage.xml
        flags: unittests
        name: codecov-umbrella
```

#### День 10: Coverage badge + финализация
```markdown
# В README.md добавить:
[![Coverage](https://codecov.io/gh/username/HomeConsole/branch/master/graph/badge.svg)](https://codecov.io/gh/username/HomeConsole)
[![Tests](https://github.com/username/HomeConsole/workflows/Tests/badge.svg)](https://github.com/username/HomeConsole/actions)
```

---

## 🎯 Критерии успеха

### Минимальные требования:
- ✅ Coverage > 80% для core/
- ✅ Coverage > 80% для modules/
- ✅ Coverage > 70% для plugins/
- ✅ Все критические пути покрыты тестами
- ✅ CI/CD запускает тесты автоматически
- ✅ PR не может быть смержен без прохождения тестов

### Что должно быть протестировано:
1. **Core компоненты:**
   - EventBus
   - ServiceRegistry
   - StateEngine
   - Storage
   - PluginManager
   - ModuleManager

2. **Auth система:**
   - API Keys
   - Sessions
   - JWT Tokens
   - Passwords
   - Revocation
   - Middleware

3. **Модули:**
   - ApiModule (endpoints)
   - AdminModule (services)
   - DevicesModule
   - AutomationModule

4. **Критические плагины:**
   - DevicesPlugin
   - SystemLoggerPlugin

---

## 📝 Checklist

### Auth модуль (14 файлов)
- [ ] test_api_keys.py
- [ ] test_sessions.py
- [ ] test_jwt_tokens.py
- [ ] test_passwords.py
- [ ] test_users.py
- [ ] test_revocation.py
- [ ] test_audit.py
- [ ] test_rate_limiting.py
- [ ] test_middleware.py
- [ ] test_utils.py
- [ ] test_context.py
- [ ] test_constants.py
- [ ] test_middleware_helpers.py

### Модули
- [ ] test_admin_module.py
- [ ] test_automation_module.py
- [ ] test_api_module_endpoints.py

### Интеграционные тесты
- [ ] test_api_endpoints.py
- [ ] test_auth_flow.py
- [ ] test_devices_api.py
- [ ] test_admin_api.py

### CI/CD
- [ ] .github/workflows/tests.yml
- [ ] Coverage badge в README.md
- [ ] Pre-commit hooks
- [ ] Codecov integration

---

## 🔗 Ссылки

- **Основной roadmap:** [ROADMAP.md](../ROADMAP.md)
- **Pytest документация:** https://docs.pytest.org/
- **Pytest-asyncio:** https://pytest-asyncio.readthedocs.io/
- **Coverage.py:** https://coverage.readthedocs.io/

---

## 📊 Прогресс

**Статус:** 🔴 Не начато  
**Coverage:** < 30%  
**Цель:** 80%+  
**Дата начала:** TBD  
**Дата завершения:** TBD
