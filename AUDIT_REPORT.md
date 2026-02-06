# 🔍 Полный аудит и оптимизация репозитория ядра

**Дата:** 6 февраля 2026  
**Версия:** 1.0  
**Статус:** Полный анализ завершен

---

## 📊 Статистика проекта

### Общие метрики
- **Python файлов:** 213
- **Тестовых файлов:** 40
- **Модулей:** 13
- **Плагинов:** 6+
- **Документация:** 242 markdown файла

### Размеры кодовой базы по директориям

#### Core (ядро)
- `plugin_manager.py` - **743 строки** ⚠️
- `service_registry.py` - **462 строки**
- `module_manager.py` - **413 строки**
- `security.py` - **389 строк**
- `runtime.py` - **365 строк**

#### Modules (модули)
- `modules/api/module.py` - **587 строк** ⚠️
- `modules/admin/auth.py` - **512 строк**
- `modules/request_logger/http_client.py` - **488 строк** ⚠️
- `modules/api/auth/jwt_tokens.py` - **471 строк**
- `modules/execution/module.py` - **433 строки**
- `modules/admin/services/introspection.py` - **401 строка**
- `modules/admin/module.py` - **351 строка** (было 1309, уже рефакторено)

#### Plugins (плагины)
- `plugins/oauth_yandex/plugin.py` - **1003 строки** 🔴 КРИТИЧНО
- `plugins/yandex_smart_home/api_client.py` - **816 строк** 🔴 КРИТИЧНО
- `plugins/client_manager/plugin.py` - **610 строк** ⚠️
- `plugins/yandex_smart_home/yandex_quasar_ws.py` - **468 строк**
- `plugins/yandex_smart_home/command_handler.py` - **465 строк**

---

## 🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 1. Огромные файлы (>1000 строк)

#### `plugins/oauth_yandex/plugin.py` (1003 строки)
**Проблема:** Монолитный файл с множественной ответственностью

**Рекомендации:**
```python
# Разбить на:
plugins/oauth_yandex/
  ├── plugin.py              # Основной класс (200 строк)
  ├── oauth_client.py        # HTTP клиент для OAuth API (200 строк)
  ├── token_manager.py       # Управление токенами (200 строк)
  ├── session_manager.py     # Управление сессиями (150 строк)
  ├── capability_provider.py # Capability provider (150 строк)
  └── storage.py             # Работа с storage (100 строк)
```

**Приоритет:** 🔴 P0  
**Оценка:** 4-6 часов

#### `plugins/yandex_smart_home/api_client.py` (816 строк)
**Проблема:** Слишком большой API клиент

**Рекомендации:**
```python
# Разбить на:
plugins/yandex_smart_home/
  ├── api_client.py          # Базовый клиент (200 строк)
  ├── quasar_api.py          # Quasar API методы (300 строк)
  ├── device_api.py          # Device API методы (200 строк)
  └── websocket_client.py    # WebSocket клиент (116 строк)
```

**Приоритет:** 🔴 P0  
**Оценка:** 3-4 часа

### 2. Дублирование зависимостей

**Файл:** `requirements.txt`

**Проблема:**
```txt
# Строка 18
asyncpg>=0.28.0

# Строка 31 (дубликат!)
asyncpg
```

**Исправление:**
```txt
# PostgreSQL adapter (опционально)
asyncpg>=0.28.0
```

**Приоритет:** 🔴 P0  
**Оценка:** 1 минута

### 3. Пустая директория

**Проблема:** `plugins/client-manager-service/` существует, но пустая

**Рекомендации:**
- Удалить пустую директорию
- Или переместить содержимое из `plugins/client_manager/` если это было запланировано

**Приоритет:** 🟡 P1  
**Оценка:** 5 минут

---

## ⚠️ ВЫСОКИЙ ПРИОРИТЕТ

### 4. Оптимизация импортов

**Проблема:** Множественные импорты `from core.` в каждом файле

**Анализ:**
- 50+ файлов импортируют из `core`
- Нет централизованного экспорта через `core/__init__.py`
- Циклические зависимости возможны

**Рекомендации:**

#### 4.1. Улучшить `core/__init__.py`
```python
# Текущий __init__.py имеет дубликат PluginManager в __all__
# Исправить:
__all__ = [
    "Config",
    "CoreRuntime",
    "EventBus",
    "ServiceRegistry",
    "StateEngine",
    "Storage",
    "StorageWithStateMirror",
    "IntegrationRegistry",
    "info",
    "warning",
    "error",
    "PluginManager",  # Убрать дубликат
    "HttpRegistry",
    "ModuleManager",
    "RuntimeModule",
    "create_storage_adapter",
]
```

#### 4.2. Lazy imports для больших модулей
```python
# Вместо:
from plugins.oauth_yandex.plugin import OAuthYandexPlugin

# Использовать:
def get_oauth_plugin():
    from plugins.oauth_yandex.plugin import OAuthYandexPlugin
    return OAuthYandexPlugin
```

**Приоритет:** 🟡 P1  
**Оценка:** 2-3 часа

### 5. Оптимизация больших модулей

#### `modules/api/module.py` (587 строк)
**Проблема:** Много ответственности в одном файле

**Рекомендации:**
```python
modules/api/
  ├── module.py              # Основной модуль (200 строк)
  ├── routes.py               # Регистрация роутов (150 строк)
  ├── middleware_setup.py     # Настройка middleware (150 строк)
  └── app_factory.py          # Создание FastAPI app (87 строк)
```

**Приоритет:** 🟡 P1  
**Оценка:** 3-4 часа

#### `modules/request_logger/http_client.py` (488 строк)
**Проблема:** Слишком сложный HTTP клиент

**Рекомендации:**
```python
modules/request_logger/
  ├── http_client.py          # Основной класс (200 строк)
  ├── trace_config.py          # Trace конфигурация (150 строк)
  └── request_formatter.py     # Форматирование запросов (138 строк)
```

**Приоритет:** 🟡 P1  
**Оценка:** 2-3 часа

### 6. Оптимизация core компонентов

#### `core/plugin_manager.py` (743 строки)
**Проблема:** Слишком много логики в одном файле

**Рекомендации:**
```python
core/
  ├── plugin_manager.py       # Основной менеджер (300 строк)
  ├── plugin_loader.py        # Загрузка плагинов (200 строк)
  ├── plugin_dependencies.py  # Управление зависимостями (150 строк)
  └── plugin_lifecycle.py     # Lifecycle управление (93 строки)
```

**Приоритет:** 🟡 P1  
**Оценка:** 4-5 часов

---

## 🟠 СРЕДНИЙ ПРИОРИТЕТ

### 7. Удаление неиспользуемого кода

**Проблема:** Возможны неиспользуемые функции и классы

**Методы проверки:**
```bash
# Использовать vulture для поиска неиспользуемого кода
pip install vulture
vulture core/ modules/ plugins/ --min-confidence 80
```

**Приоритет:** 🟠 P2  
**Оценка:** 2-3 часа

### 8. Оптимизация структуры директорий

**Проблемы:**
- `docs/archive/` - 242 файла документации, много дублирования
- `dev-scripts/` - скрипты для разработки, можно вынести в отдельный репозиторий
- `plugins/test/` - тестовые плагины, можно переместить в `tests/fixtures/`

**Рекомендации:**
```
core-runtime-service/
  ├── core/                   # Ядро (без изменений)
  ├── modules/                # Модули (без изменений)
  ├── plugins/                # Плагины (без изменений)
  ├── adapters/               # Адаптеры (без изменений)
  ├── tests/                  # Тесты
  │   ├── fixtures/           # Тестовые плагины (из plugins/test/)
  │   └── ...
  ├── docs/                   # Документация (консолидированная)
  │   └── archive/            # УДАЛИТЬ или переместить в .archive/
  └── scripts/                # Скрипты (из dev-scripts/)
```

**Приоритет:** 🟠 P2  
**Оценка:** 4-6 часов

### 9. Оптимизация зависимостей

**Проблема:** Нет разделения на production и development зависимости

**Рекомендации:**
```txt
# requirements.txt (production)
fastapi>=0.95.0
uvicorn>=0.22.0
aiohttp>=3.10.0
asyncpg>=0.28.0
bcrypt>=4.0.0
PyJWT>=2.8.0
cryptography>=41.0.0
prometheus-client
qrcode[pil]>=7.4.0

# requirements-dev.txt (development)
-r requirements.txt
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
black>=23.0.0
ruff>=0.1.0
mypy>=1.0.0
```

**Приоритет:** 🟠 P2  
**Оценка:** 30 минут

### 10. Добавление инструментов качества кода

**Проблема:** Отсутствуют линтеры и форматтеры

**Рекомендации:**

#### 10.1. Создать `pyproject.toml`
```toml
[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "I", "N", "W", "UP"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.black]
line-length = 100
target-version = ['py311']

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
```

#### 10.2. Создать `.pre-commit-config.yaml`
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

**Приоритет:** 🟠 P2  
**Оценка:** 1-2 часа

---

## 🟢 НИЗКИЙ ПРИОРИТЕТ

### 11. Оптимизация производительности

#### 11.1. Lazy loading модулей
**Проблема:** Все модули загружаются при старте

**Рекомендации:**
```python
# В module_manager.py добавить lazy loading для optional модулей
async def _load_module_lazy(self, module_name: str):
    if module_name not in self._loaded_modules:
        # Загрузить только при первом использовании
        await self._load_module(module_name)
```

#### 11.2. Кэширование результатов
**Проблема:** Нет кэширования для часто используемых данных

**Рекомендации:**
```python
# Добавить кэш для:
# - Plugin metadata
# - Service registry lookups
# - HTTP endpoint registrations
from functools import lru_cache
```

**Приоритет:** 🟢 P3  
**Оценка:** 4-6 часов

### 12. Улучшение документации кода

**Проблема:** Не все функции имеют docstrings

**Рекомендации:**
- Добавить docstrings для всех публичных функций
- Использовать Google или NumPy стиль
- Добавить type hints везде

**Приоритет:** 🟢 P3  
**Оценка:** 8-10 часов

---

## 📋 ПЛАН ДЕЙСТВИЙ

### Неделя 1: Критические исправления
- [ ] Исправить дубликат `asyncpg` в requirements.txt (5 мин)
- [ ] Удалить пустую директорию `plugins/client-manager-service/` (5 мин)
- [ ] Разбить `plugins/oauth_yandex/plugin.py` (4-6 часов)
- [ ] Разбить `plugins/yandex_smart_home/api_client.py` (3-4 часа)

### Неделя 2: Высокий приоритет
- [ ] Оптимизировать импорты (2-3 часа)
- [ ] Разбить `modules/api/module.py` (3-4 часа)
- [ ] Разбить `modules/request_logger/http_client.py` (2-3 часа)
- [ ] Разбить `core/plugin_manager.py` (4-5 часов)

### Неделя 3: Средний приоритет
- [ ] Удалить неиспользуемый код (2-3 часа)
- [ ] Оптимизировать структуру директорий (4-6 часов)
- [ ] Разделить зависимости (30 мин)
- [ ] Добавить инструменты качества кода (1-2 часа)

### Неделя 4: Низкий приоритет
- [ ] Оптимизация производительности (4-6 часов)
- [ ] Улучшение документации (8-10 часов)

---

## 📊 МЕТРИКИ УСПЕХА

### До оптимизации
- Самый большой файл: **1003 строки**
- Файлов >500 строк: **10**
- Файлов >1000 строк: **2**
- Дублирование зависимостей: **1**

### После оптимизации (цель)
- Самый большой файл: **<500 строк**
- Файлов >500 строк: **0**
- Файлов >1000 строк: **0**
- Дублирование зависимостей: **0**
- Test coverage: **>80%**
- Code quality tools: **Настроены**

---

## 🎯 ПРИОРИТЕТЫ

1. **🔴 Критично (P0):** Исправить немедленно
   - Дубликат asyncpg
   - Разбить файлы >1000 строк

2. **🟡 Высокий (P1):** Исправить в течение недели
   - Оптимизация импортов
   - Разбить файлы >500 строк

3. **🟠 Средний (P2):** Исправить в течение месяца
   - Удаление неиспользуемого кода
   - Оптимизация структуры

4. **🟢 Низкий (P3):** Исправить когда будет время
   - Оптимизация производительности
   - Улучшение документации

---

## 📝 ЗАМЕТКИ

- Все изменения должны сопровождаться тестами
- Необходимо обновить документацию после рефакторинга
- Важно сохранить обратную совместимость API
- Все изменения должны проходить CI/CD проверки

---

**Следующие шаги:** Начать с критических исправлений (P0), затем перейти к высокому приоритету (P1).
