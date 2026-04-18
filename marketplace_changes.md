# Что нужно изменить в core-runtime-service для маркетплейса

> Дата: 2026-04-18  
> Это изменения в **существующем** проекте, не в новом marketplace-api

## Статус (пройдено по коду)

| # | Статус | Где смотреть |
|---|--------|--------------|
| 1 | ✅ | `core/runtime/config.py`, `modules/marketplace/services.py` |
| 2 | ✅ | `modules/marketplace/catalog.json` удалён |
| 3 | ✅ | `modules/marketplace/services.py` — `handle_check_updates`, `except Exception as e` |
| 4 | ✅ | `modules/marketplace/registry_client.py` — `MARKETPLACE_ALLOW_LOCALHOST` |
| 4b | ✅ | Кэш индекса реестра **по URL** (подкаталог `registry-<sha256(url)>`), иначе разные `registry_url` затирали один `registry-index.json` |
| 5 | ✅ | Регистрация HTTP в `modules/marketplace/module.py` + хендлеры `modules/marketplace/admin_services.py` (не отдельный `modules/api/routers/marketplace.py`) |
| 6 | ✅ | Async-хелперы `_storage_get` / `_storage_set` в `modules/marketplace/services.py` |
| 7 | ✅ | `modules/marketplace/installer.py` + `Config.runtime_version` / `RUNTIME_VERSION` |
| 8 | ✅ | `modules/marketplace/transaction.py` — rollback и best-effort `start_plugin` |
| 9 | ✅ | `modules/marketplace/services.py` — `handle_update_all` через `transaction_mgr` |
| 10 | ✅ | `tests/marketplace/test_marketplace_install_from_registry_e2e.py` |

---

## 1. Захардкоженный registry_url везде — ГЛАВНАЯ ПРОБЛЕМА

**Статус:** ✅ сделано.

**Проблема:** `registry_url` передаётся как параметр операции при каждом вызове. Нет дефолтного registry.

```python
# Сейчас — нужно указывать URL при каждом вызове
await runtime.operations.dispatch("marketplace.install_from_registry", {
    "plugin_name": "yandex-oauth",
    "registry_url": "https://...",   # ← каждый раз вручную
})
```

**Что сделать:** добавить `MARKETPLACE_REGISTRY_URL` в конфиг/env и использовать как дефолт.

```python
# core/runtime/config.py — добавить поле
marketplace_registry_url: str = ""  # https://marketplace.homeconsole.dev/registry/index.json
```

```python
# modules/marketplace/services.py — в handle_install_from_registry
registry_url = params.get("registry_url") or self.runtime.config.marketplace_registry_url
if not registry_url:
    return {"status": "failure", "error": "registry_url not configured"}
```

**Файлы:** `core/runtime/config.py`, `modules/marketplace/services.py`

---

## 2. `catalog.json` — пустой файл без смысла

**Статус:** ✅ сделано (файл удалён).

**Файл:** `modules/marketplace/catalog.json`

```json
[]
```

Файл пустой и нигде не используется. Либо удалить, либо это артефакт начальной задумки когда каталог был локальным.

**Что сделать:** удалить файл, он создаёт ложное впечатление что каталог где-то локально хранится.

---

## 3. `handle_check_updates` — баг с переменной исключения

**Статус:** ✅ сделано.

**Файл:** `modules/marketplace/services.py:621-622`

```python
except Exception:
    logger.warning("...: failed to check updates for plugin %s: %s", plugin_name, exc_info=True)
    #                                                               ^^^
    # Здесь передаётся exc_info=True но второй %s не будет заполнен
    # Потому что переменная исключения не захвачена (except Exception: без "as e")
```

**Что сделать:**
```python
except Exception as e:
    logger.warning("handle_check_updates: failed for plugin %s: %s", plugin_name, e, exc_info=True)
```

---

## 4. `RegistryClient` — SSRF блокирует localhost и внутренние сети

**Статус:** ✅ сделано. Дополнительно: кэш скачанного `index.json` разнесён по подкаталогам от хэша полного `registry_url`, чтобы не смешивать индексы разных серверов при «свежем» TTL.

**Файл:** `modules/marketplace/registry_client.py:144-160`

SSRF-защита запрещает `localhost`, `127.*`, `192.168.*` и т.д.  
Это правильно для продакшна, но **ломает локальную разработку** когда хочешь поднять marketplace-api на localhost и потестировать связку.

**Что сделать:** добавить env-флаг для отключения SSRF-проверки в dev-режиме.

```python
# modules/marketplace/registry_client.py
import os

@staticmethod
def _validate_registry_url(url: str):
    if not url.startswith("https://") and not url.startswith("http://"):
        raise RegistrySecurityError("Registry URL must be HTTP(S)")
    
    # Пропускаем SSRF-проверку в dev-режиме
    if os.getenv("MARKETPLACE_ALLOW_LOCALHOST", "false").lower() == "true":
        return
    
    if not url.startswith("https://"):
        raise RegistrySecurityError("Registry URL must be HTTPS only")
    
    # ... остальные SSRF-проверки
```

```env
# .env (только для разработки!)
MARKETPLACE_ALLOW_LOCALHOST=true
```

---

## 5. Нет эндпоинта в API для операций маркетплейса

**Статус:** ✅ сделано. Маршруты объявлены при регистрации модуля маркетплейса (`modules/marketplace/module.py`), обработчики — `modules/marketplace/admin_services.py`. Отдельный файл `modules/api/routers/marketplace.py` в проекте не обязателен, если тот же контракт `/admin/v1/marketplace/*` уже выставлен.

**Проблема:** все marketplace-операции (`marketplace.install`, `marketplace.install_from_registry` и т.д.) доступны только через internal operations dispatcher. Нет HTTP-эндпоинта.

Нельзя сделать `curl POST /admin/marketplace/install` — такого роута нет.

**Что сделать:** добавить роутер в `modules/api/`.

```
modules/api/routers/marketplace.py   ← новый файл

POST /admin/v1/marketplace/install
POST /admin/v1/marketplace/install-from-registry
POST /admin/v1/marketplace/remove
POST /admin/v1/marketplace/update
POST /admin/v1/marketplace/enable/{plugin_name}
POST /admin/v1/marketplace/disable/{plugin_name}
GET  /admin/v1/marketplace/installed
GET  /admin/v1/marketplace/updates
```

Без этого маркетплейс работает только программно изнутри, не через внешний вызов.

---

## 6. `_store_installed_plugin` — синхронный `storage.set` в async методе

**Статус:** ✅ сделано — обращение к storage идёт через async `_storage_get` / `_storage_set` (namespace + fallback на legacy-ключи).

**Файл:** `modules/marketplace/services.py:386-404`

```python
def _store_installed_plugin(self, plugin_info: Dict[str, Any]) -> None:
    ...
    self.storage.set("marketplace.installed", installed)  # синхронный вызов
```

Метод синхронный, но вызывается из async контекста. Если storage будет async (PostgreSQL адаптер) — это сломается.

**Что сделать:** переделать в async или явно задокументировать что storage должен быть sync-only для marketplace.

---

## 7. Нет валидации `min_runtime_version` при установке

**Статус:** ✅ сделано — проверка в `MarketplaceInstaller.install_from_file` против версии runtime из конфига.

**Проблема:** поле `min_runtime_version` существует в концепции (в `plugin.json` плагинов), но `MarketplaceInstaller` не проверяет совместимость с текущей версией runtime перед установкой.

**Файл:** `modules/marketplace/installer.py`

**Что сделать:**
```python
# В install_from_file, после парсинга plugin.json
min_runtime = plugin_json.get("min_runtime_version")
if min_runtime:
    current = getattr(runtime, "version", "0.0.0")
    if not semver_satisfies(current, f">={min_runtime}"):
        raise InstallerError(
            f"Plugin requires runtime >={min_runtime}, current={current}"
        )
```

---

## 8. `UpdateTransactionManager` — rollback не восстанавливает активные плагины

**Статус:** ✅ сделано.

**Файл:** `modules/marketplace/transaction.py`

При неудачном обновлении плагина транзакция откатывается (файлы восстанавливаются), но плагин не перезапускается автоматически в plugin_manager.

**Что сделать:** в rollback-логике вызывать `plugin_manager.start_plugin(plugin_name)` если плагин был активен до обновления.

---

## 9. `handle_update_all` — обновляет без backup

**Статус:** ✅ сделано — по-плагинный сценарий через `UpdateTransactionManager` (stage / swap / commit, rollback при ошибке).

**Файл:** `modules/marketplace/services.py:633-709`

`handle_update_all` вызывает `installer.install_from_url` для каждого плагина, но не использует `UpdateTransactionManager` (который есть в `self.transaction_mgr`).  
Если обновление одного плагина упадёт — предыдущие уже обновлены, откат не происходит.

**Что сделать:** обернуть весь цикл обновлений в транзакцию или хотя бы использовать `transaction_mgr` для каждого плагина.

---

## 10. Нет интеграционного теста для полного цикла install_from_registry

**Статус:** ✅ сделано — `tests/marketplace/test_marketplace_install_from_registry_e2e.py` (локальный HTTPS-реестр, `install_from_registry`, загрузка плагина, storage).

**Проблема:** есть unit-тесты для отдельных компонентов, но нет теста:
```
RegistryClient.resolve() → installer.install_from_url() → plugin_manager.load() → storage.set()
```

После деплоя marketplace-api это надо проверить end-to-end хотя бы один раз вручную, и желательно зафиксировать как интеграционный тест.

---

## Приоритет изменений

| # | Изменение | Важность | Сложность | Статус |
|---|-----------|----------|-----------|--------|
| 1 | Дефолтный `registry_url` из конфига | ВЫСОКАЯ | Низкая | ✅ |
| 5 | HTTP-роутер для marketplace операций | ВЫСОКАЯ | Средняя | ✅ |
| 4 | SSRF dev-флаг для localhost | ВЫСОКАЯ | Низкая | ✅ |
| 3 | Баг с переменной исключения | СРЕДНЯЯ | Минуты | ✅ |
| 7 | Проверка min_runtime_version | СРЕДНЯЯ | Средняя | ✅ |
| 2 | Удалить пустой catalog.json | НИЗКАЯ | Минуты | ✅ |
| 6 | Async storage в marketplace | НИЗКАЯ | Высокая | ✅ |
| 8 | Rollback + перезапуск плагина | НИЗКАЯ | Средняя | ✅ |
| 9 | handle_update_all с транзакцией | НИЗКАЯ | Средняя | ✅ |
| 10 | Интеграционный тест | НИЗКАЯ | Средняя | ✅ |
