# Аудит документации — Полный отчёт

**Дата:** 2026-01-09  
**Статус:** Диагностика завершена, план стабилизации готов

---

## Диагноз: Критические проблемы

### 1. Раздвоение источника истины (P0)

**Проблема:** Множественные документы описывают архитектуру без чёткой иерархии:
- `ARCHITECTURE.md` — инварианты и контракты (canonical, но неполный)
- `OVERVIEW.md` — обзор для новичков (дублирует README)
- `00-README.md` — entry point (хороший, но ссылается на несуществующие документы)
- `README.md` — дубликат entry point

**Конфликт:** Неясно, какой документ является источником истины. `ARCHITECTURE.md` содержит актуальную информацию, но не маркирует stable/unstable части.

**Следствие:** При изменении архитектуры придётся синхронизировать 4+ файла вручную → неизбежная рассинхронизация.

**Решение:** 
- Объединить и стабилизировать `ARCHITECTURE.md` → `01-ARCHITECTURE.md` (canonical)
- `00-README.md` → единственный entry point (обновить ссылки)
- `OVERVIEW.md` → удалить или переместить в archive
- `README.md` → удалить (дубликат)

---

### 2. Отсутствие маркировки stable/unstable (P0)

**Проблема:** Документы не маркируют статус информации:
- Какие контракты stable?
- Какие решения transitional?
- Что экспериментально?

**Где проблема:**
- `ARCHITECTURE.md` не указывает, что HttpRegistry — transitional
- `CORE_RUNTIME_CONTRACT.md` существует, но очень краткий
- Нет явного указания на experimental части (remote plugins)

**Следствие:** Невозможно понять, на что можно полагаться. Разработчики боятся менять код, потому что неясны границы стабильности.

**Решение:**
В каждом каноническом документе добавить секцию:
```markdown
## Статус этого документа

- **Версия:** 0.2.0
- **Статус:** Stable | Transitional | Experimental
- **Последнее изменение:** 2026-01-09
- **Следующий ревью:** 2026-02-01
```

---

### 3. Yandex-документы доминируют в навигации (P1)

**Проблема:** 3 документа о Yandex интеграции в корне docs/:
- `YANDEX_REAL_INTEGRATION.md`
- `YANDEX_BEST_PRACTICES.md`
- `YANDEX_CODE_EXAMPLES.md`

**Конфликт:** Integration-специфичная документация занимает 30% docs/ и создаёт ложное впечатление, что система — это "Yandex умный дом".

**Следствие:** Новые разработчики думают, что Core привязан к Yandex. Архитектурные принципы теряются в vendor-specific деталях.

**Решение:**
- Создать `integrations/yandex/` поддиректорию
- Перенести все Yandex документы туда
- В корневом INDEX оставить только одну ссылку "Пример интеграции: Yandex"
- Добавить generic integration guide: "Как интегрировать vendor API"

---

### 4. Дублирование entry points (P1)

**Проблема:** 4 файла претендуют на роль "начни здесь":
- `docs/00-README.md` — основная документация (297 строк)
- `docs/INDEX.md` — навигация (253 строки)
- `docs/QUICKSTART.md` — быстрый старт
- `docs/README.md` — дубликат

**Конфликт:** Неясно, куда идти новичку. README.md философский, INDEX.md навигационный, QUICKSTART практический.

**Решение:**
- `docs/00-README.md` — единственный entry point (обновить, убрать ссылки на несуществующие документы)
- `docs/01-QUICKSTART.md` — переименовать из QUICKSTART.md, runnable шаги (100 строк)
- `docs/INDEX.md` → удалить или переместить в archive (навигация уже есть в 00-README.md)

---

### 5. Отсутствие contracts registry (P1)

**Проблема:** События и сервисы разбросаны по коду. Нет единого реестра контрактов.

**Где искать:**
- `devices.*` сервисы — в modules/devices
- `internal.*` события — нигде не задокументированы
- `external.*` события — упоминаются в примерах
- `yandex.*` сервисы — в plugins/yandex_smart_home_real.py

**Следствие:** Разработчик плагина не знает, какие контракты доступны. Нарушение DRY: контракты живут только в коде.

**Решение:**
- Создать `06-CONTRACTS.md`:
  - Таблица всех сервисов: имя, signature, owner (module/plugin), status
  - Таблица всех событий: имя, payload schema, semantics, status
  - Автогенерация из кода (опционально, будущее)

---

### 6. Неполный CORE_RUNTIME_CONTRACT.md (P1)

**Проблема:** `CORE_RUNTIME_CONTRACT.md` существует, но содержит только негативные гарантии.

**Отсутствует:**
- Lifecycle гарантии (что Core делает при shutdown?)
- Error handling (что происходит при exception в plugin?)
- Threading model (asyncio event loop гарантии)
- Performance характеристики (latency, throughput)
- Storage → StateEngine mirroring (как это работает?)

**Решение:**
Дополнить CORE_RUNTIME_CONTRACT.md позитивными гарантиями и operational semantics.

---

### 7. Отсутствие Developer Guide (P2)

**Проблема:** `00-README.md` ссылается на `05-DEVELOPER-GUIDE.md`, но файл не существует.

**Отсутствует:**
- Структура проекта (есть FILE_STRUCTURE.md, но не developer guide)
- Правила разработки (naming, code style, testing)
- Процесс контрибьюции
- Как добавлять новые компоненты

**Решение:**
- Создать `05-DEVELOPER-GUIDE.md` на основе FILE_STRUCTURE.md + правила разработки

---

### 8. Отсутствие Operations Guide (P2)

**Проблема:** Нет документации по эксплуатации.

**Отсутствует:**
- Как запускать в production
- Environment variables
- Deployment
- Monitoring
- Troubleshooting

**Решение:**
- Создать `07-OPERATIONS.md` (если нужно)

---

## Предлагаемая каноническая структура

```
core-runtime-service/docs/
├── 00-README.md                    ← единственный entry point
├── 01-ARCHITECTURE.md              ← source of truth (инварианты, контракты)
├── 02-MODULES-AND-PLUGINS.md      ← когда module vs plugin (✅ уже есть)
├── 03-QUICKSTART.md                ← runnable шаги (переименовать из QUICKSTART.md)
├── 04-CORE-RUNTIME-CONTRACT.md    ← гарантии, semantics, limitations (переименовать)
├── 05-DEVELOPER-GUIDE.md          ← структура кода, правила разработки (создать)
├── 06-CONTRACTS.md                 ← реестр сервисов и событий (создать)
├── 07-OPERATIONS.md                ← как запускать, env, deploy (создать, если нужно)
├── 08-TESTING.md                   ← как запускать тесты, smoke scripts (создать, если нужно)
├── 99-TODO.md                      ← roadmap (переименовать из TODO.md)
│
├── integrations/                   ← vendor-specific guides
│   └── yandex/
│       ├── README.md               ← обзор интеграции
│       ├── REAL_INTEGRATION.md     ← из YANDEX_REAL_INTEGRATION.md
│       ├── BEST_PRACTICES.md       ← из YANDEX_BEST_PRACTICES.md
│       └── CODE_EXAMPLES.md       ← из YANDEX_CODE_EXAMPLES.md
│
└── archive/                        ← transitional/historical
    ├── OVERVIEW.md                 ← переместить
    ├── README.md                    ← переместить (дубликат)
    ├── INDEX.md                     ← переместить (навигация в 00-README.md)
    └── FILE_STRUCTURE.md            ← переместить (информация в 05-DEVELOPER-GUIDE.md)
```

---

## Приоритеты выполнения

### Этап 1 (сейчас): Создать источники истины
- [x] Создать `00-AUDIT-COMPLETE.md` (этот файл)
- [ ] Обновить `00-README.md` (убрать ссылки на несуществующие документы)
- [ ] Стабилизировать `ARCHITECTURE.md` → `01-ARCHITECTURE.md` (добавить статусы)
- [ ] Переименовать `QUICKSTART.md` → `03-QUICKSTART.md`
- [ ] Переименовать `CORE_RUNTIME_CONTRACT.md` → `04-CORE-RUNTIME-CONTRACT.md`
- [ ] Дополнить `04-CORE-RUNTIME-CONTRACT.md` (lifecycle, error handling)

### Этап 2 (следующий): Реорганизация
- [ ] Создать `integrations/yandex/` и перенести документы
- [ ] Создать `06-CONTRACTS.md` (ручной реестр)
- [ ] Создать `05-DEVELOPER-GUIDE.md` (на основе FILE_STRUCTURE.md)
- [ ] Переименовать `TODO.md` → `99-TODO.md`

### Этап 3 (затем): Очистка
- [ ] Переместить устаревшие файлы в `archive/`
- [ ] Добавить статус в каждый документ
- [ ] Обновить все внутренние ссылки

---

## Что стало яснее после аудита

1. **Архитектура задокументирована неполно:** есть описание компонентов, но нет чёткого объяснения boundaries и responsibilities.
2. **Transitional состояние не маркировано:** HttpRegistry, remote plugins, integrations — неясен статус.
3. **Yandex доминирует в навигации:** создаёт ложное впечатление о назначении системы.
4. **Modules vs Plugins:** хорошо задокументировано в `02-MODULES-AND-PLUGINS.md`, но не интегрировано в общую навигацию.

## Где остаётся неопределённость

1. **Remote plugins:** `REMOTE_PLUGIN_CONTRACT.md` описывает идею, но непонятен статус — это plan или implemented?
2. **HTTP contracts:** HttpRegistry упоминается в ARCHITECTURE, но нет примеров использования и best practices.
3. **Security model:** OAuth токены, secrets — как хранить? Как rotировать? Документация молчит.
4. **StateEngine mirroring:** Как работает автоматическое зеркалирование Storage → StateEngine? Нужна документация.

---

## Следующий шаг

Начать с Этапа 1: обновить entry point и стабилизировать архитектурный документ.

