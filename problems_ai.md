# Проблемы ядра — актуальное состояние

> Обновлено: 2026-03-24
> Предыдущие фиксы применены: core/trust/ шимы починены, core/adapters/http/ удалён, core/runtime/core.py удалён, modules/ssh/__init__.py создан

---

## АРХИТЕКТУРНОЕ НАРУШЕНИЕ — core импортирует из app

**Файл:** `core/console.py:13`
```python
from app.storage_factory import build_storage_stack
```
Ядро тянет из прикладного слоя. `app/storage_factory.py` сам является ре-экспортом из `modules.storage.factory`.

**Фикс:** заменить на `from modules.storage.factory import build_storage_stack`

---

## ВЫСОКИЙ — мёртвые файлы и директории

### 1. Пустой файл `core/runtime/context.py`
0 байт. Путает с `core/runtime/runtime_context.py`. Смысла нет.

**Фикс:** удалить

### 2. Директории-призраки — только `__pycache__`, ничего больше

- `core/storage_layer/` — пусто, нет `__init__.py`
- `core/secure_storage/` — пусто, нет `__init__.py`

**Фикс:** удалить

### 3. Директории без `__init__.py` с кодом, который нигде не используется

- `core/contracts/event_bus.py` — Protocol-определение `EventBusInterface`, нигде не импортируется
- `core/remote_services/remote_logger.py` — HTTP-сервис, нигде не импортируется
- `core/remote_services/remote_metrics.py` — HTTP-сервис, нигде не импортируется

Вся директория `core/remote_services/` — dead code. HTTP не принадлежит ядру.

**Фикс:** удалить `core/remote_services/` целиком; `core/contracts/` — либо дать `__init__.py` и подключить в архитектуру, либо удалить

---

## СРЕДНИЙ — шимы используются по старым путям (сами собой противоречат)

Шимы существуют чтобы старый код не сломался. Но сам `core/runtime/runtime.py` тоже использует старые пути:

| Файл | Старый путь (используется) | Новый правильный путь |
|------|---------------------------|----------------------|
| `core/runtime/runtime.py:28` | `core.dependency_resolver` | `core.dependency` |
| `core/runtime/runtime.py:44` | `core.runtime.module_manager` | `core.module` |

**Фикс:** обновить импорты в `runtime.py`

---

## СРЕДНИЙ — незавершённая миграция `LegacyRuntimeContext` → `KernelContext`

Два контекста живут параллельно без дедлайна:
- `core/runtime/runtime_context.py` — `LegacyRuntimeContext` (алиас `RuntimeContext`)
- `core/kernel/context.py` — `KernelContext` (целевой)

Модули с fallback-кодом и TODO:
- `core/runtime/runtime.py:277` — `# TODO: migrate to KernelContext`
- `modules/credentials/module.py:123` — `# TODO: remove fallback after full KernelContext migration`
- `modules/monitoring/monitoring_module.py:60` — аналогично
- `modules/marketplace/module.py:232` — аналогично

**Фикс:** принять решение — либо завершить миграцию и удалить `LegacyRuntimeContext`, либо зафиксировать что она не нужна

---

## СРЕДНИЙ — тесты используют устаревшие импорты

Минимум 11 тестовых файлов тянут из шимов вместо новых путей:

```python
# Устаревшие пути в тестах:
from core.dependency_resolver import DependencyResolver, RuntimeIntegrityError
from core.runtime.module_manager import ModuleManager
from core.runtime.module_manager import ModuleSpec
```

Затронуто:
- `tests/test_dependency_resolver.py`
- `tests/test_robustness_p0.py`
- `tests/test_module_manager.py`
- `tests/test_remote_providers.py`
- и ещё ~7 файлов

**Фикс:** перевести на `core.dependency`, `core.module`

---

## СРЕДНИЙ — `reportMissingImports: false` в pyright

`pyrightconfig.json`:
```json
{
    "typeCheckingMode": "basic",
    "reportMissingImports": false,
    "reportOptionalMemberAccess": false,
    "exclude": ["**/plugins/**", "**/tests/**", "**/test_*.py"]
}
```

Именно эта настройка позволила сломанным `core/trust/` шимам жить незамеченными.

**Фикс:** включить `"reportMissingImports": true`, постепенно дотянуть до `strict`

---

## НИЗКИЙ — два файла ошибок хранилища

- `core/storage_errors.py` — `StorageSecurityError`, `StorageConfigurationError`, `NamespaceViolationError`
- `core/storage_exceptions.py` — `StorageCorruptionError`, `StorageRollbackDetected`, `StorageTamperDetected`

Оба активно используются, оба экспортируются из `core/__init__.py`. Нет логики разделения.

**Фикс:** объединить в `core/storage_errors.py`, удалить `core/storage_exceptions.py`

---

## НИЗКИЙ — TODO без действия

`core/runtime/runtime.py:107`:
```python
# TODO: remove modules.plugins.manager shim (backward compat)
```
Висит без привязки к задаче.

**Фикс:** либо сделать, либо удалить комментарий

---

## Порядок фиксов

| Приоритет | Действие | Файл |
|-----------|----------|------|
| 1 | Убрать импорт из app | `core/console.py:13` |
| 2 | Удалить пустые файлы и директории | `core/runtime/context.py`, `core/storage_layer/`, `core/secure_storage/` |
| 3 | Удалить dead code | `core/remote_services/`, `core/contracts/event_bus.py` |
| 4 | Починить импорты в runtime.py | `core/runtime/runtime.py:28,44` |
| 5 | Перевести тесты на новые пути | 11 тестовых файлов |
| 6 | Решить судьбу `LegacyRuntimeContext` | миграция или закрыть тему |
| 7 | Включить `reportMissingImports` | `pyrightconfig.json` |
| 8 | Объединить storage errors | `core/storage_errors.py` + `core/storage_exceptions.py` |

---

## Что уже сделано (не трогать)

| Дата | Фикс |
|------|------|
| 2026-03-24 | `core/trust/` шимы переведены на `modules.security.trust.*` |
| 2026-03-24 | `core/adapters/http/` удалён (HTTP в ядре не нужен) |
| 2026-03-24 | `core/runtime/core.py` удалён (дублирующий мёртвый код) |
| 2026-03-24 | `modules/ssh/__init__.py` создан |
