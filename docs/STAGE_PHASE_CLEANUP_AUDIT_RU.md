# Аудит stage/phase/step-маркеров и план удаления

Дата аудита: 28 марта 2026

## 1. Цель
Убрать из production-кода служебные маркеры разработки (`Step`, `Stage`, `Phase`) и связанную “этапную” семантику, чтобы код оставался нейтральным, переносимым и поддерживаемым.

## 2. Текущее состояние (по grep)
- `core` (без `docs`) по ключам `Step|Stage|phase|Phase|stage`: **0 совпадений**.
- `modules/plugins/app/sdk/main.py` (без `docs` и `README`): **109 совпадений**.
- Основные кластеры:
  - `modules/credentials/*`: 58
  - `modules/marketplace/*`: 22
- `modules/security/*`: 13
- `modules/agent/*`: 8
- `modules/storage/*`: 7

## 3. Что уже вычищено в этой итерации
- Из `core/operations/worker.py` удалены поля `stage` из hook context.
- Из `modules/logger/module.py` убраны поля `stage` в логировании execution hooks.
- Удалены `Step`-маркеры из core-комментариев/докстрингов:
  - `core/runtime/runtime.py`
  - `core/kernel/base_plugin.py`
  - `core/capability_protocol.py`
  - `core/foundation/__init__.py`
  - `core/observability/*`
  - `core/audit/*`
- Локально дочищен `plugins/yandex_smart_home/command_handler.py` и `commands/*`:
  прямые прокидывания `service_registry/event_bus/storage` убраны, используется тонкий runtime API.

## 4. План удаления остатков (без переписывания архитектуры)
1. Удалить `Step/Stage/Phase` из production-комментариев и докстрингов в `modules/*` и `plugins/*`.
2. Сохранить только реальные доменные state machine названия (например enum-статусы), но убрать “этапные” пояснения в стиле roadmap.
3. Очистить тесты/документацию отдельным коммитом (можно позже, после production-кода).
4. Добавить CI-проверку, запрещающую новые `Step/Stage/Phase` в `core` и в production-слоях.

## 5. Команды контроля
- Проверка ядра (должно быть 0):
  `rg -n "\\bStep\\b|\\bStage\\b|\\bphase\\b|\\bPhase\\b|\\bstage\\b" core --glob '!**/docs/**'`
- Проверка production-слоёв:
  `rg -n "\\bStep\\b|\\bStage\\b|\\bphase\\b|\\bPhase\\b|\\bstage\\b" modules plugins app sdk main.py --glob '!**/docs/**' --glob '!**/README.md'`

## 6. Приоритет
- P0: `core` (уже 0, держим инвариант).
- P1: `modules/credentials`, `modules/marketplace`, `modules/security`.
- P2: `modules/agent`, `modules/storage`, `plugins`.
