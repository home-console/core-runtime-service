# CORE ARCHITECTURE REFACTOR PLAN v2 (адаптирован под текущий репозиторий)

## 1) Быстрая оценка исходного плана

Исходный план в целом правильный по направлению, но в текущем состоянии репозитория его нельзя выполнять «в лоб».

Что корректно:
- Целевая модель `core -> modules -> plugins`.
- Вынос бизнес-домена из `core` в `modules`.
- Упор на единый execution-слой.

Что опасно при прямом переносе:
- `core/runtime/runtime.py` напрямую импортирует и хранит компоненты агентов (`core.agent.*`).
- В `modules/*` много прямых импортов из `core.credentials`, `core.agent`, `core.marketplace`.
- Legacy-слой remote/execution (`core/execution_router.py`, `core/remote_executor.py`, `core/remote_provider.py`) все еще используется в `core/operations/executor.py` и тестах.
- `modules/admin/services/ssh_terminal.py` и `modules/ssh/ssh_execution_service.py` дублируют execution-ответственность.

Ключевой вывод: сначала совместимость и адаптеры, потом перенос файлов, и только потом удаление legacy.

---

## 2) Зафиксированные факты из кода (для планирования)

- Runtime зависит от agent-слоя:
  - `core/runtime/runtime.py` импортирует `AgentEnrollmentManager`, `AgentRegistry`, `MTLSCertificateAuthority`.
- Модули зависят от домена в `core`:
  - `modules/agent/module.py` импортирует `core.agent.*` и `core.agents.*`.
  - `modules/credentials/*` и `modules/admin/credentials_handlers.py` импортируют `core.credentials.*`.
  - `modules/marketplace/services.py` импортирует `core.marketplace.*`.
- Execution уже частично централизован:
  - `modules/execution/module.py` поднимает `ExecutionControllerImpl`.
  - Но `core/operations/executor.py` все еще использует `RemoteOperationExecutor` из `core/remote_executor.py`.
- В `core` сохраняются плоские legacy-файлы (`config.py`, `health_monitor.py`, `logger_helper.py`, `service_registry.py`, `execution_router.py`, `remote_executor.py`, `remote_provider.py`, и часть `storage*.py`).

---

## 3) Целевой результат v2

После миграции:
- `core` = инфраструктурный runtime-engine без продуктовой доменной логики.
- `modules` = бизнес-контур (agents, credentials, marketplace, operations, admin, api и т.д.).
- `plugins` = расширения через публичные API.
- Execution — единственный слой выполнения (локально/процесс/контейнер/SSH/remote-capability).
- Legacy-обертки удалены только после прохождения тестов и import-гейтов.

---

## 4) План 2: поразделно и максимально подробно

## раздел 0. Baseline и защита от регрессий

Цель:
- Зафиксировать рабочую точку перед крупным переносом.

Шаги:
1. Сделать checkpoint commit.
2. Запустить базовый smoke-набор:
   - `pytest -v tests/test_runtime_module_contract.py`
   - `pytest -v tests/test_dependency_resolver.py`
   - `pytest -v tests/test_agent_enrollment.py tests/test_agent_deploy.py`
   - `pytest -v tests/test_credential_repository.py tests/test_credential_rbac.py`
   - `pytest -v tests/test_marketplace*.py`
3. Отдельно прогнать legacy-критичные тесты:
   - `pytest -v tests/test_plugin_isolation.py tests/test_remote_providers.py tests/test_capability_protocol.py`
4. Сохранить результаты (текстом в commit message или в notes).

Done:
- Все baseline-тесты зафиксированы.
- Есть быстрый rollback.

---

## раздел 1. Архитектурные гейты (без перемещения файлов)

Цель:
- Включить «сигнализацию» перед переносом.

Шаги:
1. Добавить проверки импорт-правил в CI/скрипт:
   - В `core` запрещены runtime-импорты из `modules` (исключение: TYPE_CHECKING допускается временно).
   - В `modules` временно разрешены импорты из `core.agent|core.credentials|core.marketplace`, но с отчетом количества.
2. Добавить отчеты-счетчики:
   - Количество `from core.agent` в `modules`.
   - Количество `from core.credentials` в `modules`.
   - Количество `from core.marketplace` в `modules`.
3. Зафиксировать целевые нули для этих счетчиков к концу раздела 6.

Done:
- Есть автоматический отчет по нарушающим импортам.
- Есть измеримая метрика прогресса.

---

## раздел 2. Runtime decoupling от Agent (блокер всего рефакторинга)

Цель:
- Убрать прямую зависимость `core/runtime` от agent-домена.

Почему это блокер:
- Пока `core/runtime/runtime.py` импортирует `core.agent.*`, перенос agents в `modules` гарантированно ломает runtime.

Шаги:
1. Убрать импорты `core.agent.*` из `core/runtime/runtime.py`.
2. Заменить типизированные поля `agent_manager`, `agent_registry`, `mtls_ca` на слабосвязанные атрибуты (`Any | None`) или protocol-интерфейсы в `core/runtime/runtime_context.py`.
3. Инициализацию agent-компонентов оставить только в `modules/agent/module.py`.
4. Runtime должен работать при отсутствии agent-модуля (already optional).
5. Проверить запуск bootstrap с `ModuleSpec("agent", required=False)`.

Тесты после раздела:
- `pytest -v tests/test_runtime_module_contract.py`
- `pytest -v tests/test_agent_enrollment.py tests/test_agent_deploy.py`

Done:
- В `core/runtime/*` нет импортов из `core.agent.*`.
- Агентная инициализация происходит только через модуль.

---

## раздел 3. Совместимость-слой для доменных пакетов (alias-first)

Цель:
- Подготовить безопасный перенос `core/agent`, `core/credentials`, `core/marketplace` без массовой поломки.

Шаги:
1. Ввести каноничные точки входа в `modules`:
   - `modules/agents/`
   - `modules/credentials/`
   - `modules/marketplace/`
2. Создать внутри них публичные API-файлы (`api.py`/`__init__.py`) и реэкспортировать текущие реализации.
3. Переключать импорты в `modules/*` на новые canonical imports по одному домену за раз.
4. В `core/*` временно оставить тонкие re-export shim-файлы (до раздела 7).

Правило раздела:
- Сначала меняются импорты потребителей, затем физический перенос файлов.

Тесты после раздела:
- `pytest -v tests/test_agent*.py`
- `pytest -v tests/test_credential*.py`
- `pytest -v tests/test_marketplace*.py tests/test_marketplace_flow_integration.py`

Done:
- Основные потребители в `modules` импортируют домены из `modules`, а не из `core`.
- Shim-слой в `core` закрывает обратную совместимость.

---

## раздел 4. Перенос Agent-домена в modules/agents

Цель:
- Сделать единый source of truth по агентам в `modules/agents`.

Шаги:
1. Перенести реализацию из `core/agent/*` (enrollment, registry, tls, identity, deployment_tracker, log_store) в `modules/agents/`.
2. Синхронизировать с существующими файлами `modules/agent/*` и `modules/agents/agent_deploy_service.py`.
3. Выбрать единую схему:
   - `modules/agent` как runtime module-обертка,
   - `modules/agents` как доменная реализация.
4. Оставить в `core/agent/*` только временные compatibility re-exports.

Тесты после раздела:
- `pytest -v tests/test_agent_enrollment.py tests/test_agent_deploy.py tests/test_agent_logs_status.py`

Done:
- Реальная логика агента только в `modules/agents`.
- `modules/agent/module.py` обращается к `modules/agents`, а не к `core/agent`.

---

## раздел 5. Перенос Credentials и Marketplace в modules

Цель:
- Убрать бизнес-домен из `core` для credentials/marketplace.

Шаги (credentials):
1. Перенести `core/credentials/*` в `modules/credentials/domain/` (или эквивалент).
2. Обновить импорты в:
   - `modules/credentials/*`
   - `modules/admin/credentials_handlers.py`
   - `modules/ssh/ssh_execution_service.py`
   - `modules/agents/agent_deploy_service.py`
3. Оставить `core/credentials/*` как shim до раздела 7.

Шаги (marketplace):
1. Перенести `core/marketplace/*` в `modules/marketplace/domain/`.
2. Обновить `modules/marketplace/services.py`.
3. Оставить `core/marketplace/*` как shim до раздела 7.

Тесты после раздела:
- `pytest -v tests/test_credential*.py`
- `pytest -v tests/test_marketplace*.py tests/test_marketplace_flow_integration.py`

Done:
- В `modules` нет импорта `core.credentials` и `core.marketplace` (кроме временно допустимых точек, задокументированных в debt-list).

---

## раздел 6. Execution consolidation (SSH + remote)

Цель:
- Сделать execution единой точкой выполнения.

Шаги:
1. Добавить SSH backend/provider в execution-контур:
   - Конвертировать `modules/ssh/ssh_execution_service.py` в backend-реализацию для execution.
2. Перевести `modules/admin/services/ssh_terminal.py` на execution API (без прямого paramiko-оркестратора внутри admin).
3. Свести remote execution к одному пути:
   - Либо через execution backend,
   - Либо через единый адаптер из `core/operations/executor.py`.
4. Убрать прямые вызовы устаревших маршрутизаторов из прикладных модулей.

Тесты после раздела:
- `pytest -v tests/test_plugin_isolation.py tests/test_remote_providers.py tests/test_capability_protocol.py`
- `pytest -v tests/test_robustness_p0.py`

Done:
- SSH/remote/process/container управляются через execution-слой.
- `admin` не содержит низкоуровневой SSH бизнес-логики.

---

## раздел 7. Cleanup core структуры + удаление legacy (после green)

Цель:
- Удалить legacy-дубли только после полной совместимости и green tests.

Шаги:
1. Перенести плоские infra-файлы в подсистемы:
   - `core/config.py` -> `core/config/config.py` + совместимый `core/config.py` shim (временно).
   - `core/health_monitor.py` -> `core/observability/health_monitor.py` + shim.
   - `core/logger_helper.py` -> `core/observability/logger.py` + shim.
   - `core/service_registry.py` -> `core/messaging/service_registry.py` + shim.
   - `core/storage*.py` -> `core/storage/*` + shims.
2. Только после миграции потребителей удалить legacy:
   - `core/execution_router.py`
   - `core/remote_executor.py`
   - `core/remote_provider.py`
   - `core/security.py` (если все переходят на `core/security/*` package exports)
3. Обновить `core/__init__.py` и публичные экспорты.

Тесты после раздела:
- полный `pytest -v`
- при возможности интеграционные из `docs/test_*.py`

Done:
- В `core` нет плоских дублирующих legacy-файлов.
- Удаление legacy не ломает тесты.

---

## раздел 8. Enforce архитектурных правил (строго)

Цель:
- Зафиксировать новое состояние правилами, чтобы не было отката.

Шаги:
1. Запретить в CI:
   - `core` импортирует `modules` (runtime imports).
   - `modules` импортируют `plugins`.
2. Запретить `modules` -> `core.agent|core.credentials|core.marketplace`.
3. Оставить whitelist только для специально оговоренных compatibility-слоев (на ограниченный период).
4. Обновить архитектурный документ в `docs/`.

Done:
- Правила автоматически проверяются и блокируют нарушение архитектуры.

---

## раздел 9. Финализация и долг

Цель:
- Закрыть migration debt и упростить поддержку.

Шаги:
1. Удалить все временные shim/re-export файлы.
2. Очистить deprecated импорты в тестах и скриптах.
3. Прогнать финальный full test sweep + smoke сценарии.
4. Зафиксировать финальную структуру в README/docs.

Done:
- Нет migration shim'ов.
- Архитектура соответствует целевой модели.

---

## 5) Практический порядок выполнения (чтобы не сломать runtime)

1. раздел 0
2. раздел 1
3. раздел 2 (runtime decoupling)
4. раздел 3 (alias-first)
5. раздел 4 (agents)
6. раздел 5 (credentials + marketplace)
7. раздел 6 (execution consolidation)
8. раздел 7 (cleanup core + delete legacy)
9. раздел 8
10. раздел 9

---

## 6) Риски и как их гасить

Риск A: поломка загрузки модулей
- Митигировать: не менять контракт `modules.<name> -> <Name>Module` до конца миграции.

Риск B: runtime циклы при переносе agent
- Митигировать: сначала decoupling в `core/runtime/runtime.py`, потом перенос.

Риск C: удаление `core/remote_*` ломает операции и тесты
- Митигировать: сначала интегрировать remote в execution-контур и обновить `core/operations/executor.py`.

Риск D: взрыв импортов в тестах
- Митигировать: массовая миграция импортов отдельным commit после каждого доменного раздела.

---

## 7) Минимальный трекер прогресса (рекомендуемый)

На каждый раздел фиксировать:
- `import_debt_count`:
  - `core <- modules` runtime imports
  - `modules -> core.agent|core.credentials|core.marketplace`
- Набор тестов раздела: pass/fail
- Список временных shim-файлов: добавлено/удалено

раздел считается завершенным только если:
- Тесты раздела green
- Debt-count не вырос
- Нет новых архитектурных нарушений
