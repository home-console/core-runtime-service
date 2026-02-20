# Анализ запуска: установка зависимостей плагина и возможное зависание

## 1. Почему не срабатывает автоустановка зависимостей (client_manager)

### Цепочка вызовов при загрузке client_manager

1. **runtime.start()** → `auto_load_plugins()` → для каждого манифеста вызывается  
   **load_plugin_from_manifest()** → создаётся экземпляр плагина → **load_plugin(plugin)** → **plugin.on_load()**.

2. В **on_load()** (standalone-режим) вызывается `importlib.import_module('app.main')` → падает **ImportError** (нет `pydantic_settings`).

3. В блоке **except ImportError** вызывается **\_ensure_plugin_deps()**:
   - если **RUNTIME_INSTALL_PLUGIN_DEPS ≠ "1"** → возвращает `False` → установка не запускается;
   - если **plugins/client-manager-service/requirements.txt** не найден → возвращает `False`;
   - иначе запускается `pip install -r requirements.txt`; при успехе возвращает `True`, при ошибке (сеть, права, таймаут) — `False`.

4. Если **\_ensure_plugin_deps()** вернула **False**, из **on_load()** пробрасывается исключение → плагин не регистрируется, в лог попадает `[WARNING] Ошибка при создании плагина из манифеста`.

### Что проверить

| Причина | Что сделать |
|--------|-------------|
| Переменная не включена | Запускать: `RUNTIME_INSTALL_PLUGIN_DEPS=1 python3 main.py` |
| Нет файла requirements | Убедиться, что есть `plugins/client-manager-service/requirements.txt` (в т.ч. если это submodule — что он подтянут). |
| pip не смог установить | Сеть, прокси, права. Запустить вручную: `pip install -r plugins/client-manager-service/requirements.txt`. |
| Режим integrated | Импорт `app.main` в standalone делается в **on_load()**; в integrated — позже в **on_start()**. Автоустановка сейчас только при ошибке в **on_load()**, т.е. только в standalone. |

### Рекомендация

Для стабильной работы лучше один раз установить зависимости (в т.ч. для плагинов) и не полагаться на установку при старте:

```bash
pip install -r requirements.txt
# при необходимости также:
pip install -r plugins/client-manager-service/requirements.txt
```

---

## 2. Почему после «Плагин 'yandex_smart_home' успешно загружен» процесс «висит»

### Что происходит после последнего сообщения о загрузке

1. Цикл **auto_load_plugins** заканчивается (больше плагинов по порядку зависимостей нет).
2. В **runtime.start()** дальше:
   - `plugins = self.plugin_manager.list_plugins()` — список загруженных (например, 3 плагина);
   - **await self.plugin_manager.start_all()** — последовательный запуск каждого плагина.

3. **start_all()** (plugin_lifecycle):
   - `states = self._registry.get_all_states()` — под **threading.Lock** (коротко);
   - для каждого плагина в состоянии **LOADED** вызывается **await self.start_plugin(plugin_name)**.

4. **start_plugin(plugin_name)**:
   - проверка required capabilities (короткий lock в capability_registry);
   - **await plugin.on_start()** — здесь выполнение может «застрять».

5. После **start_all()** в runtime вызывается **await info(..., "Плагины запущены: ...")** — вызов сервиса логирования. Если этот вызов блокируется (например, ждёт ответа), до следующего лога выполнение не дойдёт.

Итого: зависание возможно либо **в одном из plugin.on_start()** (yandex_device_auth, oauth_yandex, yandex_smart_home), либо **в первом вызове info() после start_all()** (логирование).

### Локи в этой фазе

- **plugin_registry._plugin_lock** (threading.Lock) — берётся только на время чтения списка/состояний и при регистрации, **не** держится на время `await plugin.on_start()`. Дедлока здесь нет.
- **capability_registry._lock** — только на время **validate_plugin_requirements**; после выхода из with lock идёт `await plugin.on_start()`, lock не держится.
- Остальные Lock’и (execution_router, operations/registry, execution backends и т.д.) в момент «загрузка плагинов → start_all» в этой цепочке не участвуют.

То есть «лок» в смысле классического deadlock маловероятен; скорее — **долгий или блокирующий код** в **on_start()** или в **logger.log**.

### Как найти место зависания

1. **Включить отладочные логи**  
   В **core/runtime.py** после `await self.plugin_manager.start_all()` добавить:
   ```python
   print("[Runtime] start_all() плагинов завершён", flush=True)
   ```
   Если эта строка не появляется — зависание внутри **start_all()** (в одном из **on_start()**).

2. **Сузить плагин**  
   В **core/kernel/plugin_lifecycle.py** в **start_plugin** в начале:
   ```python
   print(f"[PluginLifecycle] start_plugin: {plugin_name}", flush=True)
   ```
   и сразу перед `await plugin.on_start()`:
   ```python
   print(f"[PluginLifecycle] calling on_start: {plugin_name}", flush=True)
   ```
   По последнему выводу видно, в каком плагине зависает **on_start()**.

3. **Проверить логирование**  
   Если «start_all() плагинов завершён» есть, а дальше логов нет — смотреть реализацию **info()** / вызов **logger.log** (нет ли там синхронного ожидания или блокирующего I/O).

4. **Asyncio**  
   Запуск с `PYTHONASYNCIODEBUG=1` может показать предупреждения о долгих синхронных участках в event loop.

---

## 3. Краткий чеклист

- **Не ставится pydantic_settings при старте**  
  - Запуск с `RUNTIME_INSTALL_PLUGIN_DEPS=1`.  
  - Наличие `plugins/client-manager-service/requirements.txt`.  
  - Лучше: заранее `pip install -r requirements.txt` (и при необходимости — deps client-manager).

- **После загрузки плагинов «ничего не происходит»**  
  - Скорее всего ожидание в **start_all()** (какой-то **on_start()**) или в первом **info()** после него.  
  - Добавить print’ы по пункту «Как найти место зависания» и повторить запуск.
