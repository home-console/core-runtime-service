# Архитектурный аудит: client-manager

**Дата:** 16 февраля 2026  
**Модель:** HomeConsole (Plugin SDK + Execution Layer + Inspector + Operations)  
**Объект:** плагин `client_manager` и подключаемый `client-manager-service`

---

## 1. Классификация

| Вопрос | Ответ |
|--------|--------|
| **Где лежит client-manager?** | `plugins/client_manager/` (тонкая обёртка) + `plugins/client-manager-service/` (полноценное FastAPI-приложение, импортируемое/запускаемое обёрткой) |
| **Есть ли plugin.json / metadata?** | Да. `plugins/client_manager/plugin.json` — активный манифест. `plugins/client-manager-service/plugin.json` — отключён (`_disabled: true`), legacy. |
| **Наследуется ли от BasePlugin (SDK)?** | Да. `ClientManagerPlugin` наследует `core.base_plugin.BasePlugin` (который наследует `sdk.BasePlugin`). |
| **Тип плагина** | **In-process plugin** с двумя режимами: **integrated** (монтирует роуты и WebSocket в основной API) и **standalone** (запускает uvicorn в отдельном потоке на порту 10000). |
| **Отдельный процесс?** | В режиме standalone — отдельный **поток** (не процесс), тот же процесс Core. Отдельный контейнер/процесс `client-manager` предполагается только при деплое client-manager-service как отдельного сервиса (docker-compose), но текущая кодовая интеграция — in-process. |
| **Набор утилит?** | Нет. Это полноценный плагин с lifecycle и интеграцией в API. |

**Итог классификации:** In-process плагин с опциональным «псевдо-standalone» (поток). Backend plugin: управляет клиентами, WebSocket, REST API; не является «просто утилитой».

---

## 2. Нарушения границ

### 2.1 Импорты

- **modules/*** — плагин **не импортирует** из `modules/`.
- **admin/*** — **не импортирует**.
- **devices/*** — **не импортирует**.
- **Конкретные плагины** — **не импортирует** по имени (yandex, oauth и т.д.).

Импорты ограничены: `core.base_plugin`, код из `plugins/client-manager-service` (через `sys.path` и `from app.*`).

### 2.2 Прямой доступ к модулям (нарушение)

- **`self.runtime.module_manager.get_module("api")`** — плагин получает ссылку на ApiModule и вызывает `main_app.include_router(...)`, `main_app.websocket(...)`.
- В **integrated** режиме маршруты и WebSocket добавляются **напрямую в FastAPI app**, минуя **HttpRegistry**.
- По контракту плагины не должны трогать модули; HTTP — через `runtime.http.register(HttpEndpoint(...))`. ApiModule строит маршруты только из `runtime.http.list()`.

**Вывод:** граница «плагин не лезет в модули» нарушена: прямой доступ к `api` и к `main_app`.

### 2.3 Вызовы service_registry.call()

- Все вызовы — **только** `service_registry.call("logger.log", level=..., message=..., plugin="client_manager")`.
- Это инфраструктурный сервис логирования — допустимо.
- Вызовов по конкретным именам других плагинов (oauth_yandex.*, yandex_smart_home.* и т.д.) **нет**.

### 2.4 Прямые HTTP endpoint’ы

- В **integrated** режиме плагин сам регистрирует REST-роуты и WebSocket на `main_app`, т.е. по сути создаёт «прямые» endpoint’ы, не объявленные в HttpRegistry.
- В **standalone** режиме свой uvicorn слушает порт 10000 — отдельный HTTP-сервер, не идущий через ApiModule/HttpRegistry.

**Итог по границам:** одно явное нарушение — обращение к `module_manager.get_module("api")` и монтирование в `main_app` вместо регистрации через `runtime.http`.

---

## 3. Доменная утечка

### 3.1 В плагине-обёртке (`plugins/client_manager/plugin.py`)

- Нет `if provider == ...`, хардкода интеграций (Yandex/OAuth), знания execution backend, docker/process/scheduler.
- Домен ограничен «режимом работы» (integrated/standalone) и конфигом (host, port, ws_prefix).

### 3.2 В client-manager-service

- **Знание docker/process:** в `app/core/websocket_handlers/admin.py` при установке плагина (`mtype == "docker"`) выполняются `subprocess.run(["docker", "pull", ...])` и `subprocess.run(["docker", "run", ...])`. Это явное знание способа запуска (docker) и выполнение команд на хосте.
- **Execution backend:** плагин не использует общий Execution Layer ядра; установка «плагина» (docker-образа) реализована внутри себя.
- **Scheduler:** явного использования scheduler ядра нет; есть только `asyncio.create_task(_run_install())` для фоновой установки.
- **Yandex/OAuth:** в client-manager-service нет прямых вызовов Yandex/OAuth; есть только JWT для admin WebSocket (`audience='client_manager'`).

**Итог по утечке:** доменная утечка есть **в client-manager-service**: знание docker и subprocess, собственная логика «установки плагина» вместо единого Execution Layer.

---

## 4. Lifecycle

| Элемент | Наличие |
|---------|---------|
| **on_load** | Да. Режим (integrated/standalone), sys.path, в standalone — создание app и попытка получить handler. |
| **on_start** | Да. Запуск integrated (монтирование роутов + WebSocket) или standalone (uvicorn в потоке), затем регистрация сервисов. |
| **on_stop** | Да. Остановка сервера/потока или cleanup handler. |
| **on_unload** | Да. Unregister сервисов, обнуление ссылок. |
| **Регистрация services** | Да. `client_manager.get_clients`, `client_manager.get_client_info` через `service_registry.register`. |
| **Регистрация operations** | **Нет.** Плагин не регистрирует обработчики в `runtime.operations`. |
| **Capabilities (platform)** | **Нет.** В `PluginMetadata` не заданы `capabilities_provided` / `capabilities_required`. |

Lifecycle SDK соблюдён (on_load/on_start/on_stop/on_unload), но плагин не участвует в платформенных Operations и не объявляет capabilities.

---

## 5. Совместимость с Execution Layer

- **Выполнять операции через execution backend?** — Нет. Плагин не регистрирует типы операций в `runtime.operations`; свои «действия» (команды клиентам, установка образов) выполняет сам, не через OperationManager/Execution.
- **Запускать в container?** — Теоретически client-manager-service можно вынести в отдельный контейнер и вызывать по HTTP (как remote plugin), но текущий код рассчитан на in-process/поток.
- **Запускать в process?** — Да, текущая модель — один процесс Core + поток uvicorn (standalone) или монтирование в тот же процесс (integrated).
- **Жёстко in-process?** — По коду — да: либо общий процесс + общий app, либо общий процесс + отдельный поток. Нет протокола «remote plugin» и вызова execution backend для запуска в контейнере/процессе.

**Итог:** с Execution Layer плагин не интегрирован; выполнение «операций» локальное, внутри себя (в т.ч. docker через subprocess).

---

## 6. Совместимость с Flutter / Inspector / Operations

- **Удалить plugin и Flutter не сломается?** — Зависит от Flutter: если UI завязан на `/api/client-manager/*` и WebSocket `/client-manager/ws`, то отключение плагина уберёт эти endpoint’ы и функциональность пропадёт. Архитектурно «удалить плагин = меньше данных/действий» — нормально; важно, чтобы не было жёстких проверок «если плагин X загружен» в коде ядра/Inspector.
- **Добавить plugin и Flutter автоматически увидит через Inspector?** — Частично. Inspector читает `plugin_manager`, `service_registry.list_services()`, `http.list()` и т.д. Сервисы `client_manager.get_clients` и `client_manager.get_client_info` появятся в списке сервисов. Но маршруты, добавленные напрямую в `main_app`, **не** проходят через `runtime.http`, поэтому **не** попадут в Inspector как зарегистрированные HTTP endpoint’ы — это расхождение с моделью.
- **Управлять plugin через Operations?** — Нет. Плагин не регистрирует операции; управление (старт/стоп/установка) через Operations невозможно, только через собственные REST/WebSocket API.

**Итог:** для Flutter плагин «виден» как список плагинов и сервисов, но не как полноправный участник HttpRegistry и Operations, поэтому автоматическое отображение в Inspector по единому контракту нарушено.

---

## 7. Терминал и UI

- Терминал — **UI**. В документации указано: плагины расширяют Operations, Inspector snapshot, Flows, Integrations; терминал их отображает.
- В client-manager-service есть роут **Terminal** (`app/routes/terminal.py`) — это backend API для функциональности терминала (команды, сессии). То есть плагин даёт **backend-возможности** (операции с клиентами, команды), а не «управляет UI напрямую». Если Flutter/терминал только вызывает API плагина — это соответствует модели «плагины расширяют backend, UI отображает».
- Прямого управления виджетами/экранами Flutter из плагина в коде **нет**.

---

## 8. Итоговые выводы

### 8.1 Архитектурный статус: **Partial (частичное соответствие)**

- Плагин использует BasePlugin, lifecycle, storage, service_registry (сервисы и logger), но:
  - нарушает границу модулей (доступ к ApiModule и main_app);
  - не использует HttpRegistry для API;
  - не регистрирует operations и не объявляет capabilities;
  - client-manager-service содержит доменную утечку (docker/subprocess, своя установка).

### 8.2 Нарушения (кратко)

1. **Граница модулей:** `module_manager.get_module("api")` и монтирование роутов/WebSocket в `main_app` вместо `runtime.http.register`.
2. **HttpRegistry:** REST и WebSocket client-manager не объявлены в HttpRegistry; ApiModule их не видит; Inspector не показывает их как зарегистрированные endpoint’ы.
3. **Operations:** нет регистрации обработчиков операций — нельзя управлять через единый Operations/Execution.
4. **Capabilities:** не объявлены в metadata.
5. **client-manager-service:** знание docker/subprocess и своя логика установки плагинов вместо Execution Layer.

### 8.3 Что нужно переделать

1. Убрать прямой доступ к ApiModule: не вызывать `get_module("api")` и не делать `main_app.include_router` / `main_app.websocket` из плагина.
2. Регистрировать REST-контракты через `runtime.http.register(HttpEndpoint(...))` с сервисами вида `client_manager.*` и реализацией в плагине через `service_registry.call("client_manager.*", ...)`. WebSocket платформа пока не описывает в HttpRegistry — либо расширить контракт (отдельный реестр/вид endpoint’а), либо оставить WebSocket как исключение с явным документированием.
3. Зарегистрировать типы операций (например, `client_manager.send_command`, `client_manager.install`) в `runtime.operations` и выполнять их через handler’ы, по возможности делегируя в Execution Layer длительные/внешние задачи.
4. В metadata указать `capabilities_provided` / `capabilities_required` при наличии зависимостей от других плагинов.
5. В client-manager-service: вынести установку docker-образов в вызов Execution Layer (или отдельный сервис ядра), убрать прямые `subprocess` для docker.

### 8.4 Можно ли сделать его чистым Plugin SDK?

- **Да**, при условии:
  - все HTTP — через `runtime.http.register`;
  - WebSocket — либо через будущий контракт платформы, либо оформлен как исключение;
  - операции — через `runtime.operations`;
  - зависимости — через capabilities;
  - без доступа к `module_manager` и к `main_app`.
- Тогда плагин будет «чистым» с точки зрения SDK: только runtime API (storage, state, service_registry, http, operations, event_bus) и lifecycle.

### 8.5 Нужно ли переписывать?

- **Полная переписка не обязательна.** Текущая реализация уже на BasePlugin и lifecycle; логика client-manager-service (клиенты, WebSocket, команды) может остаться.
- **Нужна адаптация:** переход с монтирования в main_app на HttpRegistry, добавление operations и capabilities, отказ от прямого доступа к модулям и от своей логики docker/subprocess в пользу Execution Layer.

### 8.6 Минимальный план миграции

| Шаг | Действие | Оценка |
|-----|----------|--------|
| 1 | Описать все REST endpoint’ы client-manager как `HttpEndpoint` и регистрировать их в `on_load` через `runtime.http.register`, реализацию перенести в сервисы (или прокси в существующие роуты через один общий сервис). | 4–8 ч |
| 2 | Решить, как в Inspector/OpenAPI показывать WebSocket (расширение HttpRegistry или отдельный реестр / документ). Пока оставить WebSocket монтирование через модуль API по согласованию (временное исключение) или вынести в отдельный «mount» в ApiModule по конфигу. | 2–4 ч |
| 3 | Убрать вызов `module_manager.get_module("api")` и прямое `main_app.include_router`. После шага 1 маршруты должны браться из `http.list()`. | 1–2 ч |
| 4 | Зарегистрировать в `runtime.operations` несколько ключевых типов операций (например, `client_manager.send_command`, `client_manager.get_clients`) и реализовать handler’ы. | 2–4 ч |
| 5 | Добавить в metadata `capabilities_provided` / `capabilities_required` при необходимости. | 0.5 ч |
| 6 | В client-manager-service заменить прямой docker/subprocess в admin установке на вызов Execution Layer (или завести операцию `execution.run_container` и вызывать её через `runtime.operations` или `runtime.service_registry`). | 4–8 ч |

**Общая оценка:** порядка 14–26 часов в зависимости от глубины рефакторинга WebSocket и Execution.

---

## 9. Вариант по результатам аудита

- **Вариант A (почти правильный)** — не подходит: есть нарушения границ и отсутствие Operations/HttpRegistry.
- **Вариант B (сервис → Remote Plugin)** — возможен как эволюция: вынести client-manager-service в отдельный процесс/контейнер и общаться по HTTP по контракту Remote Plugin; тогда Core остаётся без прямого монтирования и без потока uvicorn.
- **Вариант C (переписать под Plugin SDK)** — не обязателен; достаточно **адаптации** (Вариант A после доработок): привести к HttpRegistry + Operations + capabilities и убрать доступ к модулям и docker/subprocess в коде сервиса.

**Рекомендация:** считать текущий статус **Partial** и выполнить минимальный план миграции выше, с приоритетом на шаги 1–3 (HttpRegistry, отказ от доступа к api-модулю), затем 4–6 (Operations, capabilities, Execution для установки).
